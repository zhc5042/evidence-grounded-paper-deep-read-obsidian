from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = (
    REPO_ROOT
    / "skills"
    / "evidence-grounded-paper-deep-read"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

from paper_naming import (  # noqa: E402
    AFFILIATION_UNKNOWN,
    MAX_BASE_PAPER_ID_LENGTH,
    MAX_PAPER_ID_LENGTH,
    NamingError,
    build_paper_naming,
    collision_suffix_from_identity,
    normalize_doi,
)


class PaperNamingTests(unittest.TestCase):
    def test_standard_example_is_exact(self) -> None:
        naming = build_paper_naming(
            publication_year="2018",
            document_type_code="J",
            venue_abbr="IEEE-TED",
            first_author_affiliation_abbr="SJTU",
            short_title="SiC MOSFET Repetitive UIS Degradation",
        )

        expected = (
            "2018-J-IEEE-TED-SJTU-"
            "SiC-MOSFET-Repetitive-UIS-Degradation"
        )
        self.assertEqual(naming.base_paper_id, expected)
        self.assertEqual(naming.paper_id, expected)
        self.assertEqual(naming.report_filename, f"{expected}-deep-read.md")

    def test_unknown_fullwidth_and_unsafe_components(self) -> None:
        naming = build_paper_naming(
            publication_year="YEAR-UNK",
            document_type_code="thesis",
            venue_abbr="PhD",
            first_author_affiliation_abbr="ＳＪＴＵ",
            short_title='A: B/C\\D? E* <F> | "G"',
        )
        self.assertEqual(naming.publication_year, "YEAR-UNK")
        self.assertEqual(naming.document_type_code, "TH")
        self.assertEqual(naming.venue_abbr, "PhD")
        self.assertEqual(naming.first_author_affiliation_abbr, "SJTU")
        self.assertEqual(naming.short_title, "A-B-C-D-E-F-G")

        unknown = build_paper_naming(
            publication_year=None,
            document_type_code=None,
            venue_abbr=None,
            first_author_affiliation_abbr="",
            short_title="Known Short Title",
        )
        self.assertEqual(unknown.publication_year, "YEAR-UNK")
        self.assertEqual(unknown.document_type_code, "UNK")
        self.assertEqual(unknown.venue_abbr, "VENUE-UNK")
        self.assertEqual(
            unknown.first_author_affiliation_abbr,
            AFFILIATION_UNKNOWN,
        )

    def test_non_latin_title_fallback_is_stable(self) -> None:
        first = build_paper_naming(
            publication_year="2024",
            document_type_code="J",
            venue_abbr="VENUE-UNK",
            first_author_affiliation_abbr="AFF-UNK",
            short_title="宽禁带半导体可靠性",
        )
        second = build_paper_naming(
            publication_year="2024",
            document_type_code="J",
            venue_abbr="VENUE-UNK",
            first_author_affiliation_abbr="AFF-UNK",
            short_title="宽禁带半导体可靠性",
        )
        digest = hashlib.sha256(
            "宽禁带半导体可靠性".encode("utf-8")
        ).hexdigest()[:8]
        self.assertEqual(first.short_title, f"Untitled-{digest}")
        self.assertEqual(first, second)

    def test_doi_normalization_and_collision_suffix(self) -> None:
        bare = "10.1109/TED.2018.1234567"
        expected = normalize_doi(bare)
        self.assertEqual(
            normalize_doi(f"https://doi.org/{bare}"),
            expected,
        )
        self.assertEqual(normalize_doi(f"doi: {bare}"), expected)

        one = collision_suffix_from_identity(doi=bare)
        two = collision_suffix_from_identity(
            doi=f"https://doi.org/{bare}"
        )
        self.assertEqual(one, two)
        self.assertRegex(one[0], r"^doi-[0-9a-f]{8}$")
        self.assertEqual(one[1], "doi-sha256")

        source_hash = hashlib.sha256(b"paper two").hexdigest()
        self.assertEqual(
            collision_suffix_from_identity(source_sha256=source_hash),
            (f"sha-{source_hash[:8]}", "source-sha256"),
        )
        with self.assertRaises(NamingError):
            collision_suffix_from_identity(doi="not-a-doi")

    def test_length_limits_reserve_collision_space(self) -> None:
        base = build_paper_naming(
            publication_year="2024",
            document_type_code="J",
            venue_abbr="IEEE-TED",
            first_author_affiliation_abbr="SJTU",
            short_title="word-" * 100,
        )
        self.assertLessEqual(
            len(base.base_paper_id), MAX_BASE_PAPER_ID_LENGTH
        )

        collided = build_paper_naming(
            publication_year="2024",
            document_type_code="J",
            venue_abbr="IEEE-TED",
            first_author_affiliation_abbr="SJTU",
            short_title="word-" * 100,
            collision_suffix="doi-12345678",
        )
        self.assertEqual(collided.base_paper_id, base.base_paper_id)
        self.assertLessEqual(len(collided.paper_id), MAX_PAPER_ID_LENGTH)
        self.assertTrue(collided.paper_id.endswith("-doi-12345678"))

        with self.assertRaises(NamingError):
            build_paper_naming(
                publication_year="2024",
                document_type_code="J",
                venue_abbr="V" * 33,
                first_author_affiliation_abbr="SJTU",
                short_title="Short Title",
            )

    def test_short_title_rejects_report_language_suffix(self) -> None:
        with self.assertRaisesRegex(
            NamingError,
            "report-language tag",
        ):
            build_paper_naming(
                publication_year="2024",
                document_type_code="J",
                venue_abbr="IEEE-TED",
                first_author_affiliation_abbr="SJTU",
                short_title="Reliability Study zh-CN",
            )


if __name__ == "__main__":
    unittest.main()
