from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
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

from safe_json import (  # noqa: E402
    ConcurrentUpdateError,
    atomic_write_json_if_unchanged,
    exclusive_update_lock,
)


class SafeJsonTests(unittest.TestCase):
    def test_atomic_update_succeeds_when_original_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)
            atomic_write_json_if_unchanged(
                path,
                {"value": 2},
                expected_sha256=hashlib.sha256(original).hexdigest(),
            )
            self.assertIn('"value": 2', path.read_text(encoding="utf-8"))

    def test_race_before_capture_preserves_concurrent_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            concurrent = '{"value": "concurrent"}\n'
            path.write_bytes(original)
            real_rename = os.rename

            def racing_rename(source: object, destination: object) -> None:
                if Path(source) == path:
                    path.write_text(concurrent, encoding="utf-8")
                real_rename(source, destination)

            with patch("safe_json.os.rename", side_effect=racing_rename):
                with self.assertRaises(ConcurrentUpdateError):
                    atomic_write_json_if_unchanged(
                        path,
                        {"value": 2},
                        expected_sha256=hashlib.sha256(original).hexdigest(),
                    )
            self.assertEqual(path.read_text(encoding="utf-8"), concurrent)

    def test_sidecar_lock_rejects_second_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            path.write_text("{}\n", encoding="utf-8")
            with exclusive_update_lock(path):
                with self.assertRaises(ConcurrentUpdateError):
                    with exclusive_update_lock(path):
                        self.fail("second writer acquired the same lock")

    def test_dead_writer_is_recovered_after_capture_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)
            child_code = f"""
import hashlib
import os
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import safe_json
target = safe_json.Path({str(path)!r})
real_rename = safe_json.os.rename
def crash_after_capture(source, destination):
    real_rename(source, destination)
    if safe_json.Path(source) == target:
        os._exit(73)
safe_json.os.rename = crash_after_capture
with safe_json.exclusive_update_lock(target):
    safe_json.atomic_write_json_if_unchanged(
        target,
        {{"value": 2}},
        expected_sha256=hashlib.sha256({original!r}).hexdigest(),
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
            self.assertEqual(result.returncode, 73)
            self.assertFalse(path.exists())

            with exclusive_update_lock(path):
                self.assertEqual(path.read_bytes(), original)

            self.assertTrue(path.is_file())
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.previous"))
            )
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.prepared"))
            )
            self.assertFalse(
                path.with_name(f".{path.name}.lock").exists()
            )

    def test_hardlink_failure_restores_canonical_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)
            with patch(
                "safe_json.os.link",
                side_effect=OSError("hard links unsupported"),
            ):
                with self.assertRaises(ConcurrentUpdateError):
                    atomic_write_json_if_unchanged(
                        path,
                        {"value": 2},
                        expected_sha256=hashlib.sha256(
                            original
                        ).hexdigest(),
                    )
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), original)

    def test_capture_hash_failure_restores_canonical_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)
            real_sha256_file = sys.modules["safe_json"].sha256_file
            failed_once = False

            def fail_first_backup_hash(target: Path) -> str:
                nonlocal failed_once
                if target.name.endswith(".previous") and not failed_once:
                    failed_once = True
                    raise PermissionError("injected backup read failure")
                return real_sha256_file(target)

            with exclusive_update_lock(path), patch(
                "safe_json.sha256_file",
                side_effect=fail_first_backup_hash,
            ):
                with self.assertRaises(ConcurrentUpdateError):
                    atomic_write_json_if_unchanged(
                        path,
                        {"value": 2},
                        expected_sha256=hashlib.sha256(
                            original
                        ).hexdigest(),
                    )

            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.previous"))
            )
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.prepared"))
            )

            with exclusive_update_lock(path):
                self.assertEqual(path.read_bytes(), original)

    def test_capture_interrupt_restores_then_propagates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)

            with patch(
                "safe_json.sha256_file",
                side_effect=KeyboardInterrupt,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    atomic_write_json_if_unchanged(
                        path,
                        {"value": 2},
                        expected_sha256=hashlib.sha256(
                            original
                        ).hexdigest(),
                    )

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.previous"))
            )
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.prepared"))
            )

    def test_error_after_hardlink_commit_keeps_new_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)
            real_link = os.link

            def link_then_fail(source: object, destination: object) -> None:
                real_link(source, destination)
                raise PermissionError("injected post-link failure")

            with patch("safe_json.os.link", side_effect=link_then_fail):
                atomic_write_json_if_unchanged(
                    path,
                    {"value": 2},
                    expected_sha256=hashlib.sha256(original).hexdigest(),
                )

            self.assertIn('"value": 2', path.read_text(encoding="utf-8"))
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.previous"))
            )
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.prepared"))
            )

    def test_orphaned_capture_recovers_without_a_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            previous = (
                path.parent
                / f".{path.name}.{'a' * 32}.previous"
            )
            previous.write_bytes(original)

            with exclusive_update_lock(path):
                self.assertEqual(path.read_bytes(), original)

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(previous.exists())

    def test_post_commit_cleanup_error_does_not_report_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)
            real_unlink = Path.unlink

            def fail_previous_cleanup(
                target: Path,
                *args: object,
                **kwargs: object,
            ) -> None:
                if target.name.endswith(".previous"):
                    raise PermissionError("injected cleanup failure")
                real_unlink(target, *args, **kwargs)

            with patch.object(
                Path,
                "unlink",
                new=fail_previous_cleanup,
            ):
                atomic_write_json_if_unchanged(
                    path,
                    {"value": 2},
                    expected_sha256=hashlib.sha256(original).hexdigest(),
                )
            self.assertIn('"value": 2', path.read_text(encoding="utf-8"))

    def test_stale_partial_restore_copy_recovers_previous_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(b'{"value":')
            previous = root / ".paper_index.json.dead.previous"
            previous.write_bytes(original)
            prepared = root / ".paper_index.json.dead.prepared"
            prepared.write_bytes(b'{"value": 2}\n')
            lock = root / ".paper_index.json.lock"
            lock.write_text(
                f"2147483647-{'a' * 32}\n",
                encoding="utf-8",
            )

            with exclusive_update_lock(path):
                self.assertEqual(path.read_bytes(), original)

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(previous.exists())
            self.assertFalse(prepared.exists())

    def test_cleanup_leftover_cannot_poison_later_crash_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_index.json"
            original = b'{"value": 1}\n'
            path.write_bytes(original)
            real_unlink = Path.unlink

            def fail_previous_cleanup(
                target: Path,
                *args: object,
                **kwargs: object,
            ) -> None:
                if target.name.endswith(".previous"):
                    raise PermissionError("injected cleanup failure")
                real_unlink(target, *args, **kwargs)

            with exclusive_update_lock(path), patch.object(
                Path,
                "unlink",
                new=fail_previous_cleanup,
            ):
                atomic_write_json_if_unchanged(
                    path,
                    {"value": 2},
                    expected_sha256=hashlib.sha256(original).hexdigest(),
                )
            committed = path.read_bytes()
            self.assertFalse(
                list(path.parent.glob(f".{path.name}.*.previous"))
            )
            self.assertTrue(
                list(
                    path.parent.glob(
                        f".{path.name}.*.recovered-backup"
                    )
                )
            )

            child_code = f"""
import hashlib
import os
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import safe_json
target = safe_json.Path({str(path)!r})
real_rename = safe_json.os.rename
def crash_after_capture(source, destination):
    real_rename(source, destination)
    if safe_json.Path(source) == target:
        os._exit(75)
safe_json.os.rename = crash_after_capture
with safe_json.exclusive_update_lock(target):
    current = target.read_bytes()
    safe_json.atomic_write_json_if_unchanged(
        target,
        {{"value": 3}},
        expected_sha256=hashlib.sha256(current).hexdigest(),
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
            self.assertEqual(result.returncode, 75)
            self.assertFalse(path.exists())

            with exclusive_update_lock(path):
                self.assertEqual(path.read_bytes(), committed)
            self.assertEqual(path.read_bytes(), committed)


if __name__ == "__main__":
    unittest.main()
