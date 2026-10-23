"""Deterministic, checked, manifest-last publication of Git-friendly analysis records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from anaxigraph.portable_codec import (
    MAX_DECODED_BYTES,
    MAX_LEGACY_PART,
    decode_partition,
    document_codec,
    encode_partition,
    partition_identity,
    partition_tables,
)
from anaxigraph.portable_paths import (
    LEGACY_RECORD_FORMAT,
    RECORD_FORMAT,
    SUPPORTED_RECORD_FORMATS,
    canonical_json,
    managed_record,
    record_directory,
)
from anaxigraph.storage_policy import StoragePolicy, admit_publication_peak, admit_record_write

MAX_RECORD_BYTES = 100_000_000
MAX_PART_BYTES = 4_000_000


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
    directory, manifest, parts, limit = _read_manifest(root)
    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total = 0
    for part in parts:
        encoded = _read_part(directory, part)
        total += len(encoded)
        content = decode_partition(encoded, part)
        if total > limit:
            raise ValueError("Portable record exceeds the supported size")
        rows = [json.loads(line) for line in content.splitlines() if line]
        if len(rows) != part["rows"]:
            raise ValueError("Portable record row count mismatch")
        _append_rows(tables, part, rows)
    keys = [row["key"] for rows in tables.values() for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Portable record contains duplicate identities")
    total += _read_views(directory, manifest.get("views", []))
    if total > limit:
        raise ValueError("Portable record exceeds the supported size")
    return manifest, dict(tables)


def _append_rows(tables: Any, part: Any, rows: Any) -> None:
    if part["table"] not in {"mixed", "legacy_records"}:
        tables[part["table"]].extend(rows)
        return
    for row in rows:
        table = row.get("table", "")
        if not re.fullmatch(r"[a-z_]+", table) or not row.get("key", "").startswith(table + ":"):
            raise ValueError("Invalid mixed portable row")
        tables[table].append({"key": row["key"], "value": row["value"]})


def _read_manifest(root: Path) -> tuple[Any, Any, Any, int]:
    directory = record_directory(root)
    manifest_path = safe_record_file(directory, "manifest.json")
    if manifest_path.stat().st_size > 2_000_000:
        raise ValueError("Portable manifest is too large")
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("format") not in SUPPORTED_RECORD_FORMATS:
        raise ValueError(
            "Unsupported AnaxiGraph record format; update AnaxiGraph before loading it"
        )
    parts = manifest.get("parts")
    if not isinstance(parts, list) or len(parts) > (
        4096 if manifest.get("format") == LEGACY_RECORD_FORMAT else 64
    ):
        raise ValueError("Invalid portable record parts")
    _check_part_formats(manifest, parts)
    from anaxigraph.config import load_config

    limit = min(MAX_RECORD_BYTES, load_config(root).storage.record_bytes)
    decoded = sum(
        item.get(
            "decoded_bytes",
            item.get("uncompressed_bytes", item.get("bytes", MAX_DECODED_BYTES + 1)),
        )
        for item in parts
    )
    if decoded > MAX_DECODED_BYTES:
        raise ValueError("Decoded portable record exceeds the supported size")
    declared = sum(item.get("bytes", limit + 1) for item in (*parts, *manifest.get("views", [])))
    if declared + manifest_path.stat().st_size > limit:
        raise ValueError(
            "Portable record exceeds its budget; compact it on the server holding the original index"
        )
    return directory, manifest, parts, limit


def _check_part_formats(manifest: Any, parts: Any) -> None:
    if (
        any(part.get("table") == "mixed" for part in parts)
        and manifest["format"] != "anaxigraph-record-v3"
    ):
        raise ValueError("Mixed portable partitions require the legacy v3 format")
    if (
        any(part.get("table") == "legacy_records" for part in parts)
        and manifest["format"] != RECORD_FORMAT
    ):
        raise ValueError("Cold compatibility partitions require the v4 format")


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
    root: Path,
    tables: Any,
    metadata: dict[str, Any],
    views: dict[str, bytes] | None = None,
    *,
    policy: StoragePolicy | None = None,
    before_write: Any = None,
    pool: Any = None,
) -> dict[str, Any]:
    policy = policy or StoragePolicy()
    directory = record_directory(root)
    if directory.exists() and not managed_record(root):
        raise ValueError(
            "The anaxigraph directory is not a managed record; leave it intact and choose another checkout"
        )
    if directory.is_symlink():
        raise ValueError("The AnaxiGraph record directory must not be a symlink")
    # Everything is sized before mkdir/write. Exceeding a budget never leaves orphan partitions.
    files, parts = _plan_partitions(tables, policy, cached=_cached_partitions(directory))
    entries = _plan_views(directory, files, views or {})
    manifest = {"format": RECORD_FORMAT, **metadata, "parts": parts, "views": entries}
    files["manifest.json"] = canonical_json(manifest)
    files["record.json"] = canonical_json({"format": RECORD_FORMAT})
    _admit_publication(root, files, manifest, policy, before_write, pool)
    temporary_bytes, peak_bytes = _publication_capacity(directory, files)
    if pool is not None:
        admit_publication_peak(pool[0], pool[1], temporary_bytes)
    changed = _clean_orphans(directory)
    changed += _publish_files(directory, files)
    changed += _clean_orphans(directory)
    return {
        "status": "saved",
        "record_exported": True,
        "committed": None,
        "pushed": None,
        "directory": str(directory),
        "changed_files": changed,
        "bytes": sum(path.stat().st_size for path in directory.rglob("*") if path.is_file()),
        "files": len(files),
        "parts": len(parts),
        "manifest": manifest,
        "budget_bytes": policy.record_bytes,
        "temporary_bytes": temporary_bytes,
        "record_peak_bytes": peak_bytes,
    }


def _admit_publication(root, files, manifest, policy, before_write, pool):
    total = sum(map(len, files.values()))
    if len(files) > policy.record_files or total > min(policy.record_bytes, MAX_RECORD_BYTES):
        raise ValueError(
            f"Portable record budget exceeded ({total} bytes, {len(files)} files); previous record retained"
        )
    if before_write is not None:
        before_write(total, manifest)
    if pool is not None:
        admit_record_write(pool[0], pool[1], root, total, policy)


def _publication_capacity(directory: Path, files: dict[str, bytes]) -> tuple[int, int]:
    staged = sum(
        len(content)
        for name, content in files.items()
        if not (path := safe_record_file(directory, name)).exists() or path.read_bytes() != content
    )
    parent = directory if directory.exists() else directory.parent
    if shutil.disk_usage(parent).free < staged:
        raise ValueError("Insufficient space for portable publication; previous record retained")
    previous = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
    return staged, previous + staged


def _clean_orphans(directory: Path) -> int:
    manifest = safe_record_file(directory, "manifest.json")
    retained = set()
    if manifest.exists():
        if manifest.stat().st_size > 2_000_000:
            raise ValueError("Existing portable manifest is too large; preserve it for recovery")
        value = json.loads(manifest.read_bytes())
        if value.get("format") not in SUPPORTED_RECORD_FORMATS:
            raise ValueError("Update AnaxiGraph before replacing an unsupported record format")
        retained = {item["path"] for item in (*value.get("parts", []), *value.get("views", []))}
        retained.update(item["display_path"] for item in value.get("views", []))
    removed = _remove_old_partitions(directory, retained)
    for name in (
        "mapping/architecture.json",
        "architecture/plan.json",
        "architecture/plan.md",
        "architecture/current.mmd",
        "architecture/target.mmd",
    ):
        path = safe_record_file(directory, name)
        if name not in retained and path.exists():
            path.unlink()
            removed += 1
    return removed


def _plan_views(directory: Path, files: dict[str, bytes], views: Any) -> list[Any]:
    entries = []
    for name, content in sorted((views).items()):
        safe_record_file(directory, name)
        if len(content) > MAX_PART_BYTES:
            raise ValueError("Portable record view is too large")
        digest = hashlib.sha256(content).hexdigest()
        path = f"views/{digest[:24]}.txt"
        files[path] = content
        files[name] = content
        entries.append(dict(path=path, display_path=name, sha256=digest, bytes=len(content)))
    return entries


def _cached_partitions(directory: Path) -> dict[Any, Any]:
    path = safe_record_file(directory, "manifest.json")
    if not path.exists():
        return {}
    _, _, parts, _ = _read_manifest(directory.parent)
    cached = {}
    for part in parts:
        digest = part.get("decoded_sha256")
        if not digest or "partition" not in part:
            continue
        content = _read_part(directory, part)
        decoded = decode_partition(content, part)
        if hashlib.sha256(decoded).hexdigest() != digest:
            raise ValueError("Portable decoded partition checksum mismatch")
        key = (part["table"], part["partition"], part.get("codec", "jsonl"), digest)
        cached[key] = (part, content)
    return cached


def _plan_partitions(
    tables: Any, policy: StoragePolicy, *, cached: Any = None
) -> tuple[dict[str, bytes], list[Any]]:
    files, parts = {}, []
    total = 0
    for table, rows in sorted(partition_tables(tables).items()):
        for (bucket, codec), items in _partition_buckets(table, rows).items():
            pending, size, index = [], 0, bucket
            for row in items:
                line = canonical_json(row)
                if len(line) > MAX_PART_BYTES:
                    raise ValueError("A portable record row exceeds the supported partition size")
                if pending and size + len(line) > (
                    MAX_LEGACY_PART if table == "legacy_records" else 2_000_000
                ):
                    _plan_part(files, parts, table, index, pending, codec=codec, cached=cached)
                    pending, size, index = [], 0, index + (8 if table == "legacy_records" else 2)
                pending.append(line)
                size += len(line)
                total += len(line)
                if total > MAX_DECODED_BYTES:
                    raise ValueError("Portable record budget exceeded; previous record retained")
            if pending:
                _plan_part(files, parts, table, index, pending, codec=codec, cached=cached)
            if len(parts) + 2 > policy.record_files:
                raise ValueError("Portable record budget exceeded; previous record retained")
    return files, parts


def _partition_buckets(table: str, rows: Any) -> dict[tuple[int, str], list[Any]]:
    width = 8 if table == "legacy_records" else 2
    buckets = {(bucket, codec): [] for bucket in range(width) for codec in ("jsonl", "xz")}
    ordered = sorted(rows, key=lambda item: (partition_identity(table, item), item["key"]))
    for row in ordered:
        digest = hashlib.sha256(partition_identity(table, row).encode()).digest()
        buckets[
            (
                int.from_bytes(digest[:2], "big") % width
                if table == "legacy_records"
                else digest[0] % width,
                document_codec(table, row),
            )
        ].append(row)
    return buckets


def _plan_part(
    files: Any,
    parts: Any,
    table: str,
    index: int,
    lines: list[bytes],
    *,
    codec: str,
    cached: Any = None,
) -> None:
    if not re.fullmatch(r"[a-z_]+", table):
        raise ValueError("Invalid portable table name")
    decoded = b"".join(lines)
    decoded_hash = hashlib.sha256(decoded).hexdigest()
    previous = (cached or {}).get((table, index, codec, decoded_hash))
    if previous:
        part, content = previous
        files[part["path"]] = content
        parts.append(part)
        return
    content = encode_partition(decoded, codec)
    digest = hashlib.sha256(content).hexdigest()
    category = "legacy" if codec == "xz" else _category(table)
    suffix = ".xz" if codec == "xz" else ""
    name = f"{category}/{table}-{index:x}-{digest[:24]}.jsonl{suffix}"
    files[name] = content
    parts.append(
        dict(
            table=table,
            path=name,
            sha256=digest,
            bytes=len(content),
            rows=len(lines),
            codec=codec,
            decoded_bytes=len(decoded),
            decoded_sha256=decoded_hash,
            partition=index,
        )
    )


def _publish_files(directory: Path, files: dict[str, bytes]) -> int:
    directory.mkdir(exist_ok=True)
    previous = {
        name: path.read_bytes()
        for name in files
        if (path := safe_record_file(directory, name)).exists()
    }
    changed = 0
    try:
        # The marker allows recovery from an interrupted first save. The manifest commits last.
        for name in sorted(
            files, key=lambda name: (name == "manifest.json", name != "record.json", name)
        ):
            changed += _write_if_changed(safe_record_file(directory, name), files[name])
    except BaseException:
        for name in files:
            path = safe_record_file(directory, name)
            if name in previous:
                if path.read_bytes() != previous[name]:
                    path.write_bytes(previous[name])
            elif name != "record.json":
                path.unlink(missing_ok=True)
        raise
    return changed


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
    for folder in ("", "mapping", "analyses", "views", "architecture", "legacy"):
        location = safe_record_file(directory, folder) if folder else directory
        for path in location.glob("*"):
            temporary = re.fullmatch(
                r"\.(?:record\.json|manifest\.json|architecture\.json|plan\.(?:json|md)|(?:current|target)\.mmd|[a-z_]+-[a-f0-9]+-[a-f0-9]{24}\.jsonl(?:\.xz)?|[a-f0-9]{24}\.txt)\.[0-9]+\.tmp",
                path.name,
            )
            if temporary or (
                re.fullmatch(
                    r"(?:[a-z_]+-[a-f0-9]+-[a-f0-9]{24}\.jsonl(?:\.xz)?|[a-f0-9]{24}\.txt)",
                    path.name,
                )
                and path.relative_to(directory).as_posix() not in retained
            ):
                safe_record_file(directory, path.relative_to(directory).as_posix()).unlink()
                removed += 1
    return removed
