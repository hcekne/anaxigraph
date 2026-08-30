"""Integrity, migration, parity, and compaction-readiness diagnostics."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anaxigraph.persistence.compatibility_compaction import COMPATIBILITY_TABLES
from anaxigraph.persistence.index_backup import validate_schema_backup
from anaxigraph.persistence.index_parity import parity_report
from anaxigraph.persistence.index_temporal_health import (
    lineage_report,
    reconstruction_report,
)
from anaxigraph.persistence.semantic_fact_references import semantic_reference_report
from anaxigraph.persistence.temporal_schema import TEMPORAL_TABLES


def inspect_index(
    database_path: Path,
    connection_factory: Callable[[], sqlite3.Connection],
) -> dict[str, Any]:
    """Return a deterministic safety report without changing the index."""

    with connection_factory() as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        schema_version = _schema_version(connection)
        migrations = _migrations(connection)
        parity = parity_report(connection)
        lineage = lineage_report(connection)
        reconstruction = reconstruction_report(connection)
        rows = _row_counts(connection)
        semantic_references = semantic_reference_report(connection)
    backup = _backup_report(migrations)
    health_blockers = _health_blockers(
        integrity,
        foreign_keys,
        parity,
        lineage,
        reconstruction,
        backup,
        semantic_references,
    )
    return {
        "status": "healthy" if not health_blockers else "blocked",
        "database": str(database_path),
        "schema_version": schema_version,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
        "migration": migrations[-1] if migrations else None,
        "backup": backup,
        "lineage": lineage,
        "reconstruction": reconstruction,
        "parity": parity,
        "semantic_references": semantic_references,
        "rows": rows,
        "compaction": _compaction_report(health_blockers, rows, semantic_references),
        "blockers": health_blockers,
    }


def _schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row[0])


def _migrations(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM schema_migrations ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    present = {
        str(row["name"])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return {
        table: (
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if table in present
            else 0
        )
        for table in (*COMPATIBILITY_TABLES, *TEMPORAL_TABLES)
    }


def _backup_report(migrations: list[dict[str, Any]]) -> dict[str, Any]:
    migrated = next(
        (row for row in reversed(migrations) if int(row["from_version"]) == 6),
        None,
    )
    if migrated is None:
        return {"status": "not_required", "required": False}
    try:
        backup = validate_schema_backup(
            migrated["backup_path"],
            expected_version=int(migrated["from_version"]),
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        return {"status": "invalid", "required": True, "error": str(exc)}
    matches = backup.sha256 == migrated["backup_sha256"]
    return {
        "status": "valid" if matches else "checksum_mismatch",
        "required": True,
        **backup.as_dict(),
    }


def _health_blockers(
    integrity: str,
    foreign_keys: list[tuple[Any, ...]],
    parity: dict[str, Any],
    lineage: dict[str, Any],
    reconstruction: dict[str, Any],
    backup: dict[str, Any],
    semantic_references: dict[str, Any],
) -> list[str]:
    blockers = []
    if integrity != "ok":
        blockers.append("integrity_check_failed")
    if foreign_keys:
        blockers.append("foreign_key_violations")
    if parity["status"] not in {"exact", "canonical_only"}:
        blockers.append("temporal_parity_mismatch")
    if lineage["status"] != "valid":
        blockers.append("invalid_snapshot_lineage")
    if reconstruction["status"] != "bounded":
        blockers.append("invalid_or_unbounded_checkpoints")
    if backup["status"] not in {"valid", "not_required"}:
        blockers.append("recovery_backup_invalid")
    if semantic_references["status"] != "exact":
        blockers.append("semantic_fact_references_missing")
    return blockers


def _compaction_report(
    health_blockers: list[str],
    rows: dict[str, int],
    semantic_references: dict[str, Any],
) -> dict[str, Any]:
    blockers = list(health_blockers)
    compatibility_rows = sum(rows[table] for table in COMPATIBILITY_TABLES)
    if compatibility_rows:
        blockers.append("compatibility_rows_remain")
    compatibility_references = sum(
        value["compatibility_references"] for value in semantic_references["tables"].values()
    )
    if compatibility_references:
        blockers.append("semantic_records_reference_compatibility_versions")
    eligible = not blockers and compatibility_rows == 0 and compatibility_references == 0
    return {
        "eligible": eligible,
        "performed": eligible,
        "blockers": blockers,
        "compatibility_rows": compatibility_rows,
        "semantic_version_references": compatibility_references,
        "message": (
            "Compatibility rows have been compacted; canonical facts are authoritative."
            if eligible
            else "Compatibility compaction is blocked; no additional data was deleted."
        ),
    }
