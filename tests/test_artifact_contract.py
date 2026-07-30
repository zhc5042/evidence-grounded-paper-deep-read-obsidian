from __future__ import annotations

import json
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

from artifact_contract import (  # noqa: E402
    publish_cropped_figure_asset,
    record_figure_asset,
    validate_figure_manifest_items,
)
import figure_package  # noqa: E402
from paper_naming import NamingError, sha256_file  # noqa: E402


class ArtifactContractTests(unittest.TestCase):
    def test_windows_nonportable_figure_paths_are_rejected(self) -> None:
        unsafe_paths = [
            "figures/carrier.png:hidden.png",
            "figures/CON.png",
            "figures/trailing-dot.",
            "figures/trailing-space ",
            "figures/control-\x01.png",
        ]
        with tempfile.TemporaryDirectory() as directory:
            extracted = Path(directory)
            for unsafe_path in unsafe_paths:
                with self.subTest(path=unsafe_path):
                    with self.assertRaises(NamingError):
                        validate_figure_manifest_items(
                            [
                                {
                                    "path": unsafe_path,
                                    "sha256": "0" * 64,
                                }
                            ],
                            extracted_dir=extracted,
                        )

    def test_record_figure_asset_updates_canonical_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            source_pdf.write_bytes(b"%PDF-canonical")
            extracted = root / "extracted"
            figures = extracted / "figures"
            figures.mkdir(parents=True)
            asset = figures / "figure-002-method.png"
            asset.write_bytes(b"first-crop")
            manifest_path = extracted / "figure_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "source_pdf": "source.pdf",
                        "source_sha256": sha256_file(source_pdf),
                        "backend": "verified-crop",
                        "items": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            first = record_figure_asset(
                manifest_path,
                source_pdf=source_pdf,
                asset_path=asset,
                record={
                    "kind": "verified_crop",
                    "page": 2,
                    "verification": {"status": "verified"},
                },
            )
            self.assertEqual(
                first["path"],
                "figures/figure-002-method.png",
            )
            self.assertEqual(first["sha256"], sha256_file(asset))

            asset.write_bytes(b"replacement-crop")
            second = record_figure_asset(
                manifest_path,
                source_pdf=source_pdf,
                asset_path=asset,
                record={
                    "kind": "verified_crop",
                    "page": 2,
                    "verification": {"status": "needs_review"},
                },
            )
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["items"], [second])
            self.assertEqual(second["sha256"], sha256_file(asset))
            self.assertEqual(second["bytes"], len(b"replacement-crop"))

    def test_concurrent_crops_keep_bytes_and_metadata_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            source_pdf.write_bytes(b"%PDF-canonical")
            extracted = root / "extracted"
            figures = extracted / "figures"
            figures.mkdir(parents=True)
            manifest_path = extracted / "figure_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "source_pdf": "source.pdf",
                        "source_sha256": sha256_file(source_pdf),
                        "items": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            errors: list[BaseException] = []
            barrier = threading.Barrier(2)

            def publish(label: str, content: bytes) -> None:
                staging = Path(
                    tempfile.mkdtemp(
                        prefix=".figure-stage-",
                        dir=extracted,
                    )
                )
                staged_asset = staging / "figures" / "crop.png"
                staged_asset.parent.mkdir()
                staged_asset.write_bytes(content)
                try:
                    barrier.wait()
                    publish_cropped_figure_asset(
                        manifest_path,
                        source_pdf=source_pdf,
                        staging=staging,
                        asset_path=figures / "crop.png",
                        record={
                            "kind": "verified_crop",
                            "label": label,
                            "bbox": [label],
                        },
                    )
                except BaseException as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(
                    target=publish,
                    args=("A", b"ASSET-A"),
                ),
                threading.Thread(
                    target=publish,
                    args=("B", b"ASSET-B"),
                ),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            asset = figures / "crop.png"
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            item = manifest["items"][0]
            expected = (
                b"ASSET-A" if item["label"] == "A" else b"ASSET-B"
            )
            self.assertEqual(asset.read_bytes(), expected)
            self.assertEqual(item["bbox"], [item["label"]])
            self.assertEqual(item["sha256"], sha256_file(asset))

    def test_post_commit_cleanup_failure_keeps_new_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            source_pdf.write_bytes(b"%PDF-canonical")
            extracted = root / "extracted"
            figures = extracted / "figures"
            figures.mkdir(parents=True)
            asset = figures / "crop.png"
            asset.write_bytes(b"OLD")
            manifest_path = extracted / "figure_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "source_pdf": "source.pdf",
                        "source_sha256": sha256_file(source_pdf),
                        "items": [
                            {
                                "kind": "verified_crop",
                                "label": "old",
                                "path": "figures/crop.png",
                                "sha256": sha256_file(asset),
                                "bytes": len(b"OLD"),
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            staging = Path(
                tempfile.mkdtemp(
                    prefix=".figure-stage-",
                    dir=extracted,
                )
            )
            staged_asset = staging / "figures" / "crop.png"
            staged_asset.parent.mkdir()
            staged_asset.write_bytes(b"NEW")

            with patch.object(
                figure_package.shutil,
                "rmtree",
                side_effect=PermissionError("injected cleanup failure"),
            ):
                publish_cropped_figure_asset(
                    manifest_path,
                    source_pdf=source_pdf,
                    staging=staging,
                    asset_path=asset,
                    record={
                        "kind": "verified_crop",
                        "label": "new",
                    },
                )

            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(asset.read_bytes(), b"NEW")
            self.assertEqual(manifest["items"][0]["label"], "new")
            self.assertEqual(
                manifest["items"][0]["sha256"],
                sha256_file(asset),
            )
            self.assertTrue(
                (extracted / figure_package.JOURNAL_NAME).is_file()
            )

            with figure_package.exclusive_figure_package_lock(extracted):
                pass
            self.assertFalse(
                (extracted / figure_package.JOURNAL_NAME).exists()
            )


if __name__ == "__main__":
    unittest.main()
