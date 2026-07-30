#!/usr/bin/env python3
"""Validate portable extraction manifests and their local assets."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
from typing import Any

from figure_package import (
    exclusive_figure_package_lock,
    publish_staged_figure_package,
)
from paper_naming import NamingError, sha256_file
from safe_json import (
    atomic_write_json_if_unchanged,
    exclusive_update_lock,
)

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WINDOWS_INVALID_CHARACTERS = frozenset('<>:"\\|?*')


def _filesystem_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def validate_figure_manifest_items(
    items: Any,
    *,
    extracted_dir: Path,
    asset_overrides: dict[str, Path] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise NamingError("figure_manifest.json field 'items' must be an array")

    seen_paths: dict[str, str] = {}
    validated: list[dict[str, Any]] = []
    extracted_root = extracted_dir.resolve()
    for number, item in enumerate(items):
        if not isinstance(item, dict):
            raise NamingError(
                f"figure_manifest.json item {number} must be an object"
            )
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise NamingError(
                f"figure_manifest.json item {number} requires a path"
            )
        if "\\" in path_value:
            raise NamingError(
                f"Figure path must use forward slashes: {path_value}"
            )
        portable = PurePosixPath(path_value)
        if (
            portable.as_posix() != path_value
            or unicodedata.normalize("NFKC", path_value) != path_value
            or portable.is_absolute()
            or ".." in portable.parts
            or len(portable.parts) < 2
            or portable.parts[0] != "figures"
        ):
            raise NamingError(
                "Figure assets must use safe paths below figures/: "
                f"{path_value}"
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
                raise NamingError(
                    "Figure path is not portable across common filesystems: "
                    f"{path_value}"
                )
        path_key = _filesystem_key(portable.as_posix())
        if path_key in seen_paths:
            raise NamingError(
                "Figure manifest contains filesystem-equivalent duplicate "
                f"paths: {seen_paths[path_key]}, {path_value}"
            )
        seen_paths[path_key] = path_value

        if asset_overrides and path_value in asset_overrides:
            asset_path = asset_overrides[path_value].resolve()
        else:
            asset_path = (
                extracted_root / Path(*portable.parts)
            ).resolve()
            try:
                asset_path.relative_to(extracted_root)
            except ValueError as exc:
                raise NamingError(
                    f"Figure asset escapes extracted/: {path_value}"
                ) from exc
        if not asset_path.is_file():
            raise NamingError(f"Figure asset not found: {path_value}")

        asset_sha256 = item.get("sha256")
        if not isinstance(asset_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", asset_sha256
        ):
            raise NamingError(
                f"Figure item {path_value} requires a lowercase SHA-256"
            )
        if sha256_file(asset_path) != asset_sha256:
            raise NamingError(
                f"Figure asset SHA-256 mismatch: {path_value}"
            )
        if "bytes" in item and item["bytes"] != asset_path.stat().st_size:
            raise NamingError(f"Figure asset byte count mismatch: {path_value}")
        validated.append(item)
    return validated


def load_figure_manifest_for_source(
    manifest_path: Path,
    *,
    source_pdf: Path,
    validate_assets: bool = True,
) -> dict[str, Any]:
    if manifest_path.name != "figure_manifest.json":
        raise NamingError("Manifest path must end with figure_manifest.json")
    if not manifest_path.is_file():
        raise NamingError(
            "figure_manifest.json does not exist; run figure extraction first"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise NamingError(
            f"Figure manifest is not valid UTF-8: {manifest_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise NamingError(
            f"Invalid figure manifest JSON: {manifest_path}: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise NamingError("figure_manifest.json must contain a JSON object")
    if manifest.get("source_pdf") != source_pdf.name:
        raise NamingError(
            "figure_manifest.json belongs to a different source PDF"
        )
    source_sha256 = sha256_file(source_pdf)
    if manifest.get("source_sha256") != source_sha256:
        raise NamingError(
            "figure_manifest.json source SHA-256 does not match the PDF"
        )
    if validate_assets:
        validate_figure_manifest_items(
            manifest.get("items"),
            extracted_dir=manifest_path.parent,
        )
    elif not isinstance(manifest.get("items"), list):
        raise NamingError(
            "figure_manifest.json field 'items' must be an array"
        )
    return manifest


def record_figure_asset(
    manifest_path: Path,
    *,
    source_pdf: Path,
    asset_path: Path,
    record: dict[str, Any],
    package_lock_held: bool = False,
) -> dict[str, Any]:
    """Add or replace one verified asset record in a canonical manifest."""
    package_context = (
        nullcontext()
        if package_lock_held
        else exclusive_figure_package_lock(manifest_path.parent)
    )
    with package_context, exclusive_update_lock(manifest_path):
        expected_manifest_sha256 = sha256_file(manifest_path)
        manifest = load_figure_manifest_for_source(
            manifest_path,
            source_pdf=source_pdf,
            validate_assets=False,
        )
        extracted_root = manifest_path.parent.resolve()
        resolved_asset = asset_path.resolve()
        try:
            relative = resolved_asset.relative_to(extracted_root)
        except ValueError as exc:
            raise NamingError(
                "Cropped asset must be inside the canonical extracted directory"
            ) from exc
        portable = PurePosixPath(*relative.parts)
        if len(portable.parts) < 2 or portable.parts[0] != "figures":
            raise NamingError(
                "Cropped asset must be stored under extracted/figures"
            )
        updated_record = {
            **record,
            "path": portable.as_posix(),
            "sha256": sha256_file(resolved_asset),
            "bytes": resolved_asset.stat().st_size,
        }
        items = manifest.get("items")
        assert isinstance(items, list)
        updated_items = [
            item
            for item in items
            if not (
                isinstance(item, dict)
                and item.get("path") == updated_record["path"]
            )
        ]
        updated_items.append(updated_record)
        validate_figure_manifest_items(
            updated_items,
            extracted_dir=manifest_path.parent,
        )
        manifest["items"] = updated_items
        atomic_write_json_if_unchanged(
            manifest_path,
            manifest,
            expected_sha256=expected_manifest_sha256,
        )
    return updated_record


def publish_cropped_figure_asset(
    manifest_path: Path,
    *,
    source_pdf: Path,
    staging: Path,
    asset_path: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Commit one staged crop and its manifest item as one package update."""
    manifest_path = manifest_path.resolve()
    extracted_root = manifest_path.parent.resolve()
    staging = staging.resolve()
    resolved_asset = asset_path.resolve()
    try:
        relative = resolved_asset.relative_to(extracted_root)
    except ValueError as exc:
        raise NamingError(
            "Cropped asset must be inside the canonical extracted directory"
        ) from exc
    portable = PurePosixPath(*relative.parts)
    if len(portable.parts) < 2 or portable.parts[0] != "figures":
        raise NamingError(
            "Cropped asset must be stored under extracted/figures"
        )
    relative_path = portable.as_posix()
    staged_asset = staging / Path(*portable.parts)
    if not staged_asset.is_file():
        raise NamingError(f"Staged cropped asset not found: {staged_asset}")

    with exclusive_figure_package_lock(extracted_root):
        expected_manifest_sha256 = sha256_file(manifest_path)
        manifest = load_figure_manifest_for_source(
            manifest_path,
            source_pdf=source_pdf,
        )
        updated_record = {
            **record,
            "path": relative_path,
            "sha256": sha256_file(staged_asset),
            "bytes": staged_asset.stat().st_size,
        }
        path_key = _filesystem_key(relative_path)
        items = manifest.get("items")
        assert isinstance(items, list)
        updated_items = [
            item
            for item in items
            if not (
                isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and _filesystem_key(str(item["path"])) == path_key
            )
        ]
        updated_items.append(updated_record)
        validate_figure_manifest_items(
            updated_items,
            extracted_dir=extracted_root,
            asset_overrides={relative_path: staged_asset},
        )
        manifest["items"] = updated_items
        staged_manifest = staging / "figure_manifest.json"
        with staged_manifest.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if sha256_file(source_pdf) != manifest["source_sha256"]:
            raise NamingError(
                "The source PDF changed during cropping; the package was "
                "left untouched"
            )
        publish_staged_figure_package(
            staging=staging,
            extracted_dir=extracted_root,
            asset_paths=[relative_path],
            expected_manifest_sha256=expected_manifest_sha256,
            lock_held=True,
        )
    return updated_record
