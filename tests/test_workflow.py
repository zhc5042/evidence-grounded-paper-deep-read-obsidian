from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = (
    REPO_ROOT / "skills" / "evidence-grounded-paper-deep-read"
)
SCRIPTS_DIR = SKILL_DIR / "scripts"
SCAFFOLD = SCRIPTS_DIR / "make_report_scaffold.py"
BUILD_INDEX = SCRIPTS_DIR / "build_paper_index.py"
VALIDATE = SCRIPTS_DIR / "validate_report.py"
BASE_ID = (
    "2018-J-IEEE-TED-SJTU-"
    "SiC-MOSFET-Repetitive-UIS-Degradation"
)
FIGURE_BYTES = b"not-a-real-image-but-a-valid-linked-asset"


def run_script(
    script: Path,
    *arguments: object,
    expected_returncode: int | None = 0,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(script), *(str(value) for value in arguments)],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if (
        expected_returncode is not None
        and result.returncode != expected_returncode
    ):
        raise AssertionError(
            f"{script.name} returned {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def scaffold_arguments(pdf: Path, out_root: Path) -> list[object]:
    return [
        pdf,
        "--title",
        "A Test Paper",
        "--short-title",
        "SiC MOSFET Repetitive UIS Degradation",
        "--year",
        "2018",
        "--document-type",
        "J",
        "--venue-abbr",
        "IEEE-TED",
        "--venue-full",
        "IEEE Transactions on Electron Devices",
        "--first-author-affiliation-abbr",
        "SJTU",
        "--first-author-affiliation-full",
        "Shanghai Jiao Tong University",
        "--affiliation-evidence",
        "PDF p. 1: first author marker 1 maps to affiliation 1.",
        "--language",
        "zh-CN",
        "--out-root",
        out_root,
    ]


def complete_chinese_report() -> str:
    headings = [
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
    blocks = ["# 论文精读报告：测试论文"]
    for number, heading in enumerate(headings):
        blocks.extend(
            [
                heading,
                f"本节给出具体说明 {number}。（证据：PDF 第 {number + 1} 页）",
            ]
        )
        if number == 4:
            blocks.extend(
                [
                    "![器件结构](extracted/figures/figure-001.png)",
                    "$$",
                    "x = 1",
                    "$$",
                ]
            )
    return "\n\n".join(blocks) + "\n"


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.pdf = self.root / "paper.pdf"
        self.pdf.write_bytes(b"%PDF-1.7\npaper one\n")
        self.reports = self.root / "reports"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def scaffold(self, pdf: Path | None = None) -> Path:
        source = pdf or self.pdf
        run_script(
            SCAFFOLD,
            *scaffold_arguments(source, self.reports),
        )
        return self.reports / BASE_ID

    def write_extraction_manifests(self, workspace: Path) -> None:
        index = json.loads(
            (workspace / "paper_index.json").read_text(encoding="utf-8")
        )
        source_sha256 = index["metadata"]["source_sha256"]
        extracted = workspace / "extracted"
        figure_path = extracted / "figures" / "figure-001.png"
        figure_path.write_bytes(FIGURE_BYTES)
        (extracted / "sections.json").write_text(
            json.dumps(
                {
                    "source_pdf": "source.pdf",
                    "source_sha256": source_sha256,
                    "pages": [],
                }
            ),
            encoding="utf-8",
        )
        (extracted / "figure_manifest.json").write_text(
            json.dumps(
                {
                    "source_pdf": "source.pdf",
                    "source_sha256": source_sha256,
                    "items": [
                        {
                            "id": "figure-001",
                            "path": "figures/figure-001.png",
                            "sha256": hashlib.sha256(
                                FIGURE_BYTES
                            ).hexdigest(),
                            "bytes": len(FIGURE_BYTES),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def make_valid_package(self) -> tuple[Path, Path]:
        workspace = self.scaffold()
        self.write_extraction_manifests(workspace)
        index_path = workspace / "paper_index.json"
        run_script(
            BUILD_INDEX,
            "--extracted",
            workspace / "extracted",
            "--out",
            index_path,
        )
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["metadata"]["authors"] = ["A. Author", "B. Author"]
        index["audit"] = {
            "corresponding_affiliation_excluded": True,
        }
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        figure = workspace / "extracted" / "figures" / "figure-001.png"
        figure.write_bytes(FIGURE_BYTES)
        report = workspace / f"{BASE_ID}-deep-read.md"
        report.write_text(
            complete_chinese_report(),
            encoding="utf-8",
            newline="\n",
        )
        return workspace, report

    def test_scaffold_creates_canonical_package(self) -> None:
        workspace = self.scaffold()
        report = workspace / f"{BASE_ID}-deep-read.md"
        index_path = workspace / "paper_index.json"

        self.assertTrue(report.is_file())
        self.assertEqual(
            (workspace / "source.pdf").read_bytes(),
            self.pdf.read_bytes(),
        )
        self.assertTrue(
            (workspace / "extracted" / "figures").is_dir()
        )

        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(index["paper_id"], BASE_ID)
        self.assertEqual(index["base_paper_id"], BASE_ID)
        self.assertEqual(
            index["report_filename"], f"{BASE_ID}-deep-read.md"
        )
        self.assertEqual(index["report_language"], "zh-CN")
        self.assertNotIn("zh-CN", report.name)
        self.assertEqual(
            index["metadata"]["source_sha256"],
            hashlib.sha256(self.pdf.read_bytes()).hexdigest(),
        )
        self.assertNotIn(
            "{{LANGUAGE}}", report.read_text(encoding="utf-8")
        )

    def test_reuse_is_explicit_and_collision_is_deterministic(self) -> None:
        workspace = self.scaffold()
        report = workspace / f"{BASE_ID}-deep-read.md"
        original = report.read_bytes()

        duplicate = run_script(
            SCAFFOLD,
            *scaffold_arguments(self.pdf, self.reports),
            expected_returncode=None,
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("Use --reuse-existing", duplicate.stderr)

        run_script(
            SCAFFOLD,
            *scaffold_arguments(self.pdf, self.reports),
            "--reuse-existing",
        )
        self.assertEqual(report.read_bytes(), original)

        second_pdf = self.root / "paper-two.pdf"
        second_pdf.write_bytes(b"%PDF-1.7\npaper two\n")
        second_hash = hashlib.sha256(second_pdf.read_bytes()).hexdigest()
        run_script(
            SCAFFOLD,
            *scaffold_arguments(second_pdf, self.reports),
        )
        collision_id = f"{BASE_ID}-sha-{second_hash[:8]}"
        collision_workspace = self.reports / collision_id
        self.assertTrue(collision_workspace.is_dir())
        collision_index = json.loads(
            (collision_workspace / "paper_index.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(collision_index["paper_id"], collision_id)
        self.assertEqual(
            collision_index["naming"]["collision_basis"],
            "source-sha256",
        )

    def test_same_source_with_conflicting_dois_fails_closed(self) -> None:
        first_arguments = [
            *scaffold_arguments(self.pdf, self.reports),
            "--doi",
            "10.1000/identity-a",
        ]
        run_script(SCAFFOLD, *first_arguments)

        conflicting = run_script(
            SCAFFOLD,
            *scaffold_arguments(self.pdf, self.reports),
            "--doi",
            "10.1000/identity-b",
            expected_returncode=None,
        )
        self.assertNotEqual(conflicting.returncode, 0)
        self.assertIn("conflicting DOI", conflicting.stderr)
        self.assertEqual(
            [path.name for path in self.reports.iterdir()],
            [BASE_ID],
        )

    def test_index_builder_preserves_identity_and_manual_fields(self) -> None:
        workspace = self.scaffold()
        index_path = workspace / "paper_index.json"
        before = json.loads(index_path.read_text(encoding="utf-8"))
        before["metadata"]["authors"] = ["A. Author"]
        before["claims_to_verify"] = [{"claim": "manual evidence"}]
        before["manual_extension"] = {"keep": True}
        index_path.write_text(
            json.dumps(before, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        extracted = workspace / "extracted"
        (extracted / "sections.json").write_text(
            json.dumps(
                {
                    "source_pdf": "source.pdf",
                    "source_sha256": before["metadata"]["source_sha256"],
                    "pages": [
                        {
                            "page": 2,
                            "paragraphs": [
                                {
                                    "id": "p-2-1",
                                    "text": "2. Method\nDetails",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (extracted / "figures" / "figure-001.png").write_bytes(
            FIGURE_BYTES
        )
        (extracted / "figure_manifest.json").write_text(
            json.dumps(
                {
                    "source_pdf": "source.pdf",
                    "source_sha256": before["metadata"]["source_sha256"],
                    "items": [
                        {
                            "id": "figure-001",
                            "path": "figures/figure-001.png",
                            "sha256": hashlib.sha256(
                                FIGURE_BYTES
                            ).hexdigest(),
                            "bytes": len(FIGURE_BYTES),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        run_script(
            BUILD_INDEX,
            "--extracted",
            extracted,
            "--out",
            index_path,
        )
        after = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(after["paper_id"], before["paper_id"])
        self.assertEqual(after["naming"], before["naming"])
        self.assertEqual(
            after["claims_to_verify"], before["claims_to_verify"]
        )
        self.assertEqual(
            after["manual_extension"], before["manual_extension"]
        )
        self.assertEqual(
            after["section_candidates"][0]["heading"],
            "2. Method",
        )
        self.assertEqual(
            after["figures_and_tables"][0]["id"], "figure-001"
        )
        self.assertEqual(
            after["extraction"]["sections_json"],
            "extracted/sections.json",
        )

        before_missing_manifest = index_path.read_text(encoding="utf-8")
        (extracted / "figure_manifest.json").unlink()
        missing = run_script(
            BUILD_INDEX,
            "--extracted",
            extracted,
            "--out",
            index_path,
            expected_returncode=None,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(
            index_path.read_text(encoding="utf-8"),
            before_missing_manifest,
        )
        (extracted / "figure_manifest.json").write_text(
            json.dumps(
                {
                    "source_pdf": "source.pdf",
                    "source_sha256": before["metadata"]["source_sha256"],
                    "items": [
                        {
                            "path": "figures/missing.png",
                            "sha256": "0" * 64,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        missing_asset = run_script(
            BUILD_INDEX,
            "--extracted",
            extracted,
            "--out",
            index_path,
            expected_returncode=None,
        )
        self.assertNotEqual(missing_asset.returncode, 0)
        self.assertIn("Figure asset not found", missing_asset.stderr)
        self.assertEqual(
            index_path.read_text(encoding="utf-8"),
            before_missing_manifest,
        )

        (extracted / "figure_manifest.json").write_text(
            json.dumps(
                {
                    "source_pdf": "source.pdf",
                    "source_sha256": "0" * 64,
                    "items": [],
                }
            ),
            encoding="utf-8",
        )
        contaminated = run_script(
            BUILD_INDEX,
            "--extracted",
            extracted,
            "--out",
            index_path,
            expected_returncode=None,
        )
        self.assertNotEqual(contaminated.returncode, 0)
        self.assertIn("does not match", contaminated.stderr)
        self.assertEqual(
            index_path.read_text(encoding="utf-8"),
            before_missing_manifest,
        )

    def test_validator_accepts_good_package(self) -> None:
        _, report = self.make_valid_package()
        result = run_script(VALIDATE, report)
        self.assertIn("Validation passed", result.stdout)

    def test_validator_rejects_naming_and_hash_mismatches(self) -> None:
        workspace, report = self.make_valid_package()

        legacy_report = workspace / "report.md"
        legacy_report.write_text(
            report.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        legacy = run_script(
            VALIDATE, legacy_report, expected_returncode=None
        )
        self.assertNotEqual(legacy.returncode, 0)
        self.assertIn("Report filename must equal", legacy.stdout)

        language_report = workspace / f"{BASE_ID}.zh-CN.md"
        language_report.write_text(
            report.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        language = run_script(
            VALIDATE, language_report, expected_returncode=None
        )
        self.assertNotEqual(language.returncode, 0)
        self.assertIn("language suffix", language.stdout)

        wrong_parent = self.root / "wrong-parent"
        shutil.copytree(workspace, wrong_parent)
        wrong_parent_report = wrong_parent / report.name
        parent_result = run_script(
            VALIDATE, wrong_parent_report, expected_returncode=None
        )
        self.assertNotEqual(parent_result.returncode, 0)
        self.assertIn("Parent directory must equal", parent_result.stdout)

        index_path = workspace / "paper_index.json"
        original_index_text = index_path.read_text(encoding="utf-8")
        index = json.loads(original_index_text)
        index["paper_id"] = "wrong-id"
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
        index_result = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(index_result.returncode, 0)
        self.assertIn("paper_id must be", index_result.stdout)
        index_path.write_text(original_index_text, encoding="utf-8")

        index = json.loads(original_index_text)
        index["metadata"]["publication_year"] = " 2018 "
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
        noncanonical = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(noncanonical.returncode, 0)
        self.assertIn(
            "metadata.publication_year must be the exact canonical value",
            noncanonical.stdout,
        )
        index_path.write_text(original_index_text, encoding="utf-8")

        index = json.loads(original_index_text)
        index["metadata"]["corresponding_author"] = {
            "affiliation": "Example University"
        }
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
        corresponding = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(corresponding.returncode, 0)
        self.assertIn(
            "Corresponding-author affiliation", corresponding.stdout
        )
        index_path.write_text(original_index_text, encoding="utf-8")

        index = json.loads(original_index_text)
        index["external_metadata"] = {
            "corresponding_author": {
                "affiliation": "Example University"
            }
        }
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
        external_corresponding = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(external_corresponding.returncode, 0)
        self.assertIn(
            "Corresponding-author affiliation",
            external_corresponding.stdout,
        )
        index_path.write_text(original_index_text, encoding="utf-8")

        index = json.loads(original_index_text)
        index["external_metadata"] = {
            "corresponding_author": {
                "organization": "Example University"
            }
        }
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
        organization_alias = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(organization_alias.returncode, 0)
        self.assertIn(
            "Corresponding-author affiliation",
            organization_alias.stdout,
        )
        index_path.write_text(original_index_text, encoding="utf-8")

        index = json.loads(original_index_text)
        index["figures_and_tables"] = []
        index_path.write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )
        figure_index = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(figure_index.returncode, 0)
        self.assertIn(
            "figures_and_tables must exactly match",
            figure_index.stdout,
        )
        index_path.write_text(original_index_text, encoding="utf-8")

        figure_manifest_path = (
            workspace / "extracted" / "figure_manifest.json"
        )
        original_manifest_text = figure_manifest_path.read_text(
            encoding="utf-8"
        )
        figure_manifest = json.loads(original_manifest_text)
        figure_manifest["items"][0]["sha256"] = "0" * 64
        figure_manifest_path.write_text(
            json.dumps(figure_manifest),
            encoding="utf-8",
        )
        figure_hash = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(figure_hash.returncode, 0)
        self.assertIn("Figure asset SHA-256 mismatch", figure_hash.stdout)
        figure_manifest_path.write_text(
            original_manifest_text,
            encoding="utf-8",
        )

        (workspace / "source.pdf").write_bytes(b"changed")
        hash_result = run_script(
            VALIDATE, report, expected_returncode=None
        )
        self.assertNotEqual(hash_result.returncode, 0)
        self.assertIn("does not match", hash_result.stdout)

    def test_corrupt_workspace_fails_closed(self) -> None:
        corrupt = self.reports / BASE_ID
        corrupt.mkdir(parents=True)
        result = run_script(
            SCAFFOLD,
            *scaffold_arguments(self.pdf, self.reports),
            expected_returncode=None,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no paper_index.json", result.stderr)
        self.assertEqual(
            [path.name for path in self.reports.iterdir()],
            [BASE_ID],
        )

    def test_deleted_base_does_not_duplicate_collision_workspace(self) -> None:
        base_workspace = self.scaffold()
        second_pdf = self.root / "paper-two.pdf"
        second_pdf.write_bytes(b"%PDF-1.7\npaper two\n")
        second_sha = hashlib.sha256(second_pdf.read_bytes()).hexdigest()
        run_script(
            SCAFFOLD,
            *scaffold_arguments(second_pdf, self.reports),
        )
        collision_id = f"{BASE_ID}-sha-{second_sha[:8]}"
        collision_workspace = self.reports / collision_id
        self.assertTrue(collision_workspace.is_dir())

        enriched_arguments = [
            *scaffold_arguments(second_pdf, self.reports),
            "--doi",
            "10.1000/example-paper-two",
        ]
        enriched = run_script(
            SCAFFOLD,
            *enriched_arguments,
            expected_returncode=None,
        )
        self.assertNotEqual(enriched.returncode, 0)
        self.assertIn("Use --reuse-existing", enriched.stderr)
        run_script(SCAFFOLD, *enriched_arguments, "--reuse-existing")
        enriched_index = json.loads(
            (collision_workspace / "paper_index.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            enriched_index["metadata"]["doi"],
            "10.1000/example-paper-two",
        )
        self.assertEqual(
            enriched_index["naming"]["collision_basis"],
            "source-sha256",
        )
        self.assertEqual(
            sorted(path.name for path in self.reports.iterdir()),
            sorted([BASE_ID, collision_id]),
        )

        revised_pdf = self.root / "paper-two-revised.pdf"
        revised_pdf.write_bytes(b"%PDF-1.7\npaper two revised\n")
        revised_arguments = [
            *scaffold_arguments(revised_pdf, self.reports),
            "--doi",
            "10.1000/example-paper-two",
            "--reuse-existing",
        ]
        run_script(SCAFFOLD, *revised_arguments)
        self.assertEqual(
            sorted(path.name for path in self.reports.iterdir()),
            sorted([BASE_ID, collision_id]),
        )

        shutil.rmtree(base_workspace)
        duplicate = run_script(
            SCAFFOLD,
            *scaffold_arguments(second_pdf, self.reports),
            expected_returncode=None,
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("Use --reuse-existing", duplicate.stderr)
        self.assertFalse((self.reports / BASE_ID).exists())

        run_script(
            SCAFFOLD,
            *scaffold_arguments(second_pdf, self.reports),
            "--reuse-existing",
        )
        self.assertFalse((self.reports / BASE_ID).exists())
        self.assertTrue(collision_workspace.is_dir())

    def test_reuse_requires_complete_source_and_valid_language(self) -> None:
        workspace = self.scaffold()
        (workspace / "source.pdf").unlink()
        incomplete = run_script(
            SCAFFOLD,
            *scaffold_arguments(self.pdf, self.reports),
            "--reuse-existing",
            expected_returncode=None,
        )
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn("incomplete", incomplete.stderr)

        other_root = self.root / "other-reports"
        invalid_language_arguments = scaffold_arguments(
            self.pdf, other_root
        )
        language_position = invalid_language_arguments.index("--language") + 1
        invalid_language_arguments[language_position] = "engineering"
        invalid_language = run_script(
            SCAFFOLD,
            *invalid_language_arguments,
            expected_returncode=None,
        )
        self.assertNotEqual(invalid_language.returncode, 0)
        self.assertIn("BCP-47", invalid_language.stderr)


if __name__ == "__main__":
    unittest.main()
