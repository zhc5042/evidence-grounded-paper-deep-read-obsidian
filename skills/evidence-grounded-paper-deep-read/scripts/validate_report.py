#!/usr/bin/env python3
"""Check whether a paper deep-reading report contains required sections."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    if not args.report.exists():
        raise SystemExit(f"Report not found: {args.report}")

    text = args.report.read_text(encoding="utf-8")
    problems = []

    language = detect_language(text)
    required_headings = ZH_REQUIRED_HEADINGS if language == "zh" else EN_REQUIRED_HEADINGS

    for heading in required_headings:
        if not heading_present(text, heading):
            problems.append(f"Missing required heading: {heading}")

    if language == "zh":
        for heading in MIXED_LANGUAGE_HEADINGS:
            if heading in text:
                problems.append(f"Mixed-language structural heading found in Chinese report: {heading}")

        if "图表精读" in text or "## 6. Figure And Table Deep Reading" in text:
            problems.append("Figures/tables must be integrated into the task, motivation, method, or experiment sections, not isolated in a standalone figure-reading section")

    if "TODO" in text:
        problems.append("Report still contains TODO markers")

    evidence_hits = len(re.findall(r"\bEvidence:|\bInference from", text, flags=re.IGNORECASE))
    if evidence_hits < 5:
        problems.append("Too few evidence markers; expected at least 5")

    image_hits = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", text))
    if image_hits == 0:
        problems.append("No Markdown images found; explain if figure extraction failed")

    preview_hits = len(re.findall(r"page-\d{3}-preview|page preview|整页预览", text, flags=re.IGNORECASE))
    if preview_hits > 0:
        problems.append("Report references page previews; crop precise figures/tables or explicitly mark this as an unresolved extraction limitation")

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
        shown_lines = ", ".join(str(line_number) for line_number in invalid_display_lines[:5])
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

    inline_unbalanced_lines = []
    inline_whitespace_lines = []
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
                closing.start() > 0 and line[closing.start() - 1].isspace()
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

    if problems:
        print("Validation failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("Validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
