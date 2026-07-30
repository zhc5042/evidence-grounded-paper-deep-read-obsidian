#!/usr/bin/env python3
"""Build and validate canonical paper workspace and report names."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPORT_SUFFIX = "-deep-read.md"
NAMING_RULE = (
    "<year>-<type_code>-<venue_abbr>-"
    "<first_author_affiliation_abbr>-<short_title>"
)
YEAR_UNKNOWN = "YEAR-UNK"
VENUE_UNKNOWN = "VENUE-UNK"
AFFILIATION_UNKNOWN = "AFF-UNK"
MAX_PAPER_ID_LENGTH = 96
MAX_COLLISION_SUFFIX_LENGTH = 12
MAX_BASE_PAPER_ID_LENGTH = (
    MAX_PAPER_ID_LENGTH - MAX_COLLISION_SUFFIX_LENGTH - 1
)
MAX_ABBREVIATION_LENGTH = 32
MAX_SHORT_TITLE_LENGTH = 72

DOCUMENT_TYPE_CODES = frozenset(
    {"J", "C", "TH", "P", "TR", "B", "BC", "STD", "UNK"}
)
DOCUMENT_TYPE_ALIASES = {
    "j": "J",
    "journal": "J",
    "journalarticle": "J",
    "article": "J",
    "c": "C",
    "conference": "C",
    "conferencepaper": "C",
    "proceedings": "C",
    "th": "TH",
    "thesis": "TH",
    "dissertation": "TH",
    "phdthesis": "TH",
    "mastersthesis": "TH",
    "p": "P",
    "preprint": "P",
    "arxiv": "P",
    "tr": "TR",
    "technicalreport": "TR",
    "report": "TR",
    "b": "B",
    "book": "B",
    "bc": "BC",
    "bookchapter": "BC",
    "chapter": "BC",
    "std": "STD",
    "standard": "STD",
    "unk": "UNK",
    "unknown": "UNK",
}
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", flags=re.IGNORECASE)
LANGUAGE_TAG_PATTERN = re.compile(
    r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"
)
SHORT_TITLE_LANGUAGE_SUFFIX_PATTERN = re.compile(
    r"(?:^|-)(?:"
    r"zh(?:-(?:CN|TW|HK|SG))?"
    r"|en(?:-(?:US|GB|AU|CA))?"
    r")$",
    flags=re.IGNORECASE,
)


class NamingError(ValueError):
    """Raised when canonical naming metadata is invalid."""


@dataclass(frozen=True)
class PaperNaming:
    publication_year: str
    document_type_code: str
    venue_abbr: str
    first_author_affiliation_abbr: str
    short_title: str
    collision_suffix: str
    base_paper_id: str
    paper_id: str
    report_filename: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_year(value: str | int | None) -> str:
    text = str(value or "").strip()
    if not text or text.upper() in {"UNK", "UNKNOWN", YEAR_UNKNOWN}:
        return YEAR_UNKNOWN
    if not re.fullmatch(r"\d{4}", text):
        raise NamingError(
            f"Publication year must be four digits or {YEAR_UNKNOWN}: {text!r}"
        )
    year = int(text)
    if year < 1000 or year > 2999:
        raise NamingError(f"Publication year is outside the supported range: {text}")
    return text


def normalize_document_type(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "UNK"
    upper = text.upper()
    if upper in DOCUMENT_TYPE_CODES:
        return upper
    alias = re.sub(r"[^a-z0-9]+", "", text.lower())
    if alias in DOCUMENT_TYPE_ALIASES:
        return DOCUMENT_TYPE_ALIASES[alias]
    allowed = ", ".join(sorted(DOCUMENT_TYPE_CODES))
    raise NamingError(f"Unsupported document type {text!r}; use one of: {allowed}")


def _truncate_slug(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    shortened = value[:max_length].rstrip("-")
    if "-" in shortened:
        word_boundary = shortened.rsplit("-", 1)[0].rstrip("-")
        if len(word_boundary) >= max(8, max_length // 2):
            shortened = word_boundary
    return shortened


def ascii_slug(
    value: str | None,
    *,
    fallback: str,
    max_length: int,
    hash_non_ascii_fallback: bool = False,
    truncate: bool = True,
) -> str:
    raw = str(value or "").strip()
    compatibility_normalized = unicodedata.normalize("NFKC", raw)
    compatibility_normalized = compatibility_normalized.replace("&", " and ")
    normalized = unicodedata.normalize("NFKD", compatibility_normalized)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")
    if not slug:
        slug = fallback
        if raw and hash_non_ascii_fallback:
            digest = hashlib.sha256(
                compatibility_normalized.encode("utf-8")
            ).hexdigest()[:8]
            slug = f"{fallback}-{digest}"
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > max_length and not truncate:
        raise NamingError(
            f"Filename component exceeds {max_length} characters: {slug}"
        )
    return _truncate_slug(slug, max_length) or fallback


def normalize_doi(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = re.sub(
        r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def doi_is_valid(value: str | None) -> bool:
    normalized = normalize_doi(value)
    return bool(normalized and DOI_PATTERN.fullmatch(normalized))


def normalize_language_tag(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not LANGUAGE_TAG_PATTERN.fullmatch(text):
        raise NamingError(
            "Report language must be a BCP-47-style tag such as zh-CN or en"
        )
    parts = text.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_collision_suffix(
    *, doi: str | None = None, source_pdf: Path | None = None
) -> str:
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        if not doi_is_valid(normalized_doi):
            raise NamingError(f"Invalid DOI: {doi!r}")
        digest = hashlib.sha256(normalized_doi.encode("utf-8")).hexdigest()[:8]
        return f"doi-{digest}"
    if source_pdf is not None:
        if not source_pdf.exists():
            raise NamingError(f"Source PDF not found for collision hash: {source_pdf}")
        return f"sha-{sha256_file(source_pdf)[:8]}"
    raise NamingError("A DOI or source PDF is required to build a collision suffix")


def collision_suffix_from_identity(
    *, doi: str | None = None, source_sha256: str = ""
) -> tuple[str, str]:
    """Return the deterministic collision suffix and its recorded basis."""
    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        if not doi_is_valid(normalized_doi):
            raise NamingError(f"Invalid DOI: {doi!r}")
        digest = hashlib.sha256(normalized_doi.encode("utf-8")).hexdigest()[:8]
        return f"doi-{digest}", "doi-sha256"
    normalized_sha = str(source_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized_sha):
        raise NamingError(
            "A normalized DOI or a 64-character source SHA-256 is required "
            "to build a collision suffix"
        )
    return f"sha-{normalized_sha[:8]}", "source-sha256"


def build_paper_naming(
    *,
    publication_year: str | int | None,
    document_type_code: str | None,
    venue_abbr: str | None,
    first_author_affiliation_abbr: str | None,
    short_title: str | None,
    collision_suffix: str | None = None,
) -> PaperNaming:
    if not str(short_title or "").strip():
        raise NamingError("Short title must not be empty")
    year = normalize_year(publication_year)
    type_code = normalize_document_type(document_type_code)
    venue = ascii_slug(
        venue_abbr,
        fallback=VENUE_UNKNOWN,
        max_length=MAX_ABBREVIATION_LENGTH,
        truncate=False,
    )
    affiliation = ascii_slug(
        first_author_affiliation_abbr,
        fallback=AFFILIATION_UNKNOWN,
        max_length=MAX_ABBREVIATION_LENGTH,
        truncate=False,
    )
    collision = str(collision_suffix or "").strip().lower()
    if collision and not re.fullmatch(r"(?:doi|sha)-[0-9a-f]{8}", collision):
        raise NamingError(
            "Collision suffix must be doi-<8 hex> or sha-<8 hex>"
        )

    fixed_parts = [year, type_code, venue, affiliation]
    fixed_length = len("-".join(fixed_parts))
    available_short_title = min(
        MAX_SHORT_TITLE_LENGTH,
        MAX_BASE_PAPER_ID_LENGTH - fixed_length - 1,
    )
    if available_short_title < 8:
        raise NamingError("Naming components leave too little room for a short title")

    short = ascii_slug(
        short_title,
        fallback="Untitled",
        max_length=available_short_title,
        hash_non_ascii_fallback=True,
    )
    if SHORT_TITLE_LANGUAGE_SUFFIX_PATTERN.search(short):
        raise NamingError(
            "Short title must not end with a report-language tag; keep the "
            "language only in paper_index.json"
        )
    base_paper_id = "-".join([*fixed_parts, short])
    paper_parts = [base_paper_id]
    if collision:
        paper_parts.append(collision)
    paper_id = "-".join(paper_parts)
    if len(paper_id) > MAX_PAPER_ID_LENGTH:
        raise NamingError(
            f"Paper ID exceeds {MAX_PAPER_ID_LENGTH} characters: {paper_id}"
        )
    if not re.fullmatch(r"[A-Za-z0-9-]+", paper_id):
        raise NamingError(f"Paper ID is not ASCII filename-safe: {paper_id}")

    return PaperNaming(
        publication_year=year,
        document_type_code=type_code,
        venue_abbr=venue,
        first_author_affiliation_abbr=affiliation,
        short_title=short,
        collision_suffix=collision,
        base_paper_id=base_paper_id,
        paper_id=paper_id,
        report_filename=f"{paper_id}{REPORT_SUFFIX}",
    )


def portable_units(value: str) -> int:
    """Return the stricter UTF-8 byte or Windows UTF-16 code-unit length."""
    return max(
        len(value.encode("utf-8")),
        len(value.encode("utf-16-le")) // 2,
    )


def identity_matches_index(
    index: dict[str, Any],
    *,
    normalized_doi: str,
    source_sha256: str,
) -> bool:
    metadata = index.get("metadata")
    if not isinstance(metadata, dict):
        return False
    indexed_doi = normalize_doi(metadata.get("doi"))
    indexed_sha = str(metadata.get("source_sha256") or "").strip().lower()
    if normalized_doi and indexed_doi:
        if not doi_is_valid(normalized_doi) or not doi_is_valid(indexed_doi):
            return False
        return normalized_doi == indexed_doi
    return bool(source_sha256 and indexed_sha == source_sha256.lower())


def naming_from_index(index: dict[str, Any]) -> PaperNaming:
    metadata = index.get("metadata")
    naming = index.get("naming")
    if not isinstance(metadata, dict):
        raise NamingError("paper_index.json is missing the metadata object")
    if not isinstance(naming, dict):
        raise NamingError("paper_index.json is missing the naming object")
    return build_paper_naming(
        publication_year=metadata.get("publication_year"),
        document_type_code=metadata.get("document_type_code"),
        venue_abbr=metadata.get("venue_abbr"),
        first_author_affiliation_abbr=metadata.get(
            "first_author_affiliation_abbr"
        ),
        short_title=naming.get("short_title"),
        collision_suffix=naming.get("collision_suffix"),
    )


def validate_index_contract(index: dict[str, Any]) -> PaperNaming:
    """Validate schema v2 without silently normalizing stored identity fields."""
    if index.get("schema_version") != 2:
        raise NamingError("paper_index.json schema_version must be the integer 2")
    if index.get("naming_algorithm") != "paper-id-v1":
        raise NamingError(
            "paper_index.json naming_algorithm must be paper-id-v1"
        )

    metadata = index.get("metadata")
    naming = index.get("naming")
    if not isinstance(metadata, dict):
        raise NamingError("paper_index.json is missing the metadata object")
    if not isinstance(naming, dict):
        raise NamingError("paper_index.json is missing the naming object")

    expected = naming_from_index(index)
    exact_fields = [
        (
            "metadata.publication_year",
            metadata.get("publication_year"),
            expected.publication_year,
        ),
        (
            "metadata.document_type_code",
            metadata.get("document_type_code"),
            expected.document_type_code,
        ),
        (
            "metadata.venue_abbr",
            metadata.get("venue_abbr"),
            expected.venue_abbr,
        ),
        (
            "metadata.first_author_affiliation_abbr",
            metadata.get("first_author_affiliation_abbr"),
            expected.first_author_affiliation_abbr,
        ),
        (
            "naming.short_title",
            naming.get("short_title"),
            expected.short_title,
        ),
        (
            "naming.collision_suffix",
            naming.get("collision_suffix"),
            expected.collision_suffix,
        ),
        ("paper_id", index.get("paper_id"), expected.paper_id),
        (
            "base_paper_id",
            index.get("base_paper_id"),
            expected.base_paper_id,
        ),
        (
            "report_filename",
            index.get("report_filename"),
            expected.report_filename,
        ),
        (
            "naming.base_paper_id",
            naming.get("base_paper_id"),
            expected.base_paper_id,
        ),
    ]
    for field, actual, expected_value in exact_fields:
        if not isinstance(actual, str) or actual != expected_value:
            raise NamingError(
                f"{field} must be the exact canonical value "
                f"{expected_value!r}; found {actual!r}"
            )

    if naming.get("algorithm") != "paper-id-v1":
        raise NamingError("naming.algorithm must be paper-id-v1")
    if naming.get("rule") != NAMING_RULE:
        raise NamingError(f"naming.rule must be {NAMING_RULE}")

    report_language = index.get("report_language")
    normalized_language = normalize_language_tag(
        report_language if isinstance(report_language, str) else None
    )
    if report_language != normalized_language:
        raise NamingError(
            "report_language must use canonical BCP-47 casing: "
            f"{normalized_language}"
        )

    source_pdf = metadata.get("source_pdf")
    if source_pdf != "source.pdf":
        raise NamingError("metadata.source_pdf must be source.pdf")
    source_sha = metadata.get("source_sha256")
    if not isinstance(source_sha, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source_sha
    ):
        raise NamingError(
            "metadata.source_sha256 must be 64 lowercase hexadecimal digits"
        )

    doi = metadata.get("doi")
    if not isinstance(doi, str):
        raise NamingError("metadata.doi must be a string")
    normalized_doi = normalize_doi(doi)
    if doi != normalized_doi:
        raise NamingError("metadata.doi must be stored in normalized form")
    if doi and not doi_is_valid(doi):
        raise NamingError(f"metadata.doi is invalid: {doi!r}")

    collision_basis = naming.get("collision_basis")
    if not isinstance(collision_basis, str):
        raise NamingError("naming.collision_basis must be a string")
    if expected.collision_suffix:
        if collision_basis == "doi-sha256":
            if not doi:
                raise NamingError(
                    "doi-sha256 collision basis requires metadata.doi"
                )
            expected_suffix, _ = collision_suffix_from_identity(doi=doi)
        elif collision_basis == "source-sha256":
            expected_suffix, _ = collision_suffix_from_identity(
                source_sha256=source_sha
            )
        else:
            raise NamingError(
                "naming.collision_basis must be doi-sha256 or source-sha256"
            )
        if expected.collision_suffix != expected_suffix:
            raise NamingError(
                "naming.collision_suffix does not match the DOI/source identity"
            )
    elif collision_basis:
        raise NamingError(
            "naming.collision_basis must be empty without a collision suffix"
        )

    return expected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a canonical paper ID and deep-reading report filename."
    )
    parser.add_argument("--year", default=YEAR_UNKNOWN)
    parser.add_argument("--document-type", default="UNK")
    parser.add_argument("--venue-abbr", default=VENUE_UNKNOWN)
    parser.add_argument("--affiliation-abbr", default=AFFILIATION_UNKNOWN)
    parser.add_argument("--short-title", required=True)
    parser.add_argument("--collision-suffix", default="")
    parser.add_argument("--auto-collision-suffix", action="store_true")
    parser.add_argument("--doi", default="")
    parser.add_argument("--source-pdf", type=Path)
    args = parser.parse_args()

    collision_suffix = args.collision_suffix
    if args.auto_collision_suffix:
        if collision_suffix:
            raise SystemExit(
                "Use either --collision-suffix or --auto-collision-suffix, not both"
            )
        collision_suffix = build_collision_suffix(
            doi=args.doi,
            source_pdf=args.source_pdf,
        )

    try:
        result = build_paper_naming(
            publication_year=args.year,
            document_type_code=args.document_type,
            venue_abbr=args.venue_abbr,
            first_author_affiliation_abbr=args.affiliation_abbr,
            short_title=args.short_title,
            collision_suffix=collision_suffix,
        )
    except NamingError as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
