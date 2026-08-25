"""Validated SQLite backups for schema upgrades and operator recovery."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IndexBackup:
    path: Path
    schema_version: int
    bytes: int
    sha256: str
    reused: bool

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["path"] = str(self.path)
        return value


def backup_path(database_path: str | Path, schema_version: int) -> Path:
    source = Path(database_path).expanduser().resolve()
    return source.with_name(f"{source.name}.schema-v{schema_version}.backup")


def create_schema_backup(
    database_path: str | Path,
    *,
    schema_version: int,
) -> IndexBackup:
    source = Path(database_path).expanduser().resolve()
    destination = backup_path(source, schema_version)
    if destination.exists():
        _validate_database(destination, expected_version=schema_version)
        return _report(destination, schema_version, reused=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    try:
        _sqlite_backup(source, temporary)
        _validate_database(temporary, expected_version=schema_version)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _report(destination, schema_version, reused=False)


def create_index_backup(
    database_path: str | Path,
    destination_path: str | Path | None = None,
) -> IndexBackup:
    """Create a new, validated online backup without changing the live index."""

    source = Path(database_path).expanduser().resolve()
    schema_version = _validate_database(source)
    destination = (
        Path(destination_path).expanduser().resolve()
        if destination_path is not None
        else _operational_backup_path(source)
    )
    if destination == source:
        raise ValueError("Backup output must differ from the AnaxiIndex path")
    if destination.exists():
        raise ValueError(f"Backup output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    try:
        _sqlite_backup(source, temporary)
        _validate_database(temporary, expected_version=schema_version)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _report(destination, schema_version, reused=False)


def restore_schema_backup(
    database_path: str | Path,
    source_backup: str | Path,
    *,
    expected_version: int,
) -> IndexBackup:
    destination = Path(database_path).expanduser().resolve()
    source = Path(source_backup).expanduser().resolve()
    _validate_database(source, expected_version=expected_version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.restore-{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    try:
        _sqlite_backup(source, temporary)
        _validate_database(temporary, expected_version=expected_version)
        temporary.replace(destination)
        _remove_sidecars(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    _validate_database(destination, expected_version=expected_version)
    return _report(destination, expected_version, reused=False)


def restore_index_backup(
    database_path: str | Path,
    source_backup: str | Path,
) -> IndexBackup:
    """Replace an index atomically from a validated backup image."""

    destination = Path(database_path).expanduser().resolve()
    source = Path(source_backup).expanduser().resolve()
    if destination == source:
        raise ValueError("Backup source must differ from the AnaxiIndex path")
    schema_version = _validate_database(source)
    return restore_schema_backup(destination, source, expected_version=schema_version)


def validate_schema_backup(path: str | Path, *, expected_version: int) -> IndexBackup:
    candidate = Path(path).expanduser().resolve()
    _validate_database(candidate, expected_version=expected_version)
    return _report(candidate, expected_version, reused=True)


def validate_index_backup(path: str | Path) -> IndexBackup:
    """Validate an operator backup and infer its schema version."""

    candidate = Path(path).expanduser().resolve()
    schema_version = _validate_database(candidate)
    return _report(candidate, schema_version, reused=True)


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ValueError(f"AnaxiIndex does not exist: {source}")
    with sqlite3.connect(source) as origin, sqlite3.connect(destination) as target:
        origin.backup(target)


def _validate_database(path: Path, *, expected_version: int | None = None) -> int:
    if not path.is_file():
        raise ValueError(f"Schema backup does not exist: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError(f"Schema backup failed integrity check: {path}")
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    actual = int(row[0]) if row is not None else None
    if expected_version is not None and actual != expected_version:
        raise RuntimeError(
            f"Schema backup is version {actual}, expected {expected_version}: {path}"
        )
    if actual is None:
        raise RuntimeError(f"Index backup has no schema version: {path}")
    return actual


def _report(path: Path, schema_version: int, *, reused: bool) -> IndexBackup:
    return IndexBackup(
        path=path,
        schema_version=schema_version,
        bytes=path.stat().st_size,
        sha256=_sha256(path),
        reused=reused,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists():
            candidate.unlink()


def _operational_backup_path(source: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return source.with_name(f"{source.name}.{timestamp}.backup")
