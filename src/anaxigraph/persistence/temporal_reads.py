"""Canonical snapshot reconstruction over immutable facts and sparse deltas."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_facts import (
    reconstruct_files,
    reconstruct_relationships,
)

SQLITE_BATCH = 800


def snapshot_files(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> list[dict[str, Any]]:
    """Reconstruct complete file records for one snapshot."""

    placements = reconstruct_files(connection, snapshot_id)
    facts = {
        int(row["id"]): row
        for row in _rows_for_ids(
            connection,
            "file_facts",
            "id",
            [int(value["file_fact_id"]) for value in placements.values()],
        )
    }
    result: list[dict[str, Any]] = []
    for placement in placements.values():
        fact = facts.get(int(placement["file_fact_id"]))
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

    files = snapshot_files(connection, snapshot_id)
    by_fact = {int(file["file_fact_id"]): file for file in files}
    rows = _rows_for_ids(
        connection,
        "fact_symbols",
        "file_fact_id",
        list(by_fact),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        file = by_fact[int(row["file_fact_id"])]
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

    relationships = reconstruct_relationships(connection, snapshot_id)
    by_set = {
        relationship_set_id: source_id for source_id, relationship_set_id in relationships.items()
    }
    rows = _rows_for_ids(
        connection,
        "relationship_edges",
        "relationship_set_id",
        list(by_set),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        value["source_artifact_id"] = by_set[int(row["relationship_set_id"])]
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


def _rows_for_ids(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    values: list[int],
) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    unique = sorted(set(values))
    for offset in range(0, len(unique), SQLITE_BATCH):
        batch = unique[offset : offset + SQLITE_BATCH]
        placeholders = ",".join("?" for _value in batch)
        rows.extend(
            connection.execute(
                f"SELECT * FROM {table} WHERE {column} IN ({placeholders})",
                batch,
            ).fetchall()
        )
    return rows
