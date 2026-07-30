#!/usr/bin/env python3
"""Validate a canonical evidence-grounded paper report package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from artifact_contract import validate_figure_manifest_items
from paper_naming import (
    AFFILIATION_UNKNOWN,
    NamingError,
    VENUE_UNKNOWN,
    sha256_file,
    validate_index_contract,
)


ZH_REQUIRED_HEADINGS = [
    "## 0. 一句话总览",
    "## 1. 论文基本信息",
    "## 2. 作者做了什么",
    "## 3. 作者为什么要做这件事",
    "## 4. 作者具体怎么做",
    "## 5. 作者如何验证",
    "## 6. 公式与关键技术细节",
    "## 7. 创新点逐条拆解",
    "## 8. 局限性与开放问题",
    "## 9. 初学者背景补充",
    "## 10. 复现与进一步阅读建议",
    "## 11. 完整性自检",
]

EN_REQUIRED_HEADINGS = [
    "## 0. One-Sentence Overview",
    "## 1. Paper Metadata",
    "## 2. What Did The Authors Do?",
    "## 3. Why Did They Do It?",
    "## 4. How Does The Method Work?",
    "## 5. How Did They Validate It?",
    "## 6. Formula And Technical Detail Walkthrough",
    "## 7. Innovation Points",
    "## 8. Limitations And Open Questions",
    "## 9. Beginner Background Notes",
    "## 10. Reproduction Notes",
    "## 11. Completeness Checklist",
]

MIXED_LANGUAGE_HEADINGS = [
    "## 2. WHAT",
    "## 3. WHY",
    "## 4. HOW",
    "## 5. EXPERIMENT",
    "## 6. Figure And Table Deep Reading",
]

WEAK_PATTERNS = [
    r"\bimproves performance\b",
    r"\bnovel framework\b",
    r"\bproves effectiveness\b",
    r"\buseful features\b",
    r"\bsignificant results\b",
    r"提升性能",
    r"提出.*框架",
    r"证明.*有效",
]

LANGUAGE_SUFFIX_PATTERN = re.compile(
    r"(?:\.(?:zh-cn|zh|en-us|en-gb|en)\.md|"
    r"-(?:zh-cn|zh|en-us|en-gb|en)-deep-read\.md)$",
    flags=re.IGNORECASE,
)


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Required package file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"JSON file is not valid UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def forbidden_corresponding_affiliation_keys(
    value: Any,
    path: str,
    ancestors: tuple[str, ...] = (),
) -> list[str]:
    corresponding_keys = {
        "corresponding",
        "correspondingauthor",
        "通讯作者",
    }
    affiliation_keys = {
        "affiliation",
        "affiliations",
        "affiliationname",
        "institution",
        "institutions",
        "institutionname",
        "organization",
        "organizations",
        "organizationname",
        "organisation",
        "organisations",
        "organisationname",
        "unit",
        "units",
        "unitname",
        "department",
        "departments",
        "departmentname",
        "employer",
        "workplace",
        "单位",
        "所在单位",
        "机构",
        "组织",
        "部门",
        "隶属机构",
    }
    combined_keys = {
        "correspondingaffiliation",
        "correspondingauthoraffiliation",
        "correspondingauthorinstitution",
        "correspondingauthorinstitutionname",
        "correspondingauthororganization",
        "correspondingauthororganizationname",
        "correspondingauthororganisation",
        "correspondingauthororganisationname",
        "correspondingauthorunit",
        "correspondingauthorunitname",
        "correspondingauthordepartment",
        "correspondingauthordepartmentname",
        "通讯作者单位",
        "通讯作者机构",
        "通讯作者组织",
        "通讯作者部门",
        "通讯作者隶属机构",
    }
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            normalized = "".join(
                character
                for character in key_text.casefold()
                if character.isalnum()
            )
            child_path = f"{path}.{key_text}"
            if normalized in combined_keys or (
                normalized in affiliation_keys
                and any(
                    ancestor in corresponding_keys
                    for ancestor in ancestors
                )
            ):
                found.append(child_path)
            found.extend(
                forbidden_corresponding_affiliation_keys(
                    child,
                    child_path,
                    (*ancestors, normalized),
                )
            )
    elif isinstance(value, list):
        for number, child in enumerate(value):
            found.extend(
                forbidden_corresponding_affiliation_keys(
                    child,
                    f"{path}[{number}]",
                    ancestors,
                )
            )
    return found


def package_validation(
    report_path: Path,
) -> tuple[list[str], str]:
    problems: list[str] = []
    index_path = report_path.parent / "paper_index.json"
    try:
        index = load_json_object(index_path)
    except ValueError as exc:
        return [str(exc)], ""

    try:
        expected = validate_index_contract(index)
    except NamingError as exc:
        return [f"Invalid canonical naming metadata: {exc}"], ""

    naming = index.get("naming")
    metadata = index.get("metadata")
    if not isinstance(naming, dict) or not isinstance(metadata, dict):
        return [
            *problems,
            "paper_index.json requires metadata and naming objects",
        ], ""

    title = str(metadata.get("title") or "").strip()
    if not title or title.upper() == "TODO":
        problems.append("metadata.title must contain the full paper title")
    authors = metadata.get("authors")
    if (
        not isinstance(authors, list)
        or not authors
        or not all(
            isinstance(author, str) and bool(author.strip())
            for author in authors
        )
    ):
        problems.append(
            "metadata.authors must be a non-empty ordered array of strings"
        )
    venue_full = str(metadata.get("venue_full") or "").strip()
    if expected.venue_abbr != VENUE_UNKNOWN and (
        not venue_full or venue_full.upper() == "TODO"
    ):
        problems.append(
            "Known venue abbreviation requires metadata.venue_full"
        )

    if report_path.parent.name != expected.paper_id:
        problems.append(
            "Parent directory must equal paper_id: "
            f"{report_path.parent.name!r} != {expected.paper_id!r}"
        )
    if report_path.name != expected.report_filename:
        problems.append(
            "Report filename must equal <paper_id>-deep-read.md: "
            f"{report_path.name!r} != {expected.report_filename!r}"
        )
        if LANGUAGE_SUFFIX_PATTERN.search(report_path.name):
            problems.append(
                "Report filename contains a language suffix; store "
                "report_language only in paper_index.json"
            )

    report_language = str(index["report_language"])
    language = report_language.split("-", 1)[0]

    source_path = report_path.parent / "source.pdf"
    actual_sha = ""
    if not source_path.is_file():
        problems.append(f"Canonical source PDF not found: {source_path}")
    else:
        actual_sha = sha256_file(source_path)

    indexed_sha = str(metadata["source_sha256"])
    if actual_sha and indexed_sha != actual_sha:
        problems.append(
            "metadata.source_sha256 does not match the packaged source.pdf"
        )

    evidence_cards_path = report_path.parent / "evidence_cards.md"
    figures_path = report_path.parent / "extracted" / "figures"
    if not evidence_cards_path.is_file():
        problems.append(
            f"Canonical evidence_cards.md not found: {evidence_cards_path}"
        )
    if not figures_path.is_dir():
        problems.append(
            f"Canonical extracted/figures directory not found: {figures_path}"
        )

    extraction = index.get("extraction")
    if not isinstance(extraction, dict):
        problems.append(
            "paper_index.json extraction metadata is missing; run "
            "build_paper_index.py after text and figure extraction"
        )
    else:
        expected_extraction = {
            "sections_json": "extracted/sections.json",
            "figure_manifest_json": "extracted/figure_manifest.json",
            "source_pdf": "source.pdf",
            "source_sha256": indexed_sha,
        }
        for field, expected_value in expected_extraction.items():
            if extraction.get(field) != expected_value:
                problems.append(
                    f"paper_index.json extraction.{field} must be "
                    f"{expected_value!r}"
                )
        for relative_path in (
            "extracted/sections.json",
            "extracted/figure_manifest.json",
        ):
            manifest_path = report_path.parent / relative_path
            try:
                manifest = load_json_object(manifest_path)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if manifest.get("source_pdf") != "source.pdf":
                problems.append(
                    f"{relative_path} source_pdf must be source.pdf"
                )
            if manifest.get("source_sha256") != indexed_sha:
                problems.append(
                    f"{relative_path} source_sha256 does not match source.pdf"
                )
            if relative_path.endswith("sections.json"):
                if not isinstance(manifest.get("pages"), list):
                    problems.append(
                        f"{relative_path} field 'pages' must be an array"
                    )
            else:
                try:
                    figure_items = validate_figure_manifest_items(
                        manifest.get("items"),
                        extracted_dir=report_path.parent / "extracted",
                    )
                except NamingError as exc:
                    problems.append(str(exc))
                else:
                    if index.get("figures_and_tables") != figure_items:
                        problems.append(
                            "paper_index.json figures_and_tables must exactly "
                            "match figure_manifest.json items"
                        )

    affiliation_full = str(
        metadata.get("first_author_affiliation_full") or ""
    ).strip()
    affiliation_evidence = str(
        metadata.get("affiliation_evidence") or ""
    ).strip()
    if expected.first_author_affiliation_abbr != AFFILIATION_UNKNOWN:
        if not affiliation_full or affiliation_full.upper() == "TODO":
            problems.append(
                "Known first-author affiliation requires its full name in metadata"
            )
    if not affiliation_evidence or affiliation_evidence.upper() == "TODO":
        problems.append(
            "metadata.affiliation_evidence must record the PDF evidence or "
            "explain why AFF-UNK was necessary"
        )
    other_affiliations = metadata.get("first_author_other_affiliations")
    if not isinstance(other_affiliations, list):
        problems.append(
            "metadata.first_author_other_affiliations must be an array"
        )

    forbidden_keys = forbidden_corresponding_affiliation_keys(index, "$")
    for key_path in forbidden_keys:
        problems.append(
            "Corresponding-author affiliation must not participate in the "
            f"naming record; remove field {key_path}"
        )

    return problems, language


def heading_present(text: str, heading: str) -> bool:
    return heading in text


def text_outside_code(text: str) -> str:
    """Remove fenced and inline code before checking Markdown math delimiters."""
    without_fences = re.sub(
        r"(^|\n)[ \t]*(```|~~~).*?\n[ \t]*\2[ \t]*(?=\n|$)",
        "\n",
        text,
        flags=re.DOTALL,
    )
    return re.sub(r"`[^`\n]*`", "", without_fences)


def detect_language(text: str) -> str:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", text))
    return "zh" if chinese_chars >= latin_words else "en"


def content_validation(
    text: str,
    language: str,
    report_path: Path | None = None,
) -> list[str]:
    problems: list[str] = []
    language = language or detect_language(text)
    if language == "zh":
        required_headings = ZH_REQUIRED_HEADINGS
    elif language == "en":
        required_headings = EN_REQUIRED_HEADINGS
    else:
        required_headings = []

    for heading in required_headings:
        if not heading_present(text, heading):
            problems.append(f"Missing required heading: {heading}")

    if language == "zh":
        for heading in MIXED_LANGUAGE_HEADINGS:
            if heading in text:
                problems.append(
                    "Mixed-language structural heading found in Chinese "
                    f"report: {heading}"
                )

        if re.search(
            r"^#{1,6}\s+.*(?:图表精读|Figure And Table Deep Reading)",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        ):
            problems.append(
                "Figures/tables must be integrated into the task, motivation, "
                "method, or experiment sections, not isolated in a standalone "
                "figure-reading section"
            )

    if "TODO" in text:
        problems.append("Report still contains TODO markers")
    if re.search(
        r"^\|[^\n]*(?:报告语言|Report Language|report_language)[^\n]*\|",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    ):
        problems.append(
            "Report metadata table duplicates report_language; keep the "
            "language tag only in paper_index.json"
        )

    evidence_hits = len(
        re.findall(
            r"\bEvidence:|\bInference from|证据[:：]|推断[:：]",
            text,
            flags=re.IGNORECASE,
        )
    )
    if evidence_hits < 5:
        problems.append("Too few evidence markers; expected at least 5")

    image_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    if not image_targets:
        problems.append(
            "No Markdown images found; explain if precise figure extraction failed"
        )
    elif report_path is not None:
        package_root = report_path.parent.resolve()
        manifest_paths: set[str] = set()
        try:
            figure_manifest = load_json_object(
                package_root / "extracted" / "figure_manifest.json"
            )
        except ValueError:
            pass
        else:
            items = figure_manifest.get("items")
            if isinstance(items, list):
                manifest_paths = {
                    f"extracted/{item['path']}"
                    for item in items
                    if isinstance(item, dict)
                    and isinstance(item.get("path"), str)
                }
        for raw_target in image_targets:
            target = raw_target.strip()
            if target.startswith("<") and ">" in target:
                target = target[1 : target.index(">")]
            elif ' "' in target:
                target = target.split(' "', 1)[0]
            target = unquote(target)
            parsed = urlparse(target)
            candidate = Path(target)
            if (
                parsed.scheme
                or parsed.netloc
                or candidate.is_absolute()
                or "\\" in target
                or ".." in candidate.parts
            ):
                problems.append(
                    "Report images must use portable local relative Markdown "
                    f"paths: {raw_target}"
                )
                continue
            if candidate.parts[:2] != ("extracted", "figures"):
                problems.append(
                    "Report image path must stay under extracted/figures: "
                    f"{raw_target}"
                )
                continue
            resolved_candidate = (package_root / candidate).resolve()
            try:
                resolved_candidate.relative_to(package_root)
            except ValueError:
                problems.append(
                    f"Report image escapes the paper workspace: {raw_target}"
                )
                continue
            if not resolved_candidate.is_file():
                problems.append(
                    f"Linked report image does not exist: {raw_target}"
                )
            if candidate.as_posix() not in manifest_paths:
                problems.append(
                    "Linked report image is missing from "
                    f"figure_manifest.json: {raw_target}"
                )

    preview_hits = len(
        re.findall(
            r"page-\d{3}-preview|page preview|整页预览",
            text,
            flags=re.IGNORECASE,
        )
    )
    if preview_hits > 0:
        problems.append(
            "Report references page previews; crop precise figures/tables or "
            "mark this as an unresolved extraction limitation"
        )

    rendered_text = text_outside_code(text)
    incompatible_math = [
        delimiter
        for delimiter in (r"\(", r"\)", r"\[", r"\]")
        if delimiter in rendered_text
    ]
    if incompatible_math:
        found = ", ".join(incompatible_math)
        problems.append(
            "Obsidian-incompatible math delimiters found "
            f"({found}); use $...$ for inline math and $$...$$ for display math"
        )

    invalid_display_lines = [
        line_number
        for line_number, line in enumerate(rendered_text.splitlines(), start=1)
        if "$$" in line and line.strip() != "$$"
    ]
    if invalid_display_lines:
        shown_lines = ", ".join(
            str(line_number) for line_number in invalid_display_lines[:5]
        )
        problems.append(
            "Obsidian display-math delimiters must be on separate lines; "
            f"check line(s): {shown_lines}"
        )

    display_delimiter_lines = [
        line_number
        for line_number, line in enumerate(rendered_text.splitlines(), start=1)
        if line.strip() == "$$"
    ]
    if len(display_delimiter_lines) % 2:
        problems.append(
            "Unbalanced Obsidian display-math delimiters; "
            f"found {len(display_delimiter_lines)} standalone $$ line(s)"
        )

    inline_unbalanced_lines: list[int] = []
    inline_whitespace_lines: list[int] = []
    inside_display_math = False
    for line_number, line in enumerate(rendered_text.splitlines(), start=1):
        if line.strip() == "$$":
            inside_display_math = not inside_display_math
            continue
        if inside_display_math or "$$" in line:
            continue

        delimiters = list(re.finditer(r"(?<!\\)(?<!\$)\$(?!\$)", line))
        if len(delimiters) % 2:
            inline_unbalanced_lines.append(line_number)

        for opening, closing in zip(delimiters[::2], delimiters[1::2]):
            starts_with_space = (
                opening.end() < len(line) and line[opening.end()].isspace()
            )
            ends_with_space = (
                closing.start() > 0
                and line[closing.start() - 1].isspace()
            )
            if starts_with_space or ends_with_space:
                inline_whitespace_lines.append(line_number)
                break

    if inline_unbalanced_lines:
        shown_lines = ", ".join(
            str(line_number) for line_number in inline_unbalanced_lines[:5]
        )
        problems.append(
            "Unbalanced Obsidian inline-math $ delimiter(s); "
            f"check line(s): {shown_lines}"
        )

    if inline_whitespace_lines:
        shown_lines = ", ".join(
            str(line_number) for line_number in inline_whitespace_lines[:5]
        )
        problems.append(
            "Whitespace found immediately inside inline-math delimiters; "
            f"use $formula$ rather than $ formula $ on line(s): {shown_lines}"
        )

    for pattern in WEAK_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            problems.append(f"Weak generic wording found: {pattern}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate canonical package identity, evidence structure, images, "
            "and Obsidian-compatible math."
        )
    )
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    report_path = args.report.resolve()
    if not report_path.exists():
        raise SystemExit(f"Report not found: {report_path}")
    if not report_path.is_file():
        raise SystemExit(f"Report path is not a file: {report_path}")

    try:
        text = report_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Report is not valid UTF-8: {report_path}") from exc

    package_problems, language = package_validation(report_path)
    problems = [
        *package_problems,
        *content_validation(text, language, report_path),
    ]

    if problems:
        print("Validation failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("Validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
