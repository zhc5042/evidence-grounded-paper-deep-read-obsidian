#!/usr/bin/env python3
"""Concurrency-aware JSON updates for paper workspace metadata."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from paper_naming import sha256_file


class ConcurrentUpdateError(RuntimeError):
    """Raised when an index changes while an update is being prepared."""


LOCK_TOKEN_PATTERN = re.compile(r"^(?P<pid>[1-9][0-9]*)-[0-9a-f]{32}$")


def process_is_alive(pid: int) -> bool:
    """Check a PID without sending a terminating signal on Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(
                handle,
                ctypes.byref(exit_code),
            ):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock_owner(lock_path: Path) -> tuple[str, int]:
    try:
        token = lock_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConcurrentUpdateError(
            f"Cannot inspect workspace lock safely: {lock_path}"
        ) from exc
    match = LOCK_TOKEN_PATTERN.fullmatch(token)
    if match is None:
        raise ConcurrentUpdateError(
            "Workspace lock has an unrecognized owner token; inspect it "
            f"manually before retrying: {lock_path}"
        )
    return token, int(match.group("pid"))


@contextmanager
def _recovery_guard(lock_path: Path) -> Iterator[None]:
    """Serialize recovery attempts while leaving the primary lock occupied."""
    guard_path = lock_path.with_name(f"{lock_path.name}.recovery")
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
            existing_token, owner_pid = _read_lock_owner(guard_path)
            if process_is_alive(owner_pid):
                raise ConcurrentUpdateError(
                    f"Another process is recovering the workspace: {guard_path}"
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
        raise ConcurrentUpdateError(
            f"Could not acquire workspace recovery guard: {guard_path}"
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


def _restore_stale_backup(backup: Path, destination: Path) -> None:
    _restore_without_overwrite(backup, destination)


def _preserve_old_backup(backup: Path) -> None:
    destination = backup.with_name(
        f"{backup.name.removesuffix('.previous')}.recovered-backup"
    )
    if destination.exists():
        destination = backup.with_name(
            f"{backup.name.removesuffix('.previous')}."
            f"{uuid.uuid4().hex}.recovered-backup"
        )
    os.rename(backup, destination)


def _is_valid_json_file(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


def _recover_stale_update(path: Path, lock_path: Path) -> None:
    """Restore a usable canonical file after a dead writer is detected."""
    with _recovery_guard(lock_path):
        if not lock_path.exists():
            return
        stale_token, owner_pid = _read_lock_owner(lock_path)
        if process_is_alive(owner_pid):
            raise ConcurrentUpdateError(
                f"Another update holds the workspace lock: {lock_path}"
            )

        previous_files = sorted(
            candidate
            for candidate in path.parent.glob(
                f".{path.name}.*.previous"
            )
            if candidate.is_file()
        )
        prepared_files = sorted(
            candidate
            for candidate in path.parent.glob(
                f".{path.name}.*.prepared"
            )
            if candidate.is_file()
        )
        if not path.exists():
            if len(previous_files) != 1:
                raise ConcurrentUpdateError(
                    f"Cannot recover {path.name} automatically: expected one "
                    f"previous copy, found {len(previous_files)}. The stale "
                    f"lock remains at {lock_path}."
                )
            _restore_stale_backup(previous_files[0], path)
            previous_files = []
        elif not path.is_file():
            raise ConcurrentUpdateError(
                f"Cannot recover because the canonical path is not a file: {path}"
            )
        elif previous_files:
            canonical_sha256 = sha256_file(path)
            previous_hashes = {
                sha256_file(candidate) for candidate in previous_files
            }
            prepared_hashes = {
                sha256_file(candidate) for candidate in prepared_files
            }
            incomplete_publish = bool(prepared_files) and (
                canonical_sha256 not in previous_hashes
                and canonical_sha256 not in prepared_hashes
            )
            invalid_canonical = not _is_valid_json_file(path)
            if incomplete_publish or invalid_canonical:
                if len(previous_files) != 1:
                    raise ConcurrentUpdateError(
                        f"Cannot recover incomplete {path.name}: expected one "
                        f"previous copy, found {len(previous_files)}"
                    )
                path.unlink()
                _restore_stale_backup(previous_files[0], path)
                previous_files = []

        for backup in previous_files:
            _preserve_old_backup(backup)
        for prepared in prepared_files:
            prepared.unlink(missing_ok=True)

        try:
            if lock_path.read_text(encoding="utf-8").strip() != stale_token:
                raise ConcurrentUpdateError(
                    "Workspace lock ownership changed during crash recovery"
                )
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _cleanup_completed_update_artifacts(path: Path) -> None:
    """Recover an orphaned capture, then remove completed-update leftovers."""
    previous_files = sorted(
        candidate
        for candidate in path.parent.glob(f".{path.name}.*.previous")
        if candidate.is_file()
    )
    prepared_files = sorted(
        candidate
        for candidate in path.parent.glob(f".{path.name}.*.prepared")
        if candidate.is_file()
    )

    if not path.exists():
        if len(previous_files) != 1:
            raise ConcurrentUpdateError(
                f"Canonical JSON is missing: {path}. Expected exactly one "
                f"recoverable previous copy, found {len(previous_files)}."
            )
        _restore_stale_backup(previous_files[0], path)
        previous_files = []
    elif not path.is_file():
        raise ConcurrentUpdateError(
            f"Canonical JSON path is not a file: {path}"
        )

    canonical_sha256 = sha256_file(path)
    for backup in previous_files:
        if sha256_file(backup) == canonical_sha256:
            backup.unlink()
        else:
            _preserve_old_backup(backup)
    for prepared in prepared_files:
        prepared.unlink()


@contextmanager
def exclusive_update_lock(path: Path) -> Iterator[None]:
    """Serialize cooperating writers with an exclusive sidecar lock."""
    lock_path = path.with_name(f".{path.name}.lock")
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    for _ in range(2):
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            break
        except FileExistsError:
            _recover_stale_update(path, lock_path)
    else:
        raise ConcurrentUpdateError(
            f"Could not acquire workspace lock: {lock_path}"
        )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as lock:
            lock.write(token + "\n")
            lock.flush()
            os.fsync(lock.fileno())
        _cleanup_completed_update_artifacts(path)
        yield
    finally:
        try:
            if lock_path.read_text(encoding="utf-8").strip() == token:
                lock_path.unlink()
        except FileNotFoundError:
            pass


def _restore_without_overwrite(backup: Path, destination: Path) -> None:
    try:
        os.link(backup, destination)
    except FileExistsError as exc:
        raise ConcurrentUpdateError(
            f"A concurrent writer recreated {destination.name}. The pre-update "
            f"copy is preserved at {backup}"
        ) from exc
    except OSError:
        descriptor: int | None = None
        try:
            source_mode = stat.S_IMODE(backup.stat().st_mode)
            descriptor = os.open(
                destination,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                source_mode,
            )
            with backup.open("rb") as source, os.fdopen(
                descriptor,
                "wb",
            ) as restored:
                descriptor = None
                for chunk in iter(
                    lambda: source.read(1024 * 1024),
                    b"",
                ):
                    restored.write(chunk)
                restored.flush()
                os.fsync(restored.fileno())
            if sha256_file(destination) != sha256_file(backup):
                destination.unlink(missing_ok=True)
                raise ConcurrentUpdateError(
                    f"Restored copy of {destination.name} failed verification"
                )
        except FileExistsError as exc:
            raise ConcurrentUpdateError(
                f"A writer recreated {destination.name}; the pre-update "
                f"copy remains at {backup}"
            ) from exc
        except (OSError, ConcurrentUpdateError) as exc:
            if descriptor is not None:
                os.close(descriptor)
            destination.unlink(missing_ok=True)
            if isinstance(exc, ConcurrentUpdateError):
                raise
            raise ConcurrentUpdateError(
                f"Could not restore {destination.name} without risking "
                f"overwrite. The pre-update copy remains at {backup}"
            ) from exc
    try:
        backup.unlink()
    except OSError:
        try:
            _preserve_old_backup(backup)
        except OSError:
            pass


def _compare_exchange_file(
    *,
    destination: Path,
    prepared: Path,
    expected_sha256: str,
) -> None:
    """Publish prepared only if the atomically captured old file is unchanged."""
    backup = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.previous"
    )
    try:
        os.rename(destination, backup)
    except FileNotFoundError as exc:
        raise ConcurrentUpdateError(
            f"File disappeared during update: {destination}"
        ) from exc

    try:
        captured_sha256 = sha256_file(backup)
        if captured_sha256 != expected_sha256:
            raise ConcurrentUpdateError(
                "paper_index.json changed during the merge; concurrent edits "
                "were preserved and this update was cancelled"
            )
        os.link(prepared, destination)
    except BaseException as exc:
        # Some wrappers and unusual filesystems can report an error after the
        # hard link became durable. In that case the new canonical file is
        # already committed and must not be rolled back.
        try:
            committed = (
                destination.is_file()
                and prepared.is_file()
                and os.path.samefile(prepared, destination)
            )
        except OSError:
            committed = False
        if committed:
            try:
                prepared.unlink()
            except OSError:
                pass
            try:
                backup.unlink()
            except OSError:
                try:
                    _preserve_old_backup(backup)
                except OSError:
                    pass
            return

        try:
            _restore_without_overwrite(backup, destination)
        except ConcurrentUpdateError as restore_exc:
            raise restore_exc from exc
        finally:
            try:
                prepared.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, ConcurrentUpdateError):
            raise
        if not isinstance(exc, Exception):
            raise
        raise ConcurrentUpdateError(
            "The captured JSON could not be verified or published; the "
            "previous canonical file was restored"
        ) from exc

    # Commit occurs when the canonical hard link is created. Cleanup failures
    # must not masquerade as a failed commit, because callers may otherwise
    # roll back related assets while this JSON already contains the new state.
    try:
        prepared.unlink()
    except OSError:
        pass
    try:
        backup.unlink()
    except OSError:
        try:
            _preserve_old_backup(backup)
        except OSError:
            pass


def atomic_write_json_if_unchanged(
    path: Path,
    value: dict[str, Any],
    *,
    expected_sha256: str,
) -> None:
    """Write JSON with an atomic capture-and-compare commit."""
    if not path.is_file():
        raise ConcurrentUpdateError(f"JSON file not found: {path}")
    original_mode = stat.S_IMODE(path.stat().st_mode)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{path.name}.",
        suffix=".prepared",
        dir=path.parent,
        delete=False,
    )
    prepared = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(prepared, original_mode)
        _compare_exchange_file(
            destination=path,
            prepared=prepared,
            expected_sha256=expected_sha256,
        )
    except Exception:
        prepared.unlink(missing_ok=True)
        raise
