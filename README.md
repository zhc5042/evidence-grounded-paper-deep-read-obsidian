# Evidence-Grounded Paper Deep Read — Obsidian-Compatible Edition

A Codex skill for producing detailed, evidence-grounded Markdown reports from
research-paper PDFs. This edition requires Obsidian-compatible MathJax
delimiters, integrates precise figure and table crops into the report, and
validates evidence coverage before delivery.

## What This Edition Changes

- Use `$...$` for inline formulas.
- Use `$$` on separate lines for display formulas.
- Reject `\(...\)` and `\[...\]` math delimiters during validation.
- Add Obsidian formula-rendering checks to the report schema, template, and
  completion checklist.
- Give every paper a canonical, evidence-backed directory and report filename
  that remains portable across Obsidian, GitHub, and common filesystems.

## Install In Codex

Ask Codex:

```text
Use skill-installer to install the global skill from:
https://github.com/zhc5042/evidence-grounded-paper-deep-read-obsidian/tree/main/skills/evidence-grounded-paper-deep-read
```

Or run the installer directly on Windows PowerShell:

```powershell
$codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
python "$codexRoot\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo zhc5042/evidence-grounded-paper-deep-read-obsidian `
  --path skills/evidence-grounded-paper-deep-read
```

The installer refuses to overwrite an existing skill with the same name.
Back up or remove the existing
`$CODEX_HOME/skills/evidence-grounded-paper-deep-read` directory before
installing this edition.

## Python Dependencies

Use Python 3.10 or newer.

When the repository has been cloned, install the Python extraction dependencies
from its root directory with:

```bash
python -m pip install -r requirements.txt
```

When the skill was downloaded directly with `skill-installer`, the repository
root files are not installed. Install the same dependencies explicitly:

```bash
python -m pip install "Pillow>=10" "PyMuPDF>=1.23" "pdfplumber>=0.11"
```

Java 17 and a locally built `pdffigures2.jar` are recommended for first-choice
figure and table extraction. They are not bundled in this repository. The
skill can fall back to PyMuPDF and pdfplumber when pdffigures2 is unavailable.

## Use

Attach or provide a research-paper PDF and ask:

```text
Use $evidence-grounded-paper-deep-read to create a detailed Chinese Markdown
deep-reading report. Explain the motivation, method, formulas, experiments,
innovations, evidence, limitations, and major figures. Clearly separate paper
evidence from inference.
```

The generated report keeps figures under a relative `extracted/figures/`
directory and uses MathJax syntax that Obsidian renders without community
plugins.

## Canonical Output Naming

The base paper identifier is:

```text
<year>-<type_code>-<venue_abbr>-<first_author_affiliation_abbr>-<short_title>
```

The directory is exactly `<paper_id>`, and the report is named exactly
`<paper_id>-deep-read.md`. For example:

```text
reports/
  batch_index.md
  2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation/
    source.pdf
    paper_index.json
    evidence_cards.md
    extracted/
      figures/
    2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation-deep-read.md
```

Use only these document type codes:

| Code | Document type |
|---|---|
| `J` | Journal article |
| `C` | Conference paper |
| `TH` | Thesis or dissertation |
| `P` | Preprint |
| `TR` | Technical report |
| `B` | Book |
| `BC` | Book chapter |
| `STD` | Standard |
| `UNK` | Unknown |

Use a stable venue abbreviation such as `IEEE-TED`. For a thesis or
dissertation, use a known degree code such as `PhD` or `MSc` as the venue
component; keep the institution in the first-author affiliation component.
Use `YEAR-UNK`, `VENUE-UNK`, or `AFF-UNK` when the corresponding value cannot
be established reliably.

Resolve the affiliation from the first author and the paper's
author-affiliation markers. When that author has multiple affiliations, use the
affiliation linked by the first printed marker; if the markers are unordered,
use the first linked entry in the printed affiliation list. Record the others
in `paper_index.json`. Do not put an author name,
corresponding-author affiliation, `FA`, or `CA` in the canonical name.

Store the language tag, such as `zh-CN`, only as `report_language` in
`paper_index.json`; never append it to the report filename or repeat it in the
report metadata table or batch index. The naming helper also rejects a short
title ending in a report-language token such as `zh-CN`.

If two different papers produce the same base identifier, append
`doi-<8 hex>` using SHA-256 of the normalized DOI. Without a DOI, append
`sha-<8 hex>` using the source PDF SHA-256. This makes the collision result
stable instead of dependent on processing order. If a DOI is discovered only
after a `sha-<8 hex>` workspace was created, explicit reuse enriches the index
with that DOI while retaining the existing stable path; later PDF versions
with the same DOI resolve to the same workspace. If the exact same source PDF
is later presented with a different non-empty DOI, scaffolding stops and asks
for the metadata conflict to be resolved instead of creating a duplicate.

Use ordinary relative Markdown links in `batch_index.md`, for example:

```markdown
[Deep read](2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation/2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation-deep-read.md)
```

The same link works in Obsidian and GitHub. Figure links remain relative to the
report, such as `extracted/figures/figure-001.png`, while the report H1 keeps
the human-readable paper title.

Every `sections.json` and `figure_manifest.json` records the canonical
`source.pdf` SHA-256. The index builder refuses missing manifests, mismatched
source hashes, malformed workspaces, and concurrent index changes instead of
silently clearing or mixing evidence from different papers. Figure items also
record and validate their own SHA-256 and portable `figures/...` path. The
fallback crop tools update that canonical manifest when called with
`--manifest extracted/figure_manifest.json`; paths containing Windows device
names, alternate-data-stream colons, control characters, or trailing dots and
spaces are rejected on every platform. Extraction and crop publishers share a
recoverable package lock, so concurrent runs cannot mix one image with another
run's manifest; an interrupted pre-commit transaction is rolled back when the
next publisher acquires the package.

## Repository Checks

The naming and package workflow uses only the Python standard library. Run its
unit and end-to-end tests with:

```bash
python -m unittest discover -s tests -v
```

## 中文说明

这是一个面向 Codex 的论文精读技能。它从论文 PDF 生成证据可追溯的 Markdown
报告，详细解释研究动机、方法流程、公式、实验、创新点、局限性和关键图表。

本版本增加了 Obsidian 公式兼容规则：

- 行内公式使用 `$...$`。
- 独立公式使用单独成行的 `$$...$$`。
- 验证器会拒绝 `\(...\)` 和 `\[...\]`。
- 报告模板和完整性检查表会检查 Obsidian 公式渲染兼容性。

输出统一采用：

```text
<年份>-<类型码>-<来源缩写>-<第一作者单位缩写>-<短标题>-deep-read.md
```

目录名使用同一 `paper_id`。文件名不包含作者姓名、通讯作者单位、`FA`、`CA`
或语言尾缀；`report_language` 只写入 `paper_index.json`。第一作者有多个单位时，
选取该作者首个已打印标记关联的单位；标记无顺序时，选取单位列表中首个关联
单位。无法可靠确认时使用 `AFF-UNK`。批量索引和图片均使用相对 Markdown
链接，因此可以同时在 Obsidian 和 GitHub 中打开。

## Attribution

This repository is a modified distribution of
[MoonKirito/evidence-grounded-paper-deep-read](https://github.com/MoonKirito/evidence-grounded-paper-deep-read).
The original work is Copyright (c) 2026 MoonKirito and is distributed under
the MIT License. Obsidian compatibility changes in this repository were
prepared by GitHub user `zhc5042`.

`pdffigures2` is a separate project maintained by AllenAI and licensed under
Apache License 2.0. No pdffigures2 binary or Java runtime is redistributed
here.

## License

MIT. See [LICENSE](LICENSE).
