"""Frame-level parity checks between compatibility rows and canonical facts."""

from __future__ import annotations

import sqlite3
from typing import Any

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


def parity_report(connection: sqlite3.Connection) -> dict[str, Any]:
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
