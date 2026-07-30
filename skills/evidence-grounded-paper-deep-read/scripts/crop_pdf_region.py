#!/usr/bin/env python3
"""Crop a precise figure/table region from a PDF page.

Coordinates are PDF points in pdfplumber/PDF coordinate space:
left top right bottom, with origin at the top-left of the page.
Use page previews to inspect the page and choose the bounding box.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from artifact_contract import (
    load_figure_manifest_for_source,
    publish_cropped_figure_asset,
)
from figure_package import (
    FigurePackageError,
    exclusive_figure_package_lock,
)
from paper_naming import NamingError, sha256_file


def require_pdfplumber():
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "pdfplumber is required for region cropping. Install with: python -m pip install pdfplumber"
        ) from exc
    return pdfplumber


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be 'left,top,right,bottom'")
    try:
        left, top, right, bottom = [float(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox values must be numbers") from exc
    if right <= left or bottom <= top:
        raise argparse.ArgumentTypeError("bbox must satisfy right > left and bottom > top")
    return left, top, right, bottom


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--page", type=int, required=True, help="1-based page number")
    parser.add_argument("--bbox", type=parse_bbox, required=True, help="left,top,right,bottom")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=220)
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
    pdfplumber = require_pdfplumber()
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
        with pdfplumber.open(args.pdf) as pdf:
            if args.page > len(pdf.pages):
                raise RuntimeError(
                    f"Page {args.page} out of range; PDF has "
                    f"{len(pdf.pages)} pages"
                )
            page = pdf.pages[args.page - 1]
            cropped = page.crop(args.bbox, strict=False)
            cropped.to_image(resolution=args.dpi).save(
                staged_output,
                format="PNG",
            )
        if sha256_file(args.pdf) != source_sha256:
            raise RuntimeError(
                "The source PDF changed during cropping; existing assets "
                "were left untouched"
            )

        record = {
            "kind": "cropped_region",
            "label": args.label,
            "page": args.page,
            "bbox": list(args.bbox),
            "dpi": args.dpi,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
