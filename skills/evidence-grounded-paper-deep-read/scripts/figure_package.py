#!/usr/bin/env python3
"""Serialize and recover figure-asset plus manifest package updates."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import unicodedata
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path, PurePosixPath
from typing import Iterator

from paper_naming import sha256_file
from safe_json import process_is_alive


LOCK_NAME = ".figure-package.lock"
RECOVERY_LOCK_NAME = ".figure-package.recovery.lock"
JOURNAL_NAME = ".figure-package-transaction.json"
LOCK_PATTERN = re.compile(r"^(?P<pid>[1-9][0-9]*)-[0-9a-f]{32}$")
WINDOWS_INVALID_CHARACTERS = frozenset('<>:"\\|?*')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}


class FigurePackageError(RuntimeError):
    """Raised when a figure package cannot be updated consistently."""

    def __init__(self, message: str, *, preserve_staging: bool = False):
        super().__init__(message)
        self.preserve_staging = preserve_staging


def _thread_lock_for(extracted_dir: Path) -> threading.RLock:
    key = os.path.normcase(str(extracted_dir.resolve()))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


def _read_lock(lock_path: Path) -> tuple[str, int]:
    try:
        token = lock_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise FigurePackageError(
            f"Cannot inspect figure-package lock safely: {lock_path}"
        ) from exc
    match = LOCK_PATTERN.fullmatch(token)
    if match is None:
        raise FigurePackageError(
            f"Unrecognized figure-package lock owner: {lock_path}"
        )
    return token, int(match.group("pid"))


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_journal(extracted_dir: Path) -> dict:
    journal_path = extracted_dir / JOURNAL_NAME
    try:
        value = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FigurePackageError(
            f"Cannot read figure-package recovery journal: {journal_path}"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise FigurePackageError(
            f"Unsupported figure-package recovery journal: {journal_path}"
        )
    if value.get("phase") not in {"prepared", "committed"}:
        raise FigurePackageError(
            f"Invalid figure-package transaction phase: {journal_path}"
        )
    transaction_id = value.get("transaction_id")
    if not isinstance(transaction_id, str) or not re.fullmatch(
        r"[0-9a-f]{32}",
        transaction_id,
    ):
        raise FigurePackageError(
            f"Invalid figure-package transaction identity: {journal_path}"
        )
    staging_name = value.get("staging_dir")
    if (
        not isinstance(staging_name, str)
        or not staging_name.startswith(".figure-stage-")
        or Path(staging_name).name != staging_name
    ):
        raise FigurePackageError(
            f"Unsafe staging directory in recovery journal: {journal_path}"
        )
    manifest = value.get("manifest")
    assets = value.get("assets")
    if not isinstance(manifest, dict) or not isinstance(assets, list):
        raise FigurePackageError(
            f"Incomplete figure-package recovery journal: {journal_path}"
        )
    return value


def _assert_journal_identity(extracted_dir: Path, journal: dict) -> None:
    current = _load_journal(extracted_dir)
    if current.get("transaction_id") != journal.get("transaction_id"):
        raise FigurePackageError(
            "Figure-package transaction identity changed during recovery"
        )


def _safe_asset_relative(value: object) -> str:
    if not isinstance(value, str) or "\\" in value:
        raise FigurePackageError("Figure transaction has an unsafe asset path")
    portable = PurePosixPath(value)
    if (
        portable.as_posix() != value
        or unicodedata.normalize("NFKC", value) != value
        or portable.is_absolute()
        or ".." in portable.parts
        or len(portable.parts) < 2
        or portable.parts[0] != "figures"
    ):
        raise FigurePackageError(
            f"Figure transaction path must stay below figures/: {value!r}"
        )
    for component in portable.parts:
        if (
            any(
                character in WINDOWS_INVALID_CHARACTERS
                or ord(character) < 32
                for character in component
            )
            or component.endswith((" ", "."))
            or component.split(".", 1)[0].upper()
            in WINDOWS_RESERVED_NAMES
        ):
            raise FigurePackageError(
                f"Figure transaction path is not portable: {value!r}"
            )
    return value


def _path_hash(path: Path) -> str:
    return sha256_file(path) if path.is_file() else ""


def _restore_entry(
    *,
    destination: Path,
    backup: Path,
    had_old: bool,
    old_sha256: str,
    new_sha256: str,
) -> None:
    if had_old:
        if backup.is_file():
            if _path_hash(backup) != old_sha256:
                raise FigurePackageError(
                    f"Recovery backup hash mismatch: {backup}"
                )
            destination_sha256 = _path_hash(destination)
            if destination_sha256 == old_sha256:
                try:
                    backup.unlink()
                except OSError:
                    pass
                return
            if destination_sha256 and destination_sha256 != new_sha256:
                raise FigurePackageError(
                    "Unexpected file blocks figure-package recovery: "
                    f"{destination}"
                )
            destination.unlink(missing_ok=True)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, destination)
        elif _path_hash(destination) != old_sha256:
            raise FigurePackageError(
                f"Previous figure-package file cannot be restored: {destination}"
            )
        if _path_hash(destination) != old_sha256:
            raise FigurePackageError(
                f"Restored figure-package file failed verification: {destination}"
            )
    elif destination.exists():
        if _path_hash(destination) != new_sha256:
            raise FigurePackageError(
                f"Unexpected file blocks figure-package rollback: {destination}"
            )
        destination.unlink()


def _rollback_prepared(extracted_dir: Path, journal: dict) -> None:
    _assert_journal_identity(extracted_dir, journal)
    staging = extracted_dir / str(journal["staging_dir"])
    backup_root = staging / ".publish-backup"
    errors: list[str] = []
    assets = journal["assets"]
    assert isinstance(assets, list)
    for entry in reversed(assets):
        try:
            if not isinstance(entry, dict):
                raise FigurePackageError("Malformed asset recovery entry")
            relative = _safe_asset_relative(entry.get("path"))
            _restore_entry(
                destination=extracted_dir / Path(*PurePosixPath(relative).parts),
                backup=(
                    backup_root
                    / "assets"
                    / Path(*PurePosixPath(relative).parts)
                ),
                had_old=entry.get("had_old") is True,
                old_sha256=str(entry.get("old_sha256") or ""),
                new_sha256=str(entry.get("new_sha256") or ""),
            )
        except (OSError, FigurePackageError) as exc:
            errors.append(str(exc))

    manifest_entry = journal["manifest"]
    assert isinstance(manifest_entry, dict)
    try:
        _restore_entry(
            destination=extracted_dir / "figure_manifest.json",
            backup=backup_root / "figure_manifest.json",
            had_old=manifest_entry.get("had_old") is True,
            old_sha256=str(manifest_entry.get("old_sha256") or ""),
            new_sha256=str(manifest_entry.get("new_sha256") or ""),
        )
    except (OSError, FigurePackageError) as exc:
        errors.append(str(exc))

    if errors:
        raise FigurePackageError(
            "Figure-package rollback is incomplete; keep the journal and "
            f"staging directory for recovery. Details: {'; '.join(errors)}",
            preserve_staging=True,
        )
    _assert_journal_identity(extracted_dir, journal)
    try:
        shutil.rmtree(staging)
    except FileNotFoundError:
        pass
    (extracted_dir / JOURNAL_NAME).unlink(missing_ok=True)


def _finish_committed(extracted_dir: Path, journal: dict) -> None:
    _assert_journal_identity(extracted_dir, journal)
    manifest_entry = journal["manifest"]
    assert isinstance(manifest_entry, dict)
    final_manifest = extracted_dir / "figure_manifest.json"
    if _path_hash(final_manifest) != str(
        manifest_entry.get("new_sha256") or ""
    ):
        raise FigurePackageError(
            "Committed figure manifest failed recovery verification"
        )
    assets = journal["assets"]
    assert isinstance(assets, list)
    for entry in assets:
        if not isinstance(entry, dict):
            raise FigurePackageError("Malformed committed asset entry")
        relative = _safe_asset_relative(entry.get("path"))
        destination = extracted_dir / Path(*PurePosixPath(relative).parts)
        if _path_hash(destination) != str(entry.get("new_sha256") or ""):
            raise FigurePackageError(
                f"Committed figure asset failed verification: {destination}"
            )

    staging = extracted_dir / str(journal["staging_dir"])
    cleanup_complete = True
    try:
        shutil.rmtree(staging)
    except FileNotFoundError:
        pass
    except OSError:
        cleanup_complete = False
    if cleanup_complete:
        try:
            _assert_journal_identity(extracted_dir, journal)
            (extracted_dir / JOURNAL_NAME).unlink(missing_ok=True)
        except OSError:
            pass


def recover_figure_package(extracted_dir: Path) -> None:
    """Recover or finish the sole journaled transaction, if present."""
    journal_path = extracted_dir / JOURNAL_NAME
    if not journal_path.exists():
        return
    journal = _load_journal(extracted_dir)
    if journal["phase"] == "prepared":
        _rollback_prepared(extracted_dir, journal)
    else:
        _finish_committed(extracted_dir, journal)


@contextmanager
def _exclusive_recovery_guard(extracted_dir: Path) -> Iterator[None]:
    """Allow only one process to inspect and recover a stale transaction."""
    guard_path = extracted_dir / RECOVERY_LOCK_NAME
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    for _ in range(2):
        try:
            descriptor = os.open(
                guard_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            break
        except FileExistsError as exc:
            existing_token, owner_pid = _read_lock(guard_path)
            if process_is_alive(owner_pid):
                raise FigurePackageError(
                    f"Another process is recovering figures: {guard_path}"
                ) from exc
            try:
                if (
                    guard_path.read_text(encoding="utf-8").strip()
                    == existing_token
                ):
                    guard_path.unlink()
            except FileNotFoundError:
                pass
    else:
        raise FigurePackageError(
            f"Could not acquire figure recovery guard: {guard_path}"
        )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as guard:
            guard.write(token + "\n")
            guard.flush()
            os.fsync(guard.fileno())
        yield
    finally:
        try:
            if guard_path.read_text(encoding="utf-8").strip() == token:
                guard_path.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def exclusive_figure_package_lock(extracted_dir: Path) -> Iterator[None]:
    """Serialize extract and crop publishers across threads and processes."""
    extracted_dir = extracted_dir.resolve()
    extracted_dir.mkdir(parents=True, exist_ok=True)
    thread_lock = _thread_lock_for(extracted_dir)
    with thread_lock:
        lock_path = extracted_dir / LOCK_NAME
        token = f"{os.getpid()}-{uuid.uuid4().hex}"
        for _ in range(2):
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                break
            except FileExistsError as exc:
                with _exclusive_recovery_guard(extracted_dir):
                    if not lock_path.exists():
                        continue
                    stale_token, owner_pid = _read_lock(lock_path)
                    if process_is_alive(owner_pid):
                        raise FigurePackageError(
                            "Another extraction or crop is publishing this "
                            f"figure package: {lock_path}"
                        ) from exc
                    recover_figure_package(extracted_dir)
                    try:
                        if (
                            lock_path.read_text(encoding="utf-8").strip()
                            != stale_token
                        ):
                            raise FigurePackageError(
                                "Figure-package lock identity changed during "
                                "recovery"
                            )
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
        else:
            raise FigurePackageError(
                f"Could not acquire figure-package lock: {lock_path}"
            )

        try:
            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as lock:
                lock.write(token + "\n")
                lock.flush()
                os.fsync(lock.fileno())
            recover_figure_package(extracted_dir)
            yield
        finally:
            try:
                if lock_path.read_text(encoding="utf-8").strip() == token:
                    lock_path.unlink()
            except FileNotFoundError:
                pass


def _assert_lock_owned(extracted_dir: Path) -> None:
    lock_path = extracted_dir / LOCK_NAME
    _, owner_pid = _read_lock(lock_path)
    if owner_pid != os.getpid():
        raise FigurePackageError(
            "Current process does not own the figure-package lock"
        )


def _publish_locked(
    *,
    staging: Path,
    extracted_dir: Path,
    asset_paths: list[str],
    expected_manifest_sha256: str | None,
) -> None:
    staging = staging.resolve()
    extracted_dir = extracted_dir.resolve()
    if (
        staging.parent != extracted_dir
        or not staging.name.startswith(".figure-stage-")
    ):
        raise FigurePackageError(
            "Figure staging directory must be a .figure-stage-* child of "
            "the canonical extracted directory"
        )
    if (extracted_dir / JOURNAL_NAME).exists():
        raise FigurePackageError(
            "A figure-package recovery journal is still active"
        )

    final_manifest = extracted_dir / "figure_manifest.json"
    staged_manifest = staging / "figure_manifest.json"
    if not staged_manifest.is_file():
        raise FigurePackageError(
            f"Staged figure manifest not found: {staged_manifest}"
        )
    if final_manifest.exists() and not final_manifest.is_file():
        raise FigurePackageError(
            f"Canonical figure manifest is not a file: {final_manifest}"
        )
    actual_manifest_sha256 = _path_hash(final_manifest)
    if (
        expected_manifest_sha256 is not None
        and actual_manifest_sha256 != expected_manifest_sha256
    ):
        raise FigurePackageError(
            "figure_manifest.json changed before package publication"
        )

    entries: list[dict] = []
    seen: set[str] = set()
    for raw_relative in asset_paths:
        relative = _safe_asset_relative(raw_relative)
        key = unicodedata.normalize("NFKC", relative).casefold()
        if key in seen:
            raise FigurePackageError(
                f"Duplicate figure transaction path: {relative}"
            )
        seen.add(key)
        portable = PurePosixPath(relative)
        staged_asset = staging / Path(*portable.parts)
        final_asset = extracted_dir / Path(*portable.parts)
        if not staged_asset.is_file():
            raise FigurePackageError(
                f"Staged figure asset not found: {staged_asset}"
            )
        if final_asset.exists() and not final_asset.is_file():
            raise FigurePackageError(
                f"Figure destination is not a file: {final_asset}"
            )
        entries.append(
            {
                "path": relative,
                "had_old": final_asset.is_file(),
                "old_sha256": _path_hash(final_asset),
                "new_sha256": sha256_file(staged_asset),
            }
        )

    journal = {
        "schema_version": 1,
        "transaction_id": uuid.uuid4().hex,
        "phase": "prepared",
        "staging_dir": staging.name,
        "manifest": {
            "had_old": final_manifest.is_file(),
            "old_sha256": actual_manifest_sha256,
            "new_sha256": sha256_file(staged_manifest),
        },
        "assets": entries,
    }
    journal_path = extracted_dir / JOURNAL_NAME
    _write_json_atomic(journal_path, journal)
    backup_root = staging / ".publish-backup"

    try:
        if final_manifest.is_file():
            manifest_backup = backup_root / "figure_manifest.json"
            manifest_backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(final_manifest, manifest_backup)
        for entry in entries:
            portable = PurePosixPath(str(entry["path"]))
            staged_asset = staging / Path(*portable.parts)
            final_asset = extracted_dir / Path(*portable.parts)
            backup_asset = (
                backup_root / "assets" / Path(*portable.parts)
            )
            final_asset.parent.mkdir(parents=True, exist_ok=True)
            if entry["had_old"]:
                backup_asset.parent.mkdir(parents=True, exist_ok=True)
                os.replace(final_asset, backup_asset)
            os.replace(staged_asset, final_asset)
        os.replace(staged_manifest, final_manifest)
        journal["phase"] = "committed"
        _write_json_atomic(journal_path, journal)
    except BaseException as exc:
        # A mocked or unusual filesystem call may raise after committing the
        # journal rename. Re-read the durable phase before deciding whether a
        # rollback is still legal.
        try:
            durable = _load_journal(extracted_dir)
        except FigurePackageError:
            durable = journal
        if durable.get("phase") == "committed":
            _finish_committed(extracted_dir, durable)
            return
        try:
            _rollback_prepared(extracted_dir, durable)
        except FigurePackageError as rollback_exc:
            raise rollback_exc from exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise FigurePackageError(
            "Figure-package publication failed; the previous package was "
            "restored"
        ) from exc

    # From this point the new package is committed. Cleanup is best effort and
    # must never make a caller roll back a matching asset/manifest pair.
    _finish_committed(extracted_dir, journal)


def publish_staged_figure_package(
    *,
    staging: Path,
    extracted_dir: Path,
    asset_paths: list[str],
    expected_manifest_sha256: str | None = None,
    lock_held: bool = False,
) -> None:
    """Publish a staged manifest and its assets under one recoverable lock."""
    extracted_dir = extracted_dir.resolve()
    context = (
        nullcontext()
        if lock_held
        else exclusive_figure_package_lock(extracted_dir)
    )
    with context:
        if lock_held:
            _assert_lock_owned(extracted_dir)
            recover_figure_package(extracted_dir)
        _publish_locked(
            staging=staging,
            extracted_dir=extracted_dir,
            asset_paths=asset_paths,
            expected_manifest_sha256=expected_manifest_sha256,
        )
