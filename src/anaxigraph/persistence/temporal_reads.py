"""Canonical snapshot reconstruction over immutable facts and sparse deltas."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_facts import (
    reconstruct_files,
    reconstruct_relationships,
)


def snapshot_files(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> list[dict[str, Any]]:
    """Reconstruct complete file records for one snapshot."""

    result: list[dict[str, Any]] = []
    for placement in reconstruct_files(connection, snapshot_id).values():
        fact = connection.execute(
            "SELECT * FROM file_facts WHERE id = ?",
            (placement["file_fact_id"],),
        ).fetchone()
        if fact is None:
            raise RuntimeError(
                f"Snapshot {snapshot_id} references missing file fact {placement['file_fact_id']}"
            )
        value = dict(fact)
        value["file_fact_id"] = value.pop("id")
        value.update(
            {
                key: placement[key]
                for key in (
                    "path",
                    "declared_group",
                    "inferred_group",
                    "analysis_status",
                    "first_seen_at",
                    "last_changed_at",
                )
            }
        )
        result.append(value)
    return sorted(result, key=lambda item: (item["path"], item["artifact_id"]))


def snapshot_symbols(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> list[dict[str, Any]]:
    """Reconstruct symbols attached to the frame's immutable file facts."""

    result: list[dict[str, Any]] = []
    for file in snapshot_files(connection, snapshot_id):
        rows = connection.execute(
            """
            SELECT symbol_type, name, qualified_name, start_line, end_line,
                   signature, summary, complexity, logical_lines
            FROM fact_symbols
            WHERE file_fact_id = ? ORDER BY start_line, qualified_name
            """,
            (file["file_fact_id"],),
        ).fetchall()
        for row in rows:
            value = dict(row)
            value["artifact_id"] = file["artifact_id"]
            value["path"] = file["path"]
            result.append(value)
    return sorted(
        result,
        key=lambda item: (
            item["path"],
            item["start_line"],
            item["qualified_name"],
        ),
    )


def snapshot_relationship_edges(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> list[dict[str, Any]]:
    """Reconstruct every relationship edge active in one snapshot."""

    result: list[dict[str, Any]] = []
    for source_id, relationship_set_id in reconstruct_relationships(
        connection,
        snapshot_id,
    ).items():
        rows = connection.execute(
            """
            SELECT target_artifact_id, target_external, relationship_type, source,
                   confidence, evidence, source_line, weight, metadata_json
            FROM relationship_edges
            WHERE relationship_set_id = ? ORDER BY id
            """,
            (relationship_set_id,),
        ).fetchall()
        for row in rows:
            value = dict(row)
            value["source_artifact_id"] = source_id
            result.append(value)
    return sorted(result, key=_edge_sort_key)


def _edge_sort_key(value: dict[str, Any]) -> tuple[Any, ...]:
    return (
        value["source_artifact_id"],
        value["target_artifact_id"] or -1,
        value["target_external"] or "",
        value["relationship_type"],
        value["source_line"],
    )
