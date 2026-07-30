#!/usr/bin/env python3
"""Create a canonically named per-paper report workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path

from paper_naming import (
    AFFILIATION_UNKNOWN,
    NAMING_RULE,
    NamingError,
    PaperNaming,
    build_paper_naming,
    collision_suffix_from_identity,
    doi_is_valid,
    identity_matches_index,
    normalize_doi,
    normalize_language_tag,
    portable_units,
    sha256_file,
    validate_index_contract,
)
from safe_json import (
    ConcurrentUpdateError,
    atomic_write_json_if_unchanged,
    exclusive_update_lock,
)


WINDOWS_SAFE_PATH_UNITS = 259


def load_workspace_index(workspace: Path) -> tuple[dict, PaperNaming]:
    path = workspace / "paper_index.json"
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NamingError(
            f"Existing workspace has no paper_index.json: {workspace}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise NamingError(
            f"Existing paper_index.json is not valid UTF-8: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise NamingError(
            f"Existing paper_index.json is invalid JSON: {path}: {exc}"
        ) from exc
    if not isinstance(index, dict):
        raise NamingError(f"Existing paper index is not a JSON object: {path}")
    try:
        indexed_naming = validate_index_contract(index)
    except NamingError as exc:
        raise NamingError(
            f"Existing workspace has invalid naming metadata: "
            f"{workspace}: {exc}"
        ) from exc
    if workspace.name != indexed_naming.paper_id:
        raise NamingError(
            "Existing workspace directory does not exactly match its "
            f"paper_id: {workspace}"
        )

    required_paths = [
        workspace / indexed_naming.report_filename,
        workspace / "source.pdf",
        workspace / "evidence_cards.md",
        workspace / "extracted",
        workspace / "extracted" / "figures",
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise NamingError(
            "Existing workspace is incomplete; missing: " + ", ".join(missing)
        )
    if not (workspace / indexed_naming.report_filename).is_file():
        raise NamingError("Existing canonical report path is not a file")
    if not (workspace / "source.pdf").is_file():
        raise NamingError("Existing canonical source.pdf path is not a file")
    if not (workspace / "evidence_cards.md").is_file():
        raise NamingError("Existing evidence_cards.md path is not a file")
    if not (workspace / "extracted").is_dir() or not (
        workspace / "extracted" / "figures"
    ).is_dir():
        raise NamingError("Existing extracted paths must be directories")

    actual_sha = sha256_file(workspace / "source.pdf")
    indexed_sha = str(index["metadata"]["source_sha256"])
    if actual_sha != indexed_sha:
        raise NamingError(
            "Existing source.pdf hash does not match paper_index.json"
        )
    return index, indexed_naming


def filesystem_key(value: str) -> str:
    """Approximate case-insensitive Unicode filename comparison."""
    return unicodedata.normalize("NFKC", value).casefold()


def find_existing_workspace(out_root: Path, paper_id: str) -> Path | None:
    expected_key = filesystem_key(paper_id)
    if not out_root.exists():
        return None
    matches = [
        child
        for child in out_root.iterdir()
        if child.is_dir() and filesystem_key(child.name) == expected_key
    ]
    if len(matches) > 1:
        rendered = ", ".join(str(path) for path in sorted(matches))
        raise NamingError(
            "Multiple filesystem-equivalent workspaces are ambiguous: "
            f"{rendered}"
        )
    return matches[0] if matches else None


def find_collision_workspaces(
    out_root: Path, base_paper_id: str
) -> list[Path]:
    if not out_root.exists():
        return []
    pattern = re.compile(
        rf"^{re.escape(filesystem_key(base_paper_id))}-"
        r"(?:doi|sha)-[0-9a-f]{8}$"
    )
    matches = sorted(
        (
            child
            for child in out_root.iterdir()
            if child.is_dir()
            and pattern.fullmatch(filesystem_key(child.name))
        ),
        key=lambda path: filesystem_key(path.name),
    )
    seen: dict[str, Path] = {}
    for match in matches:
        key = filesystem_key(match.name)
        if key in seen:
            raise NamingError(
                "Multiple filesystem-equivalent collision workspaces are "
                f"ambiguous: {seen[key]}, {match}"
            )
        seen[key] = match
    return matches


def same_identity(
    workspace: Path,
    *,
    normalized_doi: str,
    source_sha256: str,
) -> tuple[bool, PaperNaming]:
    index, indexed_naming = load_workspace_index(workspace)
    metadata = index["metadata"]
    indexed_doi = normalize_doi(str(metadata["doi"]))
    indexed_sha256 = str(metadata["source_sha256"])
    if (
        indexed_sha256 == source_sha256
        and indexed_doi
        and normalized_doi
        and indexed_doi != normalized_doi
    ):
        raise NamingError(
            "The same source PDF is associated with conflicting DOI values: "
            f"{indexed_doi!r} and {normalized_doi!r}"
        )
    matches = identity_matches_index(
        index,
        normalized_doi=normalized_doi,
        source_sha256=source_sha256,
    )
    return matches, indexed_naming


def enrich_workspace_doi(
    workspace: Path,
    *,
    normalized_doi: str,
    source_sha256: str,
) -> None:
    if not normalized_doi:
        return
    index_path = workspace / "paper_index.json"
    try:
        with exclusive_update_lock(index_path):
            expected_index_sha256 = sha256_file(index_path)
            index, _ = load_workspace_index(workspace)
            indexed_doi = str(index["metadata"]["doi"])
            if indexed_doi == normalized_doi:
                return
            if indexed_doi:
                raise NamingError(
                    "Existing workspace has a different DOI and cannot be "
                    "enriched"
                )
            if not identity_matches_index(
                index,
                normalized_doi=normalized_doi,
                source_sha256=source_sha256,
            ):
                raise NamingError(
                    "Existing workspace identity changed before DOI enrichment"
                )
            index["metadata"]["doi"] = normalized_doi
            notes = index.setdefault("notes", [])
            if isinstance(notes, list):
                note = (
                    "DOI metadata was added during explicit workspace reuse; "
                    "the original deterministic collision basis was retained."
                )
                if note not in notes:
                    notes.append(note)
            validate_index_contract(index)
            atomic_write_json_if_unchanged(
                index_path,
                index,
                expected_sha256=expected_index_sha256,
            )
    except ConcurrentUpdateError as exc:
        raise NamingError(str(exc)) from exc
    print(f"Enriched DOI metadata in {index_path}")


def reuse_or_fail(
    workspace: Path,
    *,
    indexed_naming: PaperNaming,
    reuse_existing: bool,
    normalized_doi: str,
    source_sha256: str,
) -> bool:
    if not reuse_existing:
        raise NamingError(
            f"Workspace already exists for the same paper: {workspace}. "
            "Use --reuse-existing to keep its report and assets."
        )
    enrich_workspace_doi(
        workspace,
        normalized_doi=normalized_doi,
        source_sha256=source_sha256,
    )
    report_path = workspace / indexed_naming.report_filename
    print(f"Reusing workspace without replacing report or assets: {workspace}")
    print(f"Report: {report_path}")
    return True


def choose_naming(
    *,
    args: argparse.Namespace,
    out_root: Path,
    source_sha256: str,
    normalized_doi: str,
) -> tuple[PaperNaming, bool]:
    base = build_paper_naming(
        publication_year=args.year,
        document_type_code=args.document_type,
        venue_abbr=args.venue_abbr,
        first_author_affiliation_abbr=args.first_author_affiliation_abbr,
        short_title=args.short_title,
    )
    collision_suffix, _ = collision_suffix_from_identity(
        doi=normalized_doi,
        source_sha256=source_sha256,
    )
    collided = build_paper_naming(
        publication_year=args.year,
        document_type_code=args.document_type,
        venue_abbr=args.venue_abbr,
        first_author_affiliation_abbr=args.first_author_affiliation_abbr,
        short_title=args.short_title,
        collision_suffix=collision_suffix,
    )

    existing = find_existing_workspace(out_root, base.paper_id)
    collision_workspaces = find_collision_workspaces(
        out_root, base.base_paper_id
    )
    same_collision_workspaces: list[tuple[Path, PaperNaming]] = []
    collided_existing: Path | None = None
    collided_key = filesystem_key(collided.paper_id)
    for collision_workspace in collision_workspaces:
        collision_same, collision_indexed_naming = same_identity(
            collision_workspace,
            normalized_doi=normalized_doi,
            source_sha256=source_sha256,
        )
        if filesystem_key(collision_workspace.name) == collided_key:
            collided_existing = collision_workspace
        if collision_same:
            same_collision_workspaces.append(
                (collision_workspace, collision_indexed_naming)
            )

    base_same = False
    base_indexed_naming: PaperNaming | None = None
    if existing is not None:
        base_same, base_indexed_naming = same_identity(
            existing,
            normalized_doi=normalized_doi,
            source_sha256=source_sha256,
        )

    same_workspace_count = len(same_collision_workspaces) + int(base_same)
    if same_workspace_count > 1:
        raise NamingError(
            "Multiple canonical workspaces already claim the same paper "
            "identity; resolve the duplicates before continuing"
        )

    if base_same:
        assert existing is not None and base_indexed_naming is not None
        reuse_or_fail(
            existing,
            indexed_naming=base_indexed_naming,
            reuse_existing=args.reuse_existing,
            normalized_doi=normalized_doi,
            source_sha256=source_sha256,
        )
        return base_indexed_naming, True

    if same_collision_workspaces:
        same_workspace, same_indexed_naming = same_collision_workspaces[0]
        reuse_or_fail(
            same_workspace,
            indexed_naming=same_indexed_naming,
            reuse_existing=args.reuse_existing,
            normalized_doi=normalized_doi,
            source_sha256=source_sha256,
        )
        return same_indexed_naming, True

    if existing is None:
        if collided_existing is None:
            return base, False
        raise NamingError(
            "The deterministic collision workspace is occupied by a "
            f"different paper: {collided_existing}"
        )

    if collided_existing is None:
        return collided, False
    raise NamingError(
        "A different paper already occupies both the base and deterministic "
        f"collision workspace: {collided_existing}"
    )


def build_index(
    *,
    args: argparse.Namespace,
    title: str,
    naming: PaperNaming,
    source_sha256: str,
    normalized_doi: str,
) -> dict:
    collision_basis = ""
    if naming.collision_suffix:
        collision_basis = "doi-sha256" if normalized_doi else "source-sha256"
    return {
        "schema_version": 2,
        "naming_algorithm": "paper-id-v1",
        "paper_id": naming.paper_id,
        "base_paper_id": naming.base_paper_id,
        "report_filename": naming.report_filename,
        "report_language": args.language,
        "metadata": {
            "title": title,
            "authors": [],
            "publication_year": naming.publication_year,
            "document_type": args.document_type,
            "document_type_code": naming.document_type_code,
            "venue_full": args.venue_full,
            "venue_abbr": naming.venue_abbr,
            "doi": normalized_doi,
            "source_pdf": "source.pdf",
            "source_original_filename": args.pdf.name,
            "source_sha256": source_sha256,
            "first_author_affiliation_full": (
                args.first_author_affiliation_full
            ),
            "first_author_affiliation_abbr": (
                naming.first_author_affiliation_abbr
            ),
            "first_author_other_affiliations": (
                args.first_author_other_affiliation
            ),
            "affiliation_evidence": args.affiliation_evidence,
        },
        "naming": {
            "algorithm": "paper-id-v1",
            "rule": NAMING_RULE,
            "base_paper_id": naming.base_paper_id,
            "short_title": naming.short_title,
            "collision_suffix": naming.collision_suffix,
            "collision_basis": collision_basis,
        },
        "section_candidates": [],
        "claims_to_verify": [],
        "contributions": [],
        "method_modules": [],
        "formulas": [],
        "figures_and_tables": [],
        "experiments": [],
        "limitations": [],
        "notes": [
            "Complete metadata and evidence by checking the original PDF.",
            "Do not replace first-author affiliation with corresponding-author affiliation.",
        ],
    }


def render_template(
    template: str,
    *,
    args: argparse.Namespace,
    title: str,
    naming: PaperNaming,
) -> str:
    replacements = {
        "{{TITLE}}": title,
        "{{PDF_FILE}}": "source.pdf",
        "{{PAPER_ID}}": naming.paper_id,
        "{{REPORT_FILENAME}}": naming.report_filename,
        "{{PUBLICATION_YEAR}}": naming.publication_year,
        "{{DOCUMENT_TYPE_CODE}}": naming.document_type_code,
        "{{VENUE_FULL}}": args.venue_full or "TODO",
        "{{VENUE_ABBR}}": naming.venue_abbr,
        "{{FIRST_AUTHOR_AFFILIATION_FULL}}": (
            args.first_author_affiliation_full or "TODO"
        ),
        "{{FIRST_AUTHOR_AFFILIATION_ABBR}}": (
            naming.first_author_affiliation_abbr
        ),
        "{{AFFILIATION_EVIDENCE}}": args.affiliation_evidence or "TODO",
    }
    rendered = template
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--title", default="")
    parser.add_argument("--short-title", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--document-type", required=True)
    parser.add_argument("--venue-abbr", required=True)
    parser.add_argument("--venue-full", default="")
    parser.add_argument(
        "--first-author-affiliation-abbr",
        default=AFFILIATION_UNKNOWN,
    )
    parser.add_argument("--first-author-affiliation-full", default="")
    parser.add_argument(
        "--first-author-other-affiliation",
        action="append",
        default=[],
    )
    parser.add_argument("--affiliation-evidence", default="")
    parser.add_argument("--doi", default="")
    parser.add_argument("--language", required=True)
    parser.add_argument("--out-root", type=Path, default=Path("reports"))
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument("--allow-long-paths", action="store_true")
    args = parser.parse_args()

    if not args.pdf.exists():
        raise SystemExit(f"PDF not found: {args.pdf}")
    if not args.pdf.is_file() or args.pdf.suffix.casefold() != ".pdf":
        raise SystemExit(f"Input must be a PDF file: {args.pdf}")

    skill_dir = Path(__file__).resolve().parents[1]
    template_path = args.template or skill_dir / "assets" / "report_template.md"
    if not template_path.exists():
        raise SystemExit(f"Template not found: {template_path}")

    args.pdf = args.pdf.resolve()
    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    title = args.title or args.pdf.stem
    source_sha256 = sha256_file(args.pdf)
    normalized_doi = normalize_doi(args.doi)
    if normalized_doi and not doi_is_valid(normalized_doi):
        raise SystemExit(f"Invalid DOI: {args.doi!r}")
    try:
        args.language = normalize_language_tag(args.language)
    except NamingError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        naming, reused = choose_naming(
            args=args,
            out_root=out_root,
            source_sha256=source_sha256,
            normalized_doi=normalized_doi,
        )
    except NamingError as exc:
        raise SystemExit(str(exc)) from exc
    if reused:
        if sha256_file(args.pdf) != source_sha256:
            raise SystemExit(
                "The input PDF changed while the existing workspace was "
                "being checked; retry the operation"
            )
        return 0

    out_dir = out_root / naming.paper_id
    report_path = out_dir / naming.report_filename
    if (
        os.name == "nt"
        and portable_units(str(report_path)) > WINDOWS_SAFE_PATH_UNITS
        and not args.allow_long_paths
    ):
        raise SystemExit(
            "The canonical report path exceeds the conservative Windows "
            f"{WINDOWS_SAFE_PATH_UNITS}-unit limit. Use a shorter --short-title "
            "or pass --allow-long-paths when long paths are enabled."
        )

    template = template_path.read_text(encoding="utf-8")
    report = render_template(
        template,
        args=args,
        title=title,
        naming=naming,
    )
    index = build_index(
        args=args,
        title=title,
        naming=naming,
        source_sha256=source_sha256,
        normalized_doi=normalized_doi,
    )
    try:
        validate_index_contract(index)
    except NamingError as exc:
        raise SystemExit(f"Internal index validation failed: {exc}") from exc
    evidence_title = (
        "# 证据卡\n\n"
        if args.language.split("-", 1)[0] == "zh"
        else "# Evidence Cards\n\n"
    )

    temporary = Path(
        tempfile.mkdtemp(prefix=".paper-stage-", dir=out_root)
    )
    try:
        (temporary / "extracted" / "figures").mkdir(parents=True)
        shutil.copy2(args.pdf, temporary / "source.pdf")
        copied_sha256 = sha256_file(temporary / "source.pdf")
        if copied_sha256 != source_sha256:
            raise NamingError(
                "The input PDF changed while it was being copied; "
                "no workspace was published"
            )
        (temporary / naming.report_filename).write_text(
            report,
            encoding="utf-8",
            newline="\n",
        )
        (temporary / "evidence_cards.md").write_text(
            evidence_title,
            encoding="utf-8",
            newline="\n",
        )
        (temporary / "paper_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if os.name != "nt":
            os.chmod(temporary, out_root.stat().st_mode & 0o777)
        temporary.rename(out_dir)
    except NamingError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise SystemExit(str(exc)) from exc
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    print(f"Wrote {out_dir / naming.report_filename}")
    print(f"Wrote {out_dir / 'evidence_cards.md'}")
    print(f"Wrote {out_dir / 'paper_index.json'}")
    print(f"Workspace: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
