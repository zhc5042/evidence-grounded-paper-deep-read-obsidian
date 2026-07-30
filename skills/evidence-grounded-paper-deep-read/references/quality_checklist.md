# Quality Checklist

Run this checklist before final delivery.

## Output Package And Naming

- The parent directory is exactly `paper_id`.
- The report filename is exactly `<paper_id>-deep-read.md`.
- The base identifier follows
  `<year>-<type_code>-<venue_abbr>-<first_author_affiliation_abbr>-<short_title>`.
- The type code is one of `J`, `C`, `TH`, `P`, `TR`, `B`, `BC`, `STD`, or
  `UNK`.
- Unknown year, venue, and affiliation values use `YEAR-UNK`, `VENUE-UNK`, and
  `AFF-UNK`.
- The first-author affiliation follows the paper's author-affiliation markers;
  multiple affiliations use the first printed marker, or the first linked
  affiliation-list entry when the markers do not impose an order.
- `affiliation_evidence` supports the selected first-author affiliation or
  explains why `AFF-UNK` was necessary.
- No author name, corresponding-author affiliation, `FA`, `CA`, or language tag
  appears in the directory or report filename.
- The short-title slug does not end in a report-language token such as
  `zh-CN`.
- No dedicated corresponding-author affiliation field remains in the naming
  metadata.
- `report_language` exists only in `paper_index.json`, not in the report
  metadata table or batch index.
- The directory, report filename, and naming fields in `paper_index.json` agree.
- `sections.json`, `figure_manifest.json`, and `paper_index.json` record the
  same canonical `source.pdf` SHA-256; neither manifest is missing.
- Extraction paths stored in `paper_index.json` are portable relative paths,
  not machine-specific absolute paths.
- A collision suffix, when present, is `doi-` plus the first eight SHA-256
  hexadecimal digits of the normalized DOI, or `sha-` plus the first eight
  hexadecimal digits of the source PDF SHA-256.
- A DOI added during explicit reuse is stored in the index without renaming an
  already allocated source-hash workspace; its recorded collision basis
  remains auditable.
- No complete source PDF SHA-256 is associated with two different non-empty
  DOI values.
- Every figure-manifest item has a safe `figures/...` path, an existing local
  asset, and a verified asset SHA-256; the path has no Windows-invalid
  component or alternate-data-stream syntax, and the index contains the same
  item list.
- Batch-index report links and report asset links are relative Markdown links
  that resolve in both Obsidian and GitHub.

## Required Sections

- Title and metadata are filled.
- Structural language is consistent: headings, table headers, image captions, and checklist labels match the report language.
- The task section explains the exact work, not only the topic.
- The motivation section explains background, gap, and motivation.
- The method section explains pipeline, modules, formulas, and implementation.
- The experiment section explains setup, baselines, metrics, and results.
- Major visuals are precise crops, not full-page previews.
- Every fallback crop is recorded in the canonical
  `extracted/figure_manifest.json` with bbox, margin, source identity, asset
  hash, and verification status; visuals marked `needs_review` are not used
  until visually checked or recropped.
- Figure extraction and crop publication use the bundled package transaction
  rather than separate manual replacements of assets and
  `figure_manifest.json`.
- Figures and tables are integrated into the task, motivation, method, or experiment sections where they support the argument.
- Formula section explains important equations and symbols.
- Inline formulas use `$...$`, display formulas use `$$...$$`, and no `\(...\)` or `\[...\]` math delimiters remain.
- Innovation section decomposes every contribution.
- Limitations are distinguished from agent speculation.
- Beginner notes define specialized terms.
- Reproduction notes identify code/data/config requirements if available.

## Weak Writing Patterns To Remove

Replace these with concrete detail:

- "The method improves performance."
- "The authors propose a novel framework."
- "The experiment proves effectiveness."
- "This module extracts useful features."
- "The results are significant."
- "The figure shows the overall architecture."
- "图中展示了整体框架。"
- "该图说明了方法有效。"

For every such sentence, add what, how, where, compared with what, and supported by which evidence.

## Evidence Audit

For each major claim, verify:

- There is an evidence marker.
- The evidence marker points to a real paper location.
- The claim does not exceed what the evidence supports.
- Inferences are labeled as inferences.

## Completeness Table

End the report with a table like:

```markdown
| Check Item | Status | Notes |
|---|---|---|
| Task section is detailed | Complete/Partial/Missing |  |
| Motivation section is detailed | Complete/Partial/Missing |  |
| Method section is module-level | Complete/Partial/Missing |  |
| Experiments are fully analyzed | Complete/Partial/Missing |  |
| Major figures/tables are explained | Complete/Partial/Missing |  |
| Key formulas are explained | Complete/Partial/Missing |  |
| Formulas render in Obsidian without plugins | Complete/Partial/Missing |  |
| Beginner terminology is covered | Complete/Partial/Missing |  |
| Evidence markers are present | Complete/Partial/Missing |  |
| Report language is consistent | Complete/Partial/Missing |  |
| Figures are cropped and integrated into logic | Complete/Partial/Missing |  |
```

For Chinese reports, localize the completeness table:

```markdown
| 检查项 | 状态 | 说明 |
|---|---|---|
| 作者做了什么是否具体 | 完成/部分/缺失 |  |
| 为什么做是否具体 | 完成/部分/缺失 |  |
| 方法是否到模块级 | 完成/部分/缺失 |  |
| 实验是否完整分析 | 完成/部分/缺失 |  |
| 主要图表是否精确裁剪并融入正文 | 完成/部分/缺失 |  |
| 关键公式是否解释 | 完成/部分/缺失 |  |
| 公式能否在 Obsidian 中免插件渲染 | 完成/部分/缺失 |  |
| 初学者术语是否补充 | 完成/部分/缺失 |  |
| 关键结论是否有证据标记 | 完成/部分/缺失 |  |
| 结构语言是否一致 | 完成/部分/缺失 |  |
```
