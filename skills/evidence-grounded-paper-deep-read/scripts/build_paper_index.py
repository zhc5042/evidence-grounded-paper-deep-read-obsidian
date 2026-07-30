#!/usr/bin/env python3
"""Merge extracted text and figure metadata into an existing paper index."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from artifact_contract import validate_figure_manifest_items
from figure_package import (
    FigurePackageError,
    exclusive_figure_package_lock,
)
from paper_naming import (
    NamingError,
    sha256_file,
    validate_index_contract,
)
from safe_json import (
    ConcurrentUpdateError,
    atomic_write_json_if_unchanged,
    exclusive_update_lock,
)


SECTION_PATTERNS = [
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "methodology",
    "approach",
    "experiment",
    "experiments",
    "results",
    "analysis",
    "discussion",
    "limitation",
    "limitations",
    "conclusion",
    "references",
]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Required JSON file not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"JSON file is not valid UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def looks_like_heading(text: str) -> bool:
    compact = re.sub(
        r"^\d+(?:\.\d+)*(?:[.)])?\s*",
        "",
        text.strip(),
    ).lower()
    if len(compact) > 80:
        return False
    return any(compact.startswith(pattern) for pattern in SECTION_PATTERNS)


def collect_section_candidates(sections: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    pages = sections.get("pages")
    if not isinstance(pages, list):
        return candidates
    for page in pages:
        if not isinstance(page, dict):
            continue
        paragraphs = page.get("paragraphs")
        if not isinstance(paragraphs, list):
            continue
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            text = str(paragraph.get("text") or "")
            first_line = text.splitlines()[0] if text else ""
            if looks_like_heading(first_line):
                candidates.append(
                    {
                        "heading": first_line.strip(),
                        "page": page.get("page"),
                        "paragraph_id": paragraph.get("id"),
                    }
                )
    return candidates


def verify_index_identity(index: dict[str, Any], out_path: Path) -> None:
    if out_path.name != "paper_index.json":
        raise ValueError("--out must point to canonical paper_index.json")
    try:
        expected = validate_index_contract(index)
    except NamingError as exc:
        raise ValueError(f"Invalid naming metadata in {out_path}: {exc}") from exc

    if out_path.parent.name != expected.paper_id:
        raise ValueError(
            "paper_index.json parent directory must equal paper_id: "
            f"{out_path.parent.name!r} != {expected.paper_id!r}"
        )
    source_path = out_path.parent / "source.pdf"
    if not source_path.is_file():
        raise ValueError(f"Canonical source PDF not found: {source_path}")
    if sha256_file(source_path) != index["metadata"]["source_sha256"]:
        raise ValueError(
            "Canonical source.pdf hash does not match paper_index.json"
        )


def verify_extraction_manifest(
    manifest: dict[str, Any],
    *,
    path: Path,
    expected_source_sha256: str,
) -> None:
    manifest_sha = manifest.get("source_sha256")
    if manifest_sha != expected_source_sha256:
        raise ValueError(
            f"{path.name} source_sha256 does not match paper_index.json"
        )
    if manifest.get("source_pdf") != "source.pdf":
        raise ValueError(
            f"{path.name} source_pdf must be the canonical source.pdf"
        )


def merge_index(out_path: Path, extracted_path: Path) -> None:
    original_index_sha256 = (
        sha256_file(out_path) if out_path.is_file() else ""
    )
    try:
        index = load_json(out_path)
        verify_index_identity(index, out_path)
        sections_path = extracted_path / "sections.json"
        figures_path = extracted_path / "figure_manifest.json"
        sections = load_json(sections_path)
        figures = load_json(figures_path)
        expected_source_sha256 = index["metadata"]["source_sha256"]
        verify_extraction_manifest(
            sections,
            path=sections_path,
            expected_source_sha256=expected_source_sha256,
        )
        verify_extraction_manifest(
            figures,
            path=figures_path,
            expected_source_sha256=expected_source_sha256,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    if not isinstance(sections.get("pages"), list):
        raise RuntimeError("sections.json field 'pages' must be an array")
    try:
        figure_items = validate_figure_manifest_items(
            figures.get("items"),
            extracted_dir=extracted_path,
        )
    except NamingError as exc:
        raise RuntimeError(str(exc)) from exc

    index["section_candidates"] = collect_section_candidates(sections)
    index["figures_and_tables"] = figure_items
    extraction = index.setdefault("extraction", {})
    if not isinstance(extraction, dict):
        raise RuntimeError(
            "paper_index.json field 'extraction' must be an object"
        )
    extraction.update(
        {
            "sections_json": "extracted/sections.json",
            "figure_manifest_json": "extracted/figure_manifest.json",
            "source_pdf": "source.pdf",
            "source_sha256": expected_source_sha256,
        }
    )

    notes = index.setdefault("notes", [])
    if not isinstance(notes, list):
        raise RuntimeError("paper_index.json field 'notes' must be an array")
    extraction_note = (
        "Section candidates and figure items are extraction aids; verify them "
        "against source.pdf before treating them as evidence."
    )
    if extraction_note not in notes:
        notes.append(extraction_note)

    try:
        validate_index_contract(index)
    except NamingError as exc:
        raise RuntimeError(str(exc)) from exc
    atomic_write_json_if_unchanged(
        out_path,
        index,
        expected_sha256=original_index_sha256,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Update extraction-derived fields while preserving canonical naming "
            "metadata and manually curated evidence."
        )
    )
    parser.add_argument("--extracted", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    out_path = args.out.resolve()
    extracted_path = args.extracted.resolve()
    expected_extracted_path = out_path.parent / "extracted"
    if extracted_path != expected_extracted_path:
        raise SystemExit(
            "--extracted must be the canonical extracted directory beside "
            f"paper_index.json: {expected_extracted_path}"
        )
    try:
        with exclusive_figure_package_lock(
            extracted_path
        ), exclusive_update_lock(out_path):
            merge_index(out_path, extracted_path)
    except (
        ConcurrentUpdateError,
        FigurePackageError,
        RuntimeError,
    ) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Updated {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
