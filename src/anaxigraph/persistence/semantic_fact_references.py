"""Backfill semantic provenance onto canonical immutable file facts."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_reconstruction import reconstruct_files


def backfill_semantic_fact_references(connection: sqlite3.Connection) -> dict[str, int]:
    placements: dict[int, dict[int, dict]] = {}

    def fact_id(snapshot_id: int, artifact_id: int) -> int | None:
        if snapshot_id not in placements:
            placements[snapshot_id] = reconstruct_files(connection, snapshot_id)
        state = placements[snapshot_id]
        value = state.get(artifact_id)
        return int(value["file_fact_id"]) if value is not None else None

    counts = {
        "semantic_claims": _backfill_claims(connection, fact_id),
        "semantic_documents": _backfill_entity_table(connection, "semantic_documents", fact_id),
        "semantic_jobs": _backfill_entity_table(connection, "semantic_jobs", fact_id),
        "semantic_scope_states": _backfill_states(connection, fact_id),
    }
    return counts


def semantic_fact_id(
    connection: sqlite3.Connection,
    snapshot_id: int,
    artifact_id: int | None,
) -> int | None:
    if artifact_id is None:
        return None
    placement = reconstruct_files(connection, snapshot_id).get(artifact_id)
    return int(placement["file_fact_id"]) if placement is not None else None


def semantic_reference_report(connection: sqlite3.Connection) -> dict[str, Any]:
    """Report whether every module-scoped semantic record names its immutable fact."""

    counts: dict[str, dict[str, int]] = {}
    for table in ("semantic_documents", "semantic_jobs", "semantic_scope_states"):
        total, canonical, compatibility = connection.execute(
            f"""
            SELECT COUNT(*), COUNT(file_fact_id), COUNT(artifact_version_id)
            FROM {table} WHERE artifact_id IS NOT NULL
            """
        ).fetchone()
        counts[table] = {
            "module_records": int(total),
            "canonical_references": int(canonical),
            "compatibility_references": int(compatibility),
        }
    total, canonical, compatibility = connection.execute(
        """
        SELECT COUNT(*), COUNT(file_fact_id), COUNT(artifact_version_id)
        FROM semantic_claims
        """
    ).fetchone()
    counts["semantic_claims"] = {
        "module_records": int(total),
        "canonical_references": int(canonical),
        "compatibility_references": int(compatibility),
    }
    missing = sum(
        value["module_records"] - value["canonical_references"] for value in counts.values()
    )
    return {
        "status": "exact" if missing == 0 else "missing",
        "missing_canonical_references": missing,
        "tables": counts,
    }


def _backfill_claims(connection: sqlite3.Connection, fact_id) -> int:
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'file_versions'"
        ).fetchone()
        is None
    ):
        return 0
    rows = connection.execute(
        """
        SELECT sc.id, fv.snapshot_id, fv.artifact_id
        FROM semantic_claims sc JOIN file_versions fv ON fv.id = sc.artifact_version_id
        WHERE sc.file_fact_id IS NULL
        """
    ).fetchall()
    updates = [
        (fact_id(int(row["snapshot_id"]), int(row["artifact_id"])), int(row["id"])) for row in rows
    ]
    connection.executemany(
        "UPDATE semantic_claims SET file_fact_id = ? WHERE id = ?",
        [value for value in updates if value[0] is not None],
    )
    return sum(value[0] is not None for value in updates)


def _backfill_entity_table(connection: sqlite3.Connection, table: str, fact_id) -> int:
    rows = connection.execute(
        f"""
        SELECT id, snapshot_id, artifact_id FROM {table}
        WHERE file_fact_id IS NULL AND artifact_id IS NOT NULL
        """
    ).fetchall()
    updates = [
        (fact_id(int(row["snapshot_id"]), int(row["artifact_id"])), int(row["id"])) for row in rows
    ]
    connection.executemany(
        f"UPDATE {table} SET file_fact_id = ? WHERE id = ?",
        [value for value in updates if value[0] is not None],
    )
    return sum(value[0] is not None for value in updates)


def _backfill_states(connection: sqlite3.Connection, fact_id) -> int:
    rows = connection.execute(
        """
        SELECT snapshot_id, scope_type, scope_key, artifact_id
        FROM semantic_scope_states
        WHERE file_fact_id IS NULL AND artifact_id IS NOT NULL
        """
    ).fetchall()
    updates = [
        (
            fact_id(int(row["snapshot_id"]), int(row["artifact_id"])),
            int(row["snapshot_id"]),
            row["scope_type"],
            row["scope_key"],
        )
        for row in rows
    ]
    connection.executemany(
        """
        UPDATE semantic_scope_states SET file_fact_id = ?
        WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?
        """,
        [value for value in updates if value[0] is not None],
    )
    return sum(value[0] is not None for value in updates)
