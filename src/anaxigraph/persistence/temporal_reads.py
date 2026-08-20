"""Canonical snapshot reconstruction over immutable facts and sparse deltas."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.ir_serialization import expand_stored_metadata
from anaxigraph.persistence.temporal_reconstruction import (
    ReconstructionDiagnostics,
    reconstruct_files,
    reconstruct_files_with_diagnostics,
    reconstruct_relationships,
    reconstruct_relationships_with_diagnostics,
)

SQLITE_BATCH = 800


def snapshot_files(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    expand_metadata: bool = True,
) -> list[dict[str, Any]]:
    """Reconstruct complete file records for one snapshot."""

    placements = reconstruct_files(connection, snapshot_id)
    return _files_for_placements(
        connection,
        snapshot_id,
        placements,
        expand_metadata=expand_metadata,
    )


def snapshot_files_with_diagnostics(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    expand_metadata: bool = True,
) -> tuple[list[dict[str, Any]], ReconstructionDiagnostics]:
    """Reconstruct files and expose the bounded-read evidence."""

    placements, diagnostics = reconstruct_files_with_diagnostics(connection, snapshot_id)
    return (
        _files_for_placements(
            connection,
            snapshot_id,
            placements,
            expand_metadata=expand_metadata,
        ),
        diagnostics,
    )


def _files_for_placements(
    connection: sqlite3.Connection,
    snapshot_id: int,
    placements: dict[int, dict[str, Any]],
    *,
    expand_metadata: bool,
) -> list[dict[str, Any]]:
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
        if expand_metadata:
            value["metadata_json"] = _expanded_metadata_json(value, placement)
        result.append(value)
    return sorted(result, key=lambda item: (item["path"], item["artifact_id"]))


def _expanded_metadata_json(
    value: dict[str, Any],
    placement: dict[str, Any],
) -> str:
    metadata = json.loads(value["metadata_json"] or "{}")
    metadata.update(json.loads(placement.get("metadata_json") or "{}"))
    expanded = expand_stored_metadata(
        metadata,
        path=str(value["path"]),
        language=str(value["language"]),
        public_interfaces=json.loads(value["public_interfaces_json"] or "[]"),
    )
    return json.dumps(expanded, sort_keys=True, separators=(",", ":"))


def snapshot_symbols(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> list[dict[str, Any]]:
    """Reconstruct symbols attached to the frame's immutable file facts."""

    files = snapshot_files(connection, snapshot_id)
    return symbols_for_files(connection, files)


def symbols_for_files(
    connection: sqlite3.Connection,
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Load immutable symbols for already-reconstructed files."""

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
    return _edges_for_relationships(connection, relationships)


def snapshot_relationship_edges_with_diagnostics(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> tuple[list[dict[str, Any]], ReconstructionDiagnostics]:
    """Reconstruct edges and expose the bounded-read evidence."""

    relationships, diagnostics = reconstruct_relationships_with_diagnostics(connection, snapshot_id)
    return _edges_for_relationships(connection, relationships), diagnostics


def _edges_for_relationships(
    connection: sqlite3.Connection,
    relationships: dict[int, int],
) -> list[dict[str, Any]]:
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
