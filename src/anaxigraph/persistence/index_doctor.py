"""Integrity, migration, parity, and compaction-readiness diagnostics."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anaxigraph.persistence.index_backup import validate_schema_backup
from anaxigraph.persistence.temporal_hashing import digest
from anaxigraph.persistence.temporal_reads import (
    snapshot_files,
    snapshot_relationship_edges,
    snapshot_symbols,
)

FILE_FIELDS = (
    "artifact_id",
    "path",
    "language",
    "runtime",
    "declared_group",
    "inferred_group",
    "raw_hash",
    "structural_hash",
    "lines_of_code",
    "comment_lines",
    "complexity",
    "summary",
    "responsibilities_json",
    "inputs_json",
    "outputs_json",
    "side_effects_json",
    "public_interfaces_json",
    "analyzer",
    "parse_error",
    "first_seen_at",
    "last_changed_at",
)
SYMBOL_FIELDS = (
    "artifact_id",
    "path",
    "symbol_type",
    "name",
    "qualified_name",
    "start_line",
    "end_line",
    "signature",
    "summary",
    "complexity",
    "logical_lines",
)
EDGE_FIELDS = (
    "source_artifact_id",
    "target_artifact_id",
    "target_external",
    "relationship_type",
    "source",
    "confidence",
    "evidence",
    "source_line",
    "weight",
    "metadata_json",
)
COMPATIBILITY_TABLES = ("file_versions", "symbols", "relationships")
TEMPORAL_TABLES = (
    "file_facts",
    "fact_symbols",
    "snapshot_file_changes",
    "relationship_sets",
    "relationship_edges",
    "snapshot_relationship_changes",
)


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
        parity = _parity_report(connection)
        lineage = _lineage_report(connection)
        rows = _row_counts(connection)
        semantic_references = _semantic_reference_count(connection)
    backup = _backup_report(migrations)
    health_blockers = _health_blockers(integrity, foreign_keys, parity, lineage, backup)
    compaction = _compaction_report(
        health_blockers,
        rows,
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
        "parity": parity,
        "rows": rows,
        "compaction": compaction,
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


def _parity_report(connection: sqlite3.Connection) -> dict[str, Any]:
    snapshots = connection.execute(
        "SELECT id, repository_id FROM snapshots ORDER BY repository_id, id"
    ).fetchall()
    mismatches: list[dict[str, Any]] = []
    for snapshot in snapshots:
        snapshot_id = int(snapshot["id"])
        differences = _frame_differences(connection, snapshot_id)
        if differences:
            mismatches.append(
                {
                    "snapshot_id": snapshot_id,
                    "repository_id": int(snapshot["repository_id"]),
                    "records": differences,
                }
            )
    return {
        "status": "exact" if not mismatches else "mismatch",
        "snapshots_checked": len(snapshots),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:50],
        "truncated": len(mismatches) > 50,
    }


def _frame_differences(connection: sqlite3.Connection, snapshot_id: int) -> list[str]:
    comparisons = (
        (
            "files",
            _legacy_files(connection, snapshot_id),
            snapshot_files(connection, snapshot_id),
            FILE_FIELDS,
        ),
        (
            "symbols",
            _legacy_symbols(connection, snapshot_id),
            snapshot_symbols(connection, snapshot_id),
            SYMBOL_FIELDS,
        ),
        (
            "relationships",
            _legacy_edges(connection, snapshot_id),
            snapshot_relationship_edges(connection, snapshot_id),
            EDGE_FIELDS,
        ),
    )
    return [
        name
        for name, legacy, temporal, fields in comparisons
        if _records_digest(legacy, fields) != _records_digest(temporal, fields)
    ]


def _legacy_files(connection: sqlite3.Connection, snapshot_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM file_versions WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _legacy_symbols(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT fv.artifact_id, fv.path, s.*
        FROM symbols s JOIN file_versions fv ON fv.id = s.artifact_version_id
        WHERE fv.snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _legacy_edges(connection: sqlite3.Connection, snapshot_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM relationships WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _records_digest(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    values = sorted(
        [tuple(row[field] for field in fields) for row in rows],
        key=repr,
    )
    return digest(values)


def _lineage_report(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT id, repository_id, base_snapshot_id, sequence FROM snapshots ORDER BY id"
    ).fetchall()
    known = {int(row["id"]): dict(row) for row in rows}
    issues: list[dict[str, Any]] = []
    maximum_depth = 0
    for snapshot_id, snapshot in known.items():
        depth, problem = _lineage_depth(snapshot_id, snapshot, known)
        maximum_depth = max(maximum_depth, depth)
        if problem:
            issues.append({"snapshot_id": snapshot_id, "problem": problem})
    return {
        "status": "valid" if not issues else "invalid",
        "snapshots": len(rows),
        "maximum_depth": maximum_depth,
        "issues": issues[:50],
        "truncated": len(issues) > 50,
    }


def _lineage_depth(
    snapshot_id: int,
    snapshot: dict[str, Any],
    known: dict[int, dict[str, Any]],
) -> tuple[int, str | None]:
    seen = {snapshot_id}
    current = snapshot
    depth = 0
    while current["base_snapshot_id"] is not None:
        base_id = int(current["base_snapshot_id"])
        if base_id in seen:
            return depth, f"cycle at snapshot {base_id}"
        base = known.get(base_id)
        if base is None:
            return depth, f"missing base snapshot {base_id}"
        if int(base["repository_id"]) != int(snapshot["repository_id"]):
            return depth, f"base snapshot {base_id} belongs to another repository"
        if int(base["sequence"]) >= int(current["sequence"]):
            return depth, f"base snapshot {base_id} is not earlier in its lineage"
        seen.add(base_id)
        current = base
        depth += 1
    return depth, None


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in (*COMPATIBILITY_TABLES, *TEMPORAL_TABLES)
    }


def _semantic_reference_count(connection: sqlite3.Connection) -> int:
    tables = ("semantic_claims", "semantic_documents", "semantic_jobs", "semantic_scope_states")
    return sum(
        int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE artifact_version_id IS NOT NULL"
            ).fetchone()[0]
        )
        for table in tables
    )


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
    backup: dict[str, Any],
) -> list[str]:
    blockers = []
    if integrity != "ok":
        blockers.append("integrity_check_failed")
    if foreign_keys:
        blockers.append("foreign_key_violations")
    if parity["status"] != "exact":
        blockers.append("temporal_parity_mismatch")
    if lineage["status"] != "valid":
        blockers.append("invalid_snapshot_lineage")
    if backup["status"] not in {"valid", "not_required"}:
        blockers.append("recovery_backup_invalid")
    return blockers


def _compaction_report(
    health_blockers: list[str],
    rows: dict[str, int],
    semantic_references: int,
) -> dict[str, Any]:
    blockers = list(health_blockers)
    blockers.append("compatibility_read_paths_active")
    if semantic_references:
        blockers.append("semantic_records_reference_compatibility_versions")
    return {
        "eligible": False,
        "performed": False,
        "blockers": blockers,
        "compatibility_rows": sum(rows[table] for table in COMPATIBILITY_TABLES),
        "semantic_version_references": semantic_references,
        "message": (
            "Compatibility rows are retained until bounded reads and semantic consumers use "
            "canonical facts. No data was deleted."
        ),
    }
