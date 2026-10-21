"""Deterministic, checked, manifest-last publication of Git-friendly analysis records."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from anaxigraph.portable_paths import (
    RECORD_FORMAT,
    canonical_json,
    managed_record,
    record_directory,
)

MAX_RECORD_BYTES = 512 * 1024 * 1024
MAX_PART_BYTES = 64 * 1024 * 1024


def safe_record_file(directory: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Invalid portable record path")
    path = directory / relative
    if directory.is_symlink() or any(
        parent.is_symlink() for parent in (path, *path.parents) if parent != directory.parent
    ):
        raise ValueError("Portable record paths must not use symlinks")
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Portable record path escapes its directory")
    return path


def read_record(root: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    directory = record_directory(root)
    manifest_path = safe_record_file(directory, "manifest.json")
    if manifest_path.stat().st_size > 2_000_000:
        raise ValueError("Portable manifest is too large")
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("format") != RECORD_FORMAT:
        raise ValueError(
            "Unsupported AnaxiGraph record format; update AnaxiGraph before loading it"
        )
    parts = manifest.get("parts")
    if not isinstance(parts, list) or len(parts) > 4096:
        raise ValueError("Invalid portable record parts")
    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total = 0
    for part in parts:
        content = _read_part(directory, part)
        total += len(content)
        if total > MAX_RECORD_BYTES:
            raise ValueError("Portable record exceeds the supported size")
        rows = [json.loads(line) for line in content.splitlines() if line]
        if len(rows) != part["rows"]:
            raise ValueError("Portable record row count mismatch")
        tables[part["table"]].extend(rows)
    keys = [row["key"] for rows in tables.values() for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Portable record contains duplicate identities")
    total += _read_views(directory, manifest.get("views", []))
    if total > MAX_RECORD_BYTES:
        raise ValueError("Portable record exceeds the supported size")
    return manifest, dict(tables)


def _read_views(directory: Path, views: Any) -> int:
    if not isinstance(views, list) or len(views) > 64:
        raise ValueError("Invalid portable record views")
    return sum(len(_read_part(directory, view)) for view in views)


def _read_part(directory: Path, part: dict[str, Any]) -> bytes:
    path = safe_record_file(directory, part["path"])
    if path.stat().st_size > MAX_PART_BYTES:
        raise ValueError("Portable partition is too large")
    content = path.read_bytes()
    if len(content) != part["bytes"] or hashlib.sha256(content).hexdigest() != part["sha256"]:
        raise ValueError(f"Portable partition is incomplete or changed: {part['path']}")
    return content


def publish_record(
    root: Path, tables: Any, metadata: dict[str, Any], views: dict[str, bytes] | None = None
) -> dict[str, Any]:
    directory = record_directory(root)
    if directory.exists() and not managed_record(root):
        raise ValueError(
            "The anaxigraph directory is not a managed record; leave it intact and choose another checkout"
        )
    if directory.is_symlink():
        raise ValueError("The AnaxiGraph record directory must not be a symlink")
    directory.mkdir(exist_ok=True)
    marker_changed = _write_if_changed(
        safe_record_file(directory, "record.json"), canonical_json({"format": RECORD_FORMAT})
    )
    parts, changed = _write_partitions(directory, tables)
    changed += marker_changed
    view_entries, view_changes = _write_views(directory, views or {})
    changed += view_changes
    manifest = {"format": RECORD_FORMAT, **metadata, "parts": parts, "views": view_entries}
    if sum(part["bytes"] for part in (*parts, *view_entries)) > MAX_RECORD_BYTES:
        raise ValueError("Portable record exceeds the supported size; previous manifest retained")
    changed += _write_if_changed(
        safe_record_file(directory, "manifest.json"), canonical_json(manifest)
    )
    for name, content in sorted((views or {}).items()):
        changed += _write_if_changed(safe_record_file(directory, name), content)
    changed += _remove_old_partitions(directory, {part["path"] for part in (*parts, *view_entries)})
    return {
        "status": "saved",
        "directory": str(directory),
        "changed_files": changed,
        "bytes": sum(path.stat().st_size for path in directory.rglob("*") if path.is_file()),
        "parts": len(parts),
        "manifest": manifest,
    }


def _write_views(directory: Path, views: dict[str, bytes]) -> tuple[list[Any], int]:
    entries, changed = [], 0
    if len(views) > 64:
        raise ValueError("Too many portable record views")
    for name, content in sorted(views.items()):
        safe_record_file(directory, name)
        if len(content) > MAX_PART_BYTES:
            raise ValueError("Portable record view is too large")
        digest = hashlib.sha256(content).hexdigest()
        path = f"views/{digest[:24]}.txt"
        changed += _write_if_changed(safe_record_file(directory, path), content)
        entries.append(dict(path=path, display_path=name, sha256=digest, bytes=len(content)))
    return entries, changed


def _write_partitions(directory: Path, tables: Any) -> tuple[list[Any], int]:
    parts, changed = [], 0
    for table, rows in sorted(tables.items()):
        buckets: dict[str, list[Any]] = defaultdict(list)
        for row in rows:
            bucket = str(int(row["key"].split(":", 1)[1][0], 16) % 4)
            buckets[bucket].append(row)
        for bucket, items in sorted(buckets.items()):
            for partition, members, content in _partition_rows(bucket, items):
                digest = hashlib.sha256(content).hexdigest()
                name = f"{_category(table)}/{table}-{partition}-{digest[:24]}.jsonl"
                changed += _write_if_changed(safe_record_file(directory, name), content)
                parts.append(
                    dict(
                        table=table, path=name, sha256=digest, bytes=len(content), rows=len(members)
                    )
                )
    if len(parts) > 4096 or sum(part["bytes"] for part in parts) > MAX_RECORD_BYTES:
        raise ValueError(
            "Portable record exceeds the supported size; the previous manifest is retained"
        )
    return parts, changed


def _write_if_changed(path: Path, content: bytes) -> int:
    if path.exists() and path.read_bytes() == content:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return 1


def _category(table: str) -> str:
    return "analyses" if table.startswith("semantic_") else "mapping"


def _remove_old_partitions(directory: Path, retained: set[str]) -> int:
    removed = 0
    for folder in ("mapping", "analyses", "views"):
        for path in (directory / folder).glob("*"):
            if (
                re.fullmatch(
                    r"(?:[a-z_]+-[a-f0-9]+-[a-f0-9]{24}\.jsonl|[a-f0-9]{24}\.txt)", path.name
                )
                and path.relative_to(directory).as_posix() not in retained
            ):
                safe_record_file(directory, path.relative_to(directory).as_posix()).unlink()
                removed += 1
    return removed


def _partition_rows(prefix: str, items: list[Any]) -> list[tuple[str, list[Any], bytes]]:
    content = b"".join(canonical_json(row) for row in sorted(items, key=lambda row: row["key"]))
    if len(content) <= 2_000_000:
        return [(prefix, items, content)]
    if len(items) == 1:
        if len(content) > MAX_PART_BYTES:
            raise ValueError("A portable record row exceeds the supported partition size")
        return [(prefix, items, content)]
    buckets: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        buckets[item["key"].split(":", 1)[1][: len(prefix) + 1]].append(item)
    return [
        part for key, members in sorted(buckets.items()) for part in _partition_rows(key, members)
    ]
