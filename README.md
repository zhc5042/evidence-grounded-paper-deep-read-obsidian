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

## 中文说明

这是一个面向 Codex 的论文精读技能。它从论文 PDF 生成证据可追溯的 Markdown
报告，详细解释研究动机、方法流程、公式、实验、创新点、局限性和关键图表。

本版本增加了 Obsidian 公式兼容规则：

- 行内公式使用 `$...$`。
- 独立公式使用单独成行的 `$$...$$`。
- 验证器会拒绝 `\(...\)` 和 `\[...\]`。
- 报告模板和完整性检查表会检查 Obsidian 公式渲染兼容性。

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
