#!/usr/bin/env python3
"""Crop a PDF figure/table with margin and edge-tightness verification."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageStat

from artifact_contract import (
    load_figure_manifest_for_source,
    publish_cropped_figure_asset,
)
from crop_pdf_region import parse_bbox, require_pdfplumber
from figure_package import (
    FigurePackageError,
    exclusive_figure_package_lock,
)
from paper_naming import NamingError, sha256_file


def expand_bbox(
    bbox: tuple[float, float, float, float],
    margin: float,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    left, top, right, bottom = bbox
    return (
        max(0.0, left - margin),
        max(0.0, top - margin),
        min(page_width, right + margin),
        min(page_height, bottom + margin),
    )


def edge_dark_fraction(image_path: Path, edge_px: int = 8, threshold: int = 245) -> dict:
    image = Image.open(image_path).convert("L")
    width, height = image.size
    edge_px = max(1, min(edge_px, width // 4, height // 4))
    boxes = {
        "left": (0, 0, edge_px, height),
        "right": (width - edge_px, 0, width, height),
        "top": (0, 0, width, edge_px),
        "bottom": (0, height - edge_px, width, height),
    }
    result = {}
    for name, box in boxes.items():
        crop = image.crop(box)
        dark = crop.point(lambda p: 255 if p < threshold else 0)
        stat = ImageStat.Stat(dark)
        result[name] = round(stat.mean[0] / 255.0, 4)
    return result


def crop_page(pdf_path: Path, page_number: int, bbox: tuple[float, float, float, float], out: Path, dpi: int) -> None:
    pdfplumber = require_pdfplumber()
    out.parent.mkdir(parents=True, exist_ok=True)
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_number - 1]
        page.crop(bbox, strict=False).to_image(resolution=dpi).save(out, format="PNG")


def page_size(pdf_path: Path, page_number: int) -> tuple[float, float]:
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_number - 1]
        return float(page.width), float(page.height)


def quality_status(edges: dict, tight_threshold: float) -> tuple[str, list[str]]:
    warnings = [
        f"{edge} edge has high non-white density ({value})"
        for edge, value in edges.items()
        if value >= tight_threshold
    ]
    return ("needs_review" if warnings else "verified", warnings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--bbox", type=parse_bbox, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=240)
    parser.add_argument("--margin", type=float, default=12.0, help="PDF-point margin added around bbox")
    parser.add_argument("--edge-px", type=int, default=10)
    parser.add_argument("--tight-threshold", type=float, default=0.03)
    parser.add_argument("--label", default="")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if not args.pdf.exists():
        raise SystemExit(f"PDF not found: {args.pdf}")
    if not args.pdf.is_file() or args.pdf.suffix.casefold() != ".pdf":
        raise SystemExit(f"Input must be a PDF file: {args.pdf}")
    if args.page < 1:
        raise SystemExit("--page must be 1 or greater")

    args.pdf = args.pdf.resolve()
    args.out = args.out.resolve()
    args.manifest = args.manifest.resolve()
    try:
        with exclusive_figure_package_lock(args.manifest.parent):
            load_figure_manifest_for_source(
                args.manifest,
                source_pdf=args.pdf,
            )
    except (FigurePackageError, NamingError) as exc:
        raise SystemExit(str(exc)) from exc
    expected_figures_dir = args.manifest.parent / "figures"
    try:
        relative_output = args.out.relative_to(args.manifest.parent)
        args.out.relative_to(expected_figures_dir)
    except ValueError as exc:
        raise SystemExit(
            "--out must stay under the manifest's extracted/figures "
            "directory"
        ) from exc

    source_sha256 = sha256_file(args.pdf)
    width, height = page_size(args.pdf, args.page)
    expanded = expand_bbox(args.bbox, args.margin, width, height)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".figure-stage-",
            dir=args.manifest.parent,
        )
    )
    staged_output = staging / relative_output
    staged_output.parent.mkdir(parents=True)
    preserve_staging = False
    try:
        crop_page(
            args.pdf,
            args.page,
            expanded,
            staged_output,
            args.dpi,
        )
        if sha256_file(args.pdf) != source_sha256:
            raise RuntimeError(
                "The source PDF changed during cropping; existing assets "
                "were left untouched"
            )
        edges = edge_dark_fraction(staged_output, edge_px=args.edge_px)
        status, warnings = quality_status(edges, args.tight_threshold)
        record = {
            "kind": "verified_crop",
            "label": args.label,
            "page": args.page,
            "original_bbox": list(args.bbox),
            "expanded_bbox": list(expanded),
            "margin": args.margin,
            "dpi": args.dpi,
            "verification": {
                "status": status,
                "edge_dark_fraction": edges,
                "warnings": warnings,
                "note": (
                    "Edge check detects likely tight crops; visual review "
                    "is still required."
                ),
            },
        }

        publish_cropped_figure_asset(
            args.manifest,
            source_pdf=args.pdf,
            staging=staging,
            asset_path=args.out,
            record=record,
        )
    except FigurePackageError as exc:
        preserve_staging = exc.preserve_staging
        raise SystemExit(str(exc)) from exc
    except (NamingError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        if not preserve_staging:
            shutil.rmtree(staging, ignore_errors=True)

    print(f"Wrote {args.out}")
    print(f"Status: {status}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
