---
name: evidence-grounded-paper-deep-read
description: Generate detailed, evidence-grounded Markdown deep-reading reports from research paper PDFs and organize single- or multi-paper outputs with canonical Obsidian-safe names. Use when Codex needs to analyze academic papers, extract figures/tables, explain formulas and technical terms for beginners, compare claims against paper evidence, or produce structured reading reports covering what the authors did, why they did it, how they did it, and how they validated it.
---

# Evidence-Grounded Paper Deep Read

## Purpose

Create a detailed Markdown deep-reading report from a research paper PDF. The report must be specific enough that a beginner can understand the paper's motivation, method, formulas, figures, experiments, and technical terms without reading the original paper first.

Default to the user's language for the final report. If the user does not specify a language, use the language of the request.

Maintain strict language consistency. Section titles, table headers, checklist labels, image captions, and explanatory prose must use the report language. Keep English only for paper titles, author names, dataset names, model names, abbreviations, code identifiers, equations, and technical terms that are normally written in English.

Store the language tag as `report_language` only in `paper_index.json`. Never add a language suffix to the directory, short-title slug, or report filename, and do not duplicate the language tag in the report metadata table or batch index.

## Required Workflow

Never start by writing a polished summary. Work through these phases in order:

1. Read the [output naming contract](references/output_naming.md), resolve every naming component from evidence, and record any required unknown fallback.
2. Prepare the canonically named per-paper workspace.
3. Extract text, figures, tables, captions, and formulas from the workspace's canonical `source.pdf` when possible. Prefer pdffigures2 for figure/table extraction. Use local fallback extraction and verified cropping only for visuals that pdffigures2 misses or renders incorrectly. Every extraction manifest must record `source_pdf: "source.pdf"` and the exact source SHA-256 from `paper_index.json`.
4. Build a paper index that maps identity, sections, claims, methods, formulas, figures, and experiments.
5. Create evidence cards for all important claims and method details.
6. Draft the report from the evidence cards.
7. Insert figures with local relative Markdown paths.
8. Run the quality checklist before final delivery.

Use this directory layout for each paper. The user may choose a different
output root, but retain the canonical per-paper directory and report filename:

```text
reports/
  <paper_id>/
    source.pdf
    extracted/
      full_text.md
      sections.json
      figure_manifest.json
      figures/
        figure-001.png
        figure-002.png
    paper_index.json
    evidence_cards.md
    <paper_id>-deep-read.md
```

Build `paper_id` as
`<year>-<type_code>-<venue_abbr>-<first_author_affiliation_abbr>-<short_title>`.
Use exactly the same value for the parent directory. Do not include an author
name, corresponding-author affiliation, `FA`, `CA`, or language suffix.

## Tools And Resources

- Read the [output naming contract](references/output_naming.md) before creating a workspace, paper index, or batch index.
- Use `scripts/paper_naming.py` to normalize and validate canonical paper IDs and report filenames.
- Use `scripts/extract_pdf_text.py` to extract page-level text into Markdown and JSON.
- Prefer an available pdffigures2 workflow for figure/table extraction. Use the user's configured jar or project wrapper when present; no jar is bundled with this skill. Normalize its output into `extracted/figure_manifest.json` with `source_pdf`, `source_sha256`, and an `items` array containing captions, pages, bounding boxes, safe relative asset paths, and each asset's SHA-256.
- Use `scripts/extract_pdf_figures.py` to inspect embedded image objects and render page previews only when pdffigures2 misses a visual.
- Use `scripts/crop_pdf_region_verified.py` as a fallback recovery tool for exact figure/table regions with safety margin and edge-tightness checks. Its required `--manifest extracted/figure_manifest.json` argument keeps the crop path, source identity, SHA-256, bbox, and verification result in the canonical package metadata.
- Use `scripts/build_paper_index.py` to merge extracted section and figure metadata into the existing scaffold without replacing naming identity or curated evidence.
- Use `scripts/make_report_scaffold.py` to create a canonical workspace and report from `assets/report_template.md`.
- Use `scripts/validate_report.py` to catch naming/index mismatches, missing sections, and weak report coverage.
- Read `references/reading_protocol.md` before analyzing a paper.
- Read `references/report_schema.md` before drafting the report.
- Read `references/figure_analysis_protocol.md` before explaining figures and tables.
- Read `references/terminology_explanation.md` when the paper uses specialized terms, formulas, or field-specific methods.
- Read `references/quality_checklist.md` before claiming the report is complete.

The Python extraction scripts prefer PyMuPDF and automatically fall back to `pdfplumber` when available. If both extraction backends are unavailable, continue manually, but keep the same artifacts and report structure. Full-page previews are inspection aids only and should not be used as final report figures.

## Evidence Rules

Treat the paper as the source of truth.

- Attach section names, page numbers, paragraph numbers, figure numbers, table numbers, or equation numbers to important claims whenever available.
- Do not invent motivations, baselines, datasets, metrics, ablations, or limitations.
- Mark uncertain items as `Not clearly stated in the paper` instead of guessing.
- When a claim depends on interpretation, label it as an inference and explain the evidence behind it.
- Prefer concrete details over evaluative adjectives. Replace vague phrases such as "improves performance" with the exact mechanism, metric, dataset, and result when available.

## Required Report Structure

The final `<paper_id>-deep-read.md` must use section titles in the report language. For Chinese reports, use:

```markdown
# 论文精读报告：<paper title>

## 0. 一句话总览
## 1. 论文基本信息
## 2. 作者做了什么
## 3. 作者为什么要做这件事
## 4. 作者具体怎么做
## 5. 作者如何验证
## 6. 公式与关键技术细节
## 7. 创新点逐条拆解
## 8. 局限性与开放问题
## 9. 初学者背景补充
## 10. 复现与进一步阅读建议
## 11. 完整性自检
```

For English reports, translate the same structure fully into English. Do not mix labels such as `WHAT`, `WHY`, `HOW`, or `EXPERIMENT` into a Chinese report heading.

For each innovation point, include:

- The problem it addresses.
- The author's idea.
- The exact implementation or algorithmic procedure.
- The relevant formula, figure, or module if present.
- Why the design may work.
- How it differs from prior or baseline methods.
- Evidence location in the paper.

For each experiment, include:

- Research question tested by the experiment.
- Dataset or benchmark.
- Metric.
- Compared methods or baselines.
- Setup details.
- Main result.
- What the result proves and what it does not prove.
- Evidence location in the paper.

## Figure Handling

Save cropped figures under `extracted/figures/` or `figures/` and reference them with relative paths:

```markdown
![Figure 1: Overall framework](extracted/figures/figure-001.png)
```

Use pdffigures2 output as the first-choice visual source. Inspect its extracted images and metadata before writing. If pdffigures2 misses a figure/table or produces an incomplete crop, recover that visual with fallback page preview plus verified cropping. When cropping manually, add margin, inspect edge warnings, and recrop until the image contains all panels, labels, axes, legends, and caption elements needed for understanding.

Do not create a standalone figure/table explanation section. Integrate each figure or table into the section where it is used as evidence:

- Use task/problem definition figures in `作者做了什么`.
- Use motivation or gap figures in `作者为什么要做这件事`.
- Use architecture, algorithm, and formula figures in `作者具体怎么做`.
- Use result tables, ablation tables, and qualitative examples in `作者如何验证`.

For every major figure or table, explain naturally in the surrounding prose:

- What the figure/table shows.
- How to read each region, arrow, axis, row, or column.
- Which claim or method step it supports.
- What a beginner might misunderstand.
- Whether the visual evidence is strong, incomplete, or only illustrative.

Full-page previews are inspection aids, not final report figures. If pdffigures2 and fallback cropping both fail, mark the visual as an unresolved extraction limitation and do not pretend the page preview is the figure.

## Formula Handling

For each important formula:

- Reproduce the formula if it can be extracted reliably.
- Define every symbol.
- Explain the computation in plain language.
- Explain where it appears in the method pipeline.
- Explain why the formula is needed.
- Give a toy intuitive example when useful.
- Mark any symbol that is not defined by the paper.

Write all report formulas with Obsidian-compatible MathJax delimiters:

- Use `$...$` for inline formulas, with no whitespace immediately inside the delimiters.
- Use `$$` on separate lines before and after every display formula.
- Never use `\(...\)` or `\[...\]` as math delimiters.
- Keep Markdown tables valid when they contain formulas; escape a literal table separator as `\|` when needed.
- Run `scripts/validate_report.py` before delivery and fix every incompatible math delimiter it reports.

## Batch Processing

When processing many papers, create one output folder per paper and keep a batch index:

```text
reports/
  batch_index.md
  2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation/
    2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation-deep-read.md
  2024-C-IEEE-ISPSD-AFF-UNK-Wide-Bandgap-Reliability/
    2024-C-IEEE-ISPSD-AFF-UNK-Wide-Bandgap-Reliability-deep-read.md
```

`batch_index.md` must list `paper_id`, original title, document type, venue,
first-author affiliation abbreviation, status, a relative Markdown report link,
and any extraction problems. Do not add a report-language column. Use standard
relative Markdown links rather than absolute filesystem paths or Obsidian-only
wikilinks so the same index works in Obsidian and GitHub.

## Completion Standard

A report is not complete until it passes these checks:

- The parent directory equals `paper_id`, and the report is named exactly `<paper_id>-deep-read.md`.
- Naming fields in `paper_index.json` reproduce the directory and report filename.
- `sections.json` and `figure_manifest.json` both identify the same canonical `source.pdf` SHA-256 as `paper_index.json`; missing or mismatched manifests are not merged.
- The name contains no author, corresponding-author affiliation, `FA`, `CA`, or language suffix.
- The first-author affiliation is supported by `affiliation_evidence` or uses `AFF-UNK`; unknown year and venue use `YEAR-UNK` and `VENUE-UNK`.
- `report_language` appears only in `paper_index.json`.
- Any collision suffix is the documented deterministic DOI or source-PDF SHA-256 form; a DOI discovered during explicit reuse enriches the index without changing an already allocated source-hash path.
- The same source SHA-256 is never associated with two different non-empty DOI values; stop and resolve that metadata conflict.
- Every figure-manifest item has a safe relative asset path and matching asset SHA-256, and `figures_and_tables` exactly mirrors the manifest.
- Extraction and crop publication use the shared package lock and recovery journal; do not bypass these scripts by replacing canonical assets and the manifest separately.
- Batch-index and figure links are relative Markdown links that resolve in Obsidian.
- The task, motivation, method, and experiment sections are all substantive.
- All stated contributions are decomposed into problem, idea, implementation, and evidence.
- Major figures and tables are embedded or explicitly marked as unavailable.
- Figures/tables are precise crops and are integrated into the report's argument instead of isolated in a figure-reading section.
- Key formulas and technical terms are explained for beginners.
- All formulas use Obsidian-compatible `$...$` or `$$...$$` MathJax delimiters.
- Experiments include datasets, metrics, baselines, settings, and interpretation.
- The report distinguishes paper evidence from agent inference.
- The completeness checklist is filled honestly.
