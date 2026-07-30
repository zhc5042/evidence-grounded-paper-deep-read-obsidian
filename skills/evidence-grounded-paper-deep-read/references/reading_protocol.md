# Reading Protocol

Use this protocol before drafting any report.

## 1. Build The Paper Map

Identify:

- Full title and ordered author list.
- Verified publication year, or `YEAR-UNK` when it is not reliably available.
- Document type code and full venue name according to the
  [output naming contract](output_naming.md).
- Stable venue abbreviation, or `VENUE-UNK` when it is not reliably available.
- DOI when present.
- The first author's affiliation marker or other author-affiliation link.
- The first author's linked affiliations in the order shown by the paper.
- The selected first-author primary affiliation, its abbreviation, and the exact
  `affiliation_evidence` used to select it.
- The requested report language for `paper_index.json`.
- Abstract claim.
- Problem setting.
- Main contributions as stated by the authors.
- Method sections and module names.
- Algorithms, formulas, losses, objectives, or prompts.
- Figures and tables with captions.
- Datasets, metrics, baselines, ablations, and implementation details.
- Limitations, failure cases, and future work.

Resolve the first-author affiliation from the paper's ordered author list and
author-affiliation markers. If the first author has multiple linked
affiliations, select the affiliation linked by the first marker printed for
that author. If the markers do not impose an order, select the first linked
entry in the paper's printed affiliation list. Record the rest in
`first_author_other_affiliations`. If the relationship or abbreviation cannot
be established reliably, use `AFF-UNK` and explain the missing evidence. Never
substitute a corresponding-author address, and do not create
corresponding-author affiliation naming fields.

Store `report_language` only in `paper_index.json`; do not copy its language tag
into the directory, report filename, report metadata table, or batch index.

Run extraction against the workspace's copied `source.pdf`. Record that file's
SHA-256 in both `sections.json` and `figure_manifest.json`; do not merge an
extraction artifact whose hash differs from `paper_index.json`.

## 2. Create Evidence Cards

Create one evidence card for every important item. Use this format:

```markdown
### Evidence Card: <short name>

- Type: contribution | motivation | method | formula | figure | experiment | limitation
- Location: section/page/paragraph/figure/table/equation
- Paper text summary:
- Concrete details:
- Why it matters:
- Related report sections:
- Confidence: high | medium | low
```

Do not merge unrelated claims into one card.

## 3. Analyze Contributions

For each contribution, answer:

- What exact gap or problem is addressed?
- What is the author's insight?
- What existing approach is insufficient?
- What mechanism is introduced?
- What inputs and outputs does it operate on?
- What formula, module, training objective, data construction, or inference procedure implements it?
- What evidence validates it?

## 4. Analyze The Method Pipeline

Explain the method as an ordered pipeline:

1. Input and assumptions.
2. Preprocessing or representation.
3. Core modules.
4. Training objective or optimization.
5. Inference or deployment procedure.
6. Outputs.

For each step, describe what enters, what happens, what leaves, and why the step exists.

## 5. Analyze Experiments

Separate experiments by purpose:

- Main comparison: Does the proposed method beat baselines?
- Ablation: Which component matters?
- Sensitivity: How robust is the method to hyperparameters or conditions?
- Efficiency: What is the cost?
- Qualitative analysis: What examples explain behavior?
- Failure analysis: Where does it break?

If the paper omits one of these categories, say so.

## 6. Beginner Reconstruction Test

Before drafting, check whether a beginner could answer:

- What problem is being solved?
- Why previous methods are not enough?
- What each proposed module does?
- How the key formula should be read?
- What every major figure/table contributes?
- Why each experiment was included?

If not, gather more evidence before writing.
