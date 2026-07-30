from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = (
    REPO_ROOT
    / "skills"
    / "evidence-grounded-paper-deep-read"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

import extract_pdf_figures  # noqa: E402
import figure_package  # noqa: E402
from paper_naming import sha256_file as real_sha256_file  # noqa: E402


class FakePage:
    def get_images(self, *, full: bool) -> list[tuple[int]]:
        return [(1,)]


class FakeDocument:
    def __iter__(self):
        return iter([FakePage()])

    def extract_image(self, xref: int) -> dict[str, object]:
        return {"ext": "png", "image": b"NEW-ASSET"}


class FakeBackend:
    @staticmethod
    def open(path: Path) -> FakeDocument:
        return FakeDocument()


class FigureExtractionTests(unittest.TestCase):
    def run_main(self, pdf: Path, out: Path) -> int:
        arguments = [
            "extract_pdf_figures.py",
            str(pdf),
            "--out",
            str(out),
        ]
        with patch.object(sys, "argv", arguments), patch.object(
            extract_pdf_figures,
            "load_backend",
            return_value=("fitz", FakeBackend),
        ):
            return extract_pdf_figures.main()

    def test_source_change_keeps_existing_assets_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF-old")
            out = root / "extracted"
            figures = out / "figures"
            figures.mkdir(parents=True)
            existing_asset = figures / "page-001-image-01.png"
            existing_asset.write_bytes(b"OLD-ASSET")
            manifest = out / "figure_manifest.json"
            old_manifest = '{"state":"old"}\n'
            manifest.write_text(old_manifest, encoding="utf-8")

            with patch.object(
                extract_pdf_figures,
                "sha256_file",
                side_effect=["a" * 64, "b" * 64],
            ):
                with self.assertRaises(SystemExit):
                    self.run_main(pdf, out)

            self.assertEqual(existing_asset.read_bytes(), b"OLD-ASSET")
            self.assertEqual(
                manifest.read_text(encoding="utf-8"),
                old_manifest,
            )

    def test_successful_publish_records_asset_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF-stable")
            out = root / "extracted"
            source_hash = real_sha256_file(pdf)

            def stable_hash(path: Path) -> str:
                if Path(path).resolve() == pdf.resolve():
                    return source_hash
                return real_sha256_file(Path(path))

            with patch.object(
                extract_pdf_figures,
                "sha256_file",
                side_effect=stable_hash,
            ):
                self.assertEqual(self.run_main(pdf, out), 0)

            asset = out / "figures" / "page-001-image-01.png"
            manifest = json.loads(
                (out / "figure_manifest.json").read_text(encoding="utf-8")
            )
            item = manifest["items"][0]
            self.assertEqual(asset.read_bytes(), b"NEW-ASSET")
            self.assertEqual(item["path"], "figures/page-001-image-01.png")
            self.assertEqual(item["sha256"], real_sha256_file(asset))
            self.assertEqual(item["bytes"], len(b"NEW-ASSET"))

    def test_manifest_publish_failure_restores_previous_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF-stable")
            out = root / "extracted"
            figures = out / "figures"
            figures.mkdir(parents=True)
            existing_asset = figures / "page-001-image-01.png"
            existing_asset.write_bytes(b"OLD-ASSET")
            manifest_path = out / "figure_manifest.json"
            old_manifest = '{"state":"old"}\n'
            manifest_path.write_text(old_manifest, encoding="utf-8")
            real_replace = os.replace
            failure_injected = False

            def fail_after_manifest_replace(
                source: object,
                destination: object,
            ) -> None:
                nonlocal failure_injected
                real_replace(source, destination)
                source_path = Path(source)
                if (
                    not failure_injected
                    and Path(destination) == manifest_path
                    and source_path.name == "figure_manifest.json"
                    and source_path.parent.name.startswith(
                        ".figure-stage-"
                    )
                ):
                    failure_injected = True
                    raise OSError("injected manifest publish failure")

            with patch.object(
                figure_package.os,
                "replace",
                side_effect=fail_after_manifest_replace,
            ):
                with self.assertRaises(SystemExit):
                    self.run_main(pdf, out)

            self.assertTrue(failure_injected)
            self.assertEqual(existing_asset.read_bytes(), b"OLD-ASSET")
            self.assertEqual(
                manifest_path.read_text(encoding="utf-8"),
                old_manifest,
            )
            self.assertFalse(
                list(out.glob(".figure-stage-*")),
                "staging should be removed after a complete rollback",
            )

    def test_concurrent_publishers_leave_a_matching_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "extracted"
            out.mkdir()
            errors: list[BaseException] = []
            barrier = threading.Barrier(2)

            def publish(writer: str, content: bytes) -> None:
                staging = Path(
                    tempfile.mkdtemp(
                        prefix=".figure-stage-",
                        dir=out,
                    )
                )
                asset = staging / "figures" / "shared.png"
                asset.parent.mkdir()
                asset.write_bytes(content)
                (staging / "figure_manifest.json").write_text(
                    json.dumps(
                        {
                            "writer": writer,
                            "items": [
                                {
                                    "path": "figures/shared.png",
                                    "sha256": real_sha256_file(asset),
                                }
                            ],
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                try:
                    barrier.wait()
                    extract_pdf_figures.publish_staged_extraction(
                        staging=staging,
                        out_dir=out,
                        manifest=[
                            {"path": "figures/shared.png"}
                        ],
                    )
                except BaseException as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=publish, args=("A", b"ASSET-A")),
                threading.Thread(target=publish, args=("B", b"ASSET-B")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            final_asset = out / "figures" / "shared.png"
            final_manifest = json.loads(
                (out / "figure_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            expected_content = (
                b"ASSET-A"
                if final_manifest["writer"] == "A"
                else b"ASSET-B"
            )
            self.assertEqual(final_asset.read_bytes(), expected_content)
            self.assertEqual(
                final_manifest["items"][0]["sha256"],
                real_sha256_file(final_asset),
            )

    def test_crashed_publish_is_recovered_on_next_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "extracted"
            figures = out / "figures"
            figures.mkdir(parents=True)
            final_asset = figures / "shared.png"
            final_asset.write_bytes(b"OLD-ASSET")
            final_manifest = out / "figure_manifest.json"
            old_manifest = '{"writer":"old"}\n'
            final_manifest.write_text(old_manifest, encoding="utf-8")
            staging = Path(
                tempfile.mkdtemp(prefix=".figure-stage-", dir=out)
            )
            staged_asset = staging / "figures" / "shared.png"
            staged_asset.parent.mkdir()
            staged_asset.write_bytes(b"NEW-ASSET")
            (staging / "figure_manifest.json").write_text(
                '{"writer":"new"}\n',
                encoding="utf-8",
            )
            child_code = f"""
import os
import sys
from pathlib import Path
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import figure_package
out = Path({str(out)!r})
stage = Path({str(staging)!r})
source_asset = stage / "figures" / "shared.png"
destination_asset = out / "figures" / "shared.png"
real_replace = figure_package.os.replace
def crash_after_asset(source, destination):
    real_replace(source, destination)
    if Path(source) == source_asset and Path(destination) == destination_asset:
        os._exit(74)
figure_package.os.replace = crash_after_asset
figure_package.publish_staged_figure_package(
    staging=stage,
    extracted_dir=out,
    asset_paths=["figures/shared.png"],
)
"""
            result = subprocess.run(
                [sys.executable, "-c", child_code],
                check=False,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUTF8": "1",
                },
            )
            self.assertEqual(result.returncode, 74)
            self.assertTrue(
                (out / figure_package.JOURNAL_NAME).is_file()
            )

            with figure_package.exclusive_figure_package_lock(out):
                pass

            self.assertEqual(final_asset.read_bytes(), b"OLD-ASSET")
            self.assertEqual(
                final_manifest.read_text(encoding="utf-8"),
                old_manifest,
            )
            self.assertFalse(
                (out / figure_package.JOURNAL_NAME).exists()
            )
            self.assertFalse(
                (out / figure_package.LOCK_NAME).exists()
            )

    def test_publish_crash_matrix_recovers_a_consistent_pair(self) -> None:
        for crash_call in range(1, 7):
            with self.subTest(crash_call=crash_call):
                with tempfile.TemporaryDirectory() as directory:
                    out = Path(directory) / "extracted"
                    figures = out / "figures"
                    figures.mkdir(parents=True)
                    final_asset = figures / "shared.png"
                    final_asset.write_bytes(b"OLD-ASSET")
                    old_item = {
                        "path": "figures/shared.png",
                        "sha256": real_sha256_file(final_asset),
                    }
                    final_manifest = out / "figure_manifest.json"
                    final_manifest.write_text(
                        json.dumps(
                            {"writer": "old", "items": [old_item]}
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    staging = Path(
                        tempfile.mkdtemp(
                            prefix=".figure-stage-",
                            dir=out,
                        )
                    )
                    staged_asset = (
                        staging / "figures" / "shared.png"
                    )
                    staged_asset.parent.mkdir()
                    staged_asset.write_bytes(b"NEW-ASSET")
                    new_item = {
                        "path": "figures/shared.png",
                        "sha256": real_sha256_file(staged_asset),
                    }
                    (staging / "figure_manifest.json").write_text(
                        json.dumps(
                            {"writer": "new", "items": [new_item]}
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    child_code = f"""
import os
import sys
from pathlib import Path
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import figure_package
out = Path({str(out)!r})
stage = Path({str(staging)!r})
real_replace = figure_package.os.replace
count = 0
def crash_at_selected_replace(source, destination):
    global count
    real_replace(source, destination)
    count += 1
    if count == {crash_call}:
        os._exit(80 + count)
figure_package.os.replace = crash_at_selected_replace
figure_package.publish_staged_figure_package(
    staging=stage,
    extracted_dir=out,
    asset_paths=["figures/shared.png"],
)
"""
                    result = subprocess.run(
                        [sys.executable, "-c", child_code],
                        check=False,
                        env={
                            **os.environ,
                            "PYTHONDONTWRITEBYTECODE": "1",
                            "PYTHONUTF8": "1",
                        },
                    )
                    self.assertEqual(
                        result.returncode,
                        80 + crash_call,
                    )

                    with figure_package.exclusive_figure_package_lock(
                        out
                    ):
                        pass

                    manifest = json.loads(
                        final_manifest.read_text(encoding="utf-8")
                    )
                    expected = (
                        b"OLD-ASSET"
                        if manifest["writer"] == "old"
                        else b"NEW-ASSET"
                    )
                    self.assertEqual(final_asset.read_bytes(), expected)
                    self.assertEqual(
                        manifest["items"][0]["sha256"],
                        real_sha256_file(final_asset),
                    )
                    self.assertFalse(
                        (out / figure_package.JOURNAL_NAME).exists()
                    )
                    self.assertFalse(
                        (out / figure_package.LOCK_NAME).exists()
                    )


if __name__ == "__main__":
    unittest.main()
