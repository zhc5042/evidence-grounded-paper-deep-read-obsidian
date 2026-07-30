# Output Naming Contract

Read this contract before creating a paper workspace, writing
`paper_index.json`, or adding a row to `batch_index.md`.

## Contents

- [Canonical Identity](#canonical-identity)
- [Document Type Codes](#document-type-codes)
- [Component Rules](#component-rules)
- [Evidence Record](#evidence-record)
- [Deterministic Collision Rule](#deterministic-collision-rule)
- [`paper_index.json` Naming Fields](#paper_indexjson-naming-fields)
- [Batch Index And Obsidian Links](#batch-index-and-obsidian-links)

## Canonical Identity

Build the base paper identifier as:

```text
<year>-<type_code>-<venue_abbr>-<first_author_affiliation_abbr>-<short_title>
```

Use that exact identifier for both the directory and report filename:

```text
reports/<paper_id>/
reports/<paper_id>/<paper_id>-deep-read.md
```

Example:

```text
2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation/
  2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation-deep-read.md
```

Do not put an author name, corresponding-author affiliation, `FA`, `CA`, or a
language tag in the directory or filename. Store `report_language` only in
`paper_index.json`.

## Document Type Codes

Use only these codes:

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
| `UNK` | Unknown document type |

`P` always means preprint, not patent.

## Component Rules

- **Year:** Use a verified four-digit publication year. Use `YEAR-UNK` when it
  cannot be established reliably.
- **Venue abbreviation:** Use a stable ASCII abbreviation. Use a journal
  abbreviation for `J`, conference acronym for `C`, preprint platform for `P`,
  report series or issuing body for `TR`, publisher or stable book abbreviation
  for `B`, parent book or series abbreviation for `BC`, and standards body or
  series for `STD`. For `TH`, use the degree code when known, such as `PhD` or
  `MSc`; the institution belongs in the affiliation component. Use
  `VENUE-UNK` when the venue value cannot be established reliably.
- **First-author affiliation:** Resolve the first author from the paper's author
  order. Follow that author's superscript, symbol, or other affiliation marker.
  If the first author has multiple affiliations, choose the affiliation linked
  by the first marker printed for that author. If the markers do not impose an
  order, choose the first linked entry in the paper's printed affiliation list.
  Record all remaining linked affiliations in
  `first_author_other_affiliations`.
- **Affiliation abbreviation:** Prefer an abbreviation printed by the paper or
  otherwise supported by reliable evidence. Use `AFF-UNK` when either the
  author-affiliation relationship or abbreviation cannot be established
  reliably. Never substitute the corresponding author's affiliation.
- **Short title:** Use a concise, descriptive, ASCII-safe title slug. Preserve
  established capitalization such as `SiC`, `MOSFET`, and `UIS`; replace
  separators and punctuation with single hyphens. Do not add author or language
  tokens; the helper rejects a short title ending in a report-language token
  such as `zh-CN`. Prefer three to eight distinctive keywords from the paper's
  English title when available. If no usable Latin title text exists, use the
  stable `Untitled-<8 hex>` fallback produced from SHA-256 of the supplied
  short title.

Keep all filename components ASCII and use only letters, digits, and hyphens.
Record the unshortened title, full venue, and full affiliation in
`paper_index.json`. Venue and affiliation components are limited to 32
characters. The naming helper reserves room for a collision suffix, limits the
base identifier to 83 characters and the final identifier to 96 characters,
and truncates only the short-title component at a word boundary.

## Evidence Record

Record enough evidence to audit the chosen affiliation. Prefer a precise entry
such as:

```text
PDF p. 1: first author marker 1 maps to affiliation 1.
```

If `AFF-UNK` is used, state whether the missing element is the author-affiliation
link, the institution name, or a reliable abbreviation. Do not create dedicated
corresponding-author affiliation fields.

## Deterministic Collision Rule

Treat an existing base `paper_id` with the same normalized DOI, or with the same
source PDF SHA-256 when DOI evidence is unavailable, as the same paper. Do not
overwrite it unless reuse was explicitly requested.

When the base identifier belongs to a different paper, append one deterministic
collision suffix:

```text
<base_paper_id>-doi-<8 lowercase hex digits>
<base_paper_id>-sha-<8 lowercase hex digits>
```

Use the first eight hexadecimal digits of SHA-256 over the normalized DOI. If
there is no DOI, use the first eight hexadecimal digits of the source PDF's
SHA-256. If that collision identifier is also occupied by a different paper,
stop instead of adding an order-dependent counter. Normalize a DOI with Unicode
NFKC, remove a leading `doi:` or DOI resolver URL, trim whitespace, and
case-fold before hashing.

The collision basis is fixed when the workspace is first allocated so links do
not change after metadata enrichment. If a DOI is discovered later,
`--reuse-existing` records the normalized DOI in `paper_index.json` but retains
an already allocated `sha-<8 hex>` name and `source-sha256` basis. Future
versions of the same DOI then resolve to that existing workspace even when the
PDF bytes differ.

If the same complete source PDF SHA-256 is presented with two different
non-empty normalized DOI values, stop and require the metadata conflict to be
resolved. Do not allocate a second directory for contradictory identities.

## `paper_index.json` Naming Fields

Keep the final identity and its source fields explicit. At minimum, retain:

```json
{
  "schema_version": 2,
  "naming_algorithm": "paper-id-v1",
  "paper_id": "2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation",
  "base_paper_id": "2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation",
  "report_filename": "2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation-deep-read.md",
  "report_language": "zh-CN",
  "metadata": {
    "title": "A Deep Insight Into the Degradation of 1.2-kV 4H-SiC MOSFETs Under Repetitive Unclamped Inductive Switching",
    "authors": ["Zhou et al."],
    "publication_year": "2018",
    "document_type_code": "J",
    "venue_full": "IEEE Transactions on Electron Devices",
    "venue_abbr": "IEEE-TED",
    "doi": "",
    "source_pdf": "source.pdf",
    "source_sha256": "<64 lowercase hex digits>",
    "first_author_affiliation_full": "Shanghai Jiao Tong University",
    "first_author_affiliation_abbr": "SJTU",
    "first_author_other_affiliations": [],
    "affiliation_evidence": "PDF p. 1: first author marker 1 maps to affiliation 1."
  },
  "naming": {
    "algorithm": "paper-id-v1",
    "rule": "<year>-<type_code>-<venue_abbr>-<first_author_affiliation_abbr>-<short_title>",
    "base_paper_id": "2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation",
    "short_title": "SiC-MOSFET-Repetitive-UIS-Degradation",
    "collision_suffix": "",
    "collision_basis": ""
  },
  "extraction": {
    "sections_json": "extracted/sections.json",
    "figure_manifest_json": "extracted/figure_manifest.json",
    "source_pdf": "source.pdf",
    "source_sha256": "<same 64 lowercase hex digits>"
  }
}
```

Do not duplicate `report_language` in the report metadata table, filename, or
`batch_index.md`.

Both extraction manifests must repeat `source_pdf: "source.pdf"` and the same
source SHA-256. `build_paper_index.py` fails closed when a manifest is missing
or belongs to a different PDF; it never replaces existing evidence with empty
data from a missing input. Every `figure_manifest.json` item must use a safe
relative path under `figures/` and record the asset's lowercase SHA-256 (and,
when present, its byte count); the builder and final validator verify the
referenced file. Paths must also be portable to Windows: reject control
characters, `< > : " \ | ? *`, trailing dots or spaces, and reserved device
names such as `CON`, `NUL`, `COM1`, and `LPT1`. This also prevents NTFS
alternate data streams from disappearing when the package is published.
The bundled extraction and crop publishers serialize changes with one
package-level lock and persist a recovery journal before replacing any
canonical asset. A pre-commit crash is rolled back on the next publisher run;
after the durable commit marker, cleanup failures do not revert a matching
asset/manifest pair.

Treat `paper_id` as an opaque identifier. Do not recover its fields by splitting
on hyphens because values such as `IEEE-TED`, `YEAR-UNK`, and `AFF-UNK` already
contain hyphens; rebuild and compare the complete value from explicit index
fields.

## Batch Index And Obsidian Links

Use standard relative Markdown links so both Obsidian and GitHub resolve them:

```markdown
[Deep read](2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation/2018-J-IEEE-TED-SJTU-SiC-MOSFET-Repetitive-UIS-Degradation-deep-read.md)
```

Keep figure links relative to the report, such as
`extracted/figures/figure-001.png`. The report's H1 remains the human-readable
paper title; the canonical filename is the stable note identity.
