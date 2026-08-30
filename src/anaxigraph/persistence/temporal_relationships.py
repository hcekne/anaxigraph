"""Immutable relationship sets and sparse per-snapshot source changes."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.persistence.temporal_hashing import (
    analysis_signature as stored_analysis_signature,
)
from anaxigraph.persistence.temporal_hashing import (
    digest,
    resolver_context_hash,
)
from anaxigraph.persistence.temporal_reconstruction import (
    reconstruct_relationships,
    refresh_checkpoint_if_due,
)


def legacy_relationship_sets(
    connection: sqlite3.Connection,
    snapshot_id: int,
    repository_id: int,
    files: dict[int, dict[str, Any]],
    analysis_signature: str,
    *,
    set_cache: dict[str, int] | None = None,
) -> dict[int, int]:
    rows = connection.execute(
        """
        SELECT * FROM relationships
        WHERE snapshot_id = ? ORDER BY source_artifact_id, id
        """,
        (snapshot_id,),
    ).fetchall()
    grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["source_artifact_id"])].append(dict(row))
    return {
        source_id: _upsert_relationship_set(
            connection,
            repository_id,
            files[source_id]["file_fact_id"],
            source_id,
            values,
            analysis_signature,
            cache=set_cache,
        )
        for source_id, values in grouped.items()
        if source_id in files
    }


def record_canonical_relationships(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    base_snapshot_id: int | None,
    current_files: dict[int, dict[str, Any]],
    changed_sources: set[int],
    edges_by_source: dict[int, list[dict[str, Any]]],
) -> None:
    """Persist resolved edges directly as immutable sets and sparse source changes."""

    snapshot = connection.execute(
        "SELECT repository_id, metadata_json FROM snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if snapshot is None:
        raise ValueError(f"Unknown snapshot: {snapshot_id}")
    previous = reconstruct_relationships(connection, base_snapshot_id)
    current = {
        source_id: set_id
        for source_id, set_id in previous.items()
        if source_id in current_files and source_id not in changed_sources
    }
    for source_id, edges in edges_by_source.items():
        if edges and source_id in current_files:
            current[source_id] = _upsert_relationship_set(
                connection,
                int(snapshot["repository_id"]),
                int(current_files[source_id]["file_fact_id"]),
                source_id,
                edges,
                stored_analysis_signature(snapshot["metadata_json"]),
            )
    persist_relationship_changes(connection, snapshot_id, previous, current)
    refresh_checkpoint_if_due(connection, snapshot_id)


def persist_relationship_changes(
    connection: sqlite3.Connection,
    snapshot_id: int,
    previous: dict[int, int],
    current: dict[int, int],
) -> None:
    connection.execute(
        "DELETE FROM snapshot_relationship_changes WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    for source_id in sorted(set(previous) | set(current)):
        if previous.get(source_id) == current.get(source_id):
            continue
        connection.execute(
            """
            INSERT INTO snapshot_relationship_changes(
                snapshot_id, source_artifact_id, change_kind, relationship_set_id
            ) VALUES (?, ?, ?, ?)
            """,
            (
                snapshot_id,
                source_id,
                "set" if source_id in current else "retract",
                current.get(source_id),
            ),
        )


def compact_duplicate_relationship_sets(connection: sqlite3.Connection) -> int:
    """Reuse identical resolved edge sets across source-only fact changes."""

    for row in connection.execute("SELECT id FROM relationship_sets ORDER BY id").fetchall():
        set_id = int(row["id"])
        edges = [
            dict(edge)
            for edge in connection.execute(
                "SELECT * FROM relationship_edges WHERE relationship_set_id = ?",
                (set_id,),
            ).fetchall()
        ]
        connection.execute(
            "UPDATE relationship_sets SET content_hash = ? WHERE id = ?",
            (_relationship_content_hash(edges), set_id),
        )
    rows = connection.execute(
        """
        SELECT repository_id, source_artifact_id, resolver_context_hash,
               analysis_signature, content_hash, MIN(id) AS canonical_id,
               GROUP_CONCAT(id) AS ids
        FROM relationship_sets
        GROUP BY repository_id, source_artifact_id, resolver_context_hash,
                 analysis_signature, content_hash
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    removed = 0
    for row in rows:
        canonical_id = int(row["canonical_id"])
        duplicate_ids = [
            int(value) for value in str(row["ids"]).split(",") if int(value) != canonical_id
        ]
        canonical_edges = _edges_by_value(connection, canonical_id)
        for duplicate_id in duplicate_ids:
            _move_relationship_references(
                connection,
                duplicate_id=duplicate_id,
                canonical_id=canonical_id,
                canonical_edges=canonical_edges,
            )
            connection.execute("DELETE FROM relationship_sets WHERE id = ?", (duplicate_id,))
            removed += 1
    for row in connection.execute("SELECT * FROM relationship_sets ORDER BY id").fetchall():
        connection.execute(
            "UPDATE relationship_sets SET set_key = ? WHERE id = ?",
            (_relationship_set_key(row), int(row["id"])),
        )
    return removed


def _upsert_relationship_set(
    connection: sqlite3.Connection,
    repository_id: int,
    source_fact_id: int,
    source_artifact_id: int,
    edges: list[dict[str, Any]],
    analysis_signature: str,
    *,
    cache: dict[str, int] | None = None,
) -> int:
    content_hash = _relationship_content_hash(edges)
    fact = connection.execute(
        "SELECT metadata_json, created_at FROM file_facts WHERE id = ?",
        (source_fact_id,),
    ).fetchone()
    resolver_hash = resolver_context_hash(fact["metadata_json"] if fact else "{}")
    set_key = digest([source_artifact_id, resolver_hash, analysis_signature, content_hash])
    if cache is not None and set_key in cache:
        return cache[set_key]
    connection.execute(
        """
        INSERT OR IGNORE INTO relationship_sets(
            repository_id, source_artifact_id, source_file_fact_id, set_key,
            resolver_context_hash, analysis_signature, content_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repository_id,
            source_artifact_id,
            source_fact_id,
            set_key,
            resolver_hash,
            analysis_signature,
            content_hash,
            fact["created_at"] if fact else "unknown",
        ),
    )
    row = connection.execute(
        "SELECT id FROM relationship_sets WHERE set_key = ?",
        (set_key,),
    ).fetchone()
    assert row is not None
    set_id = int(row["id"])
    if not connection.execute(
        "SELECT 1 FROM relationship_edges WHERE relationship_set_id = ? LIMIT 1", (set_id,)
    ).fetchone():
        _insert_edges(connection, set_id, edges)
    if cache is not None:
        cache[set_key] = set_id
    return set_id


def _move_relationship_references(
    connection: sqlite3.Connection,
    *,
    duplicate_id: int,
    canonical_id: int,
    canonical_edges: dict[tuple[Any, ...], int],
) -> None:
    for edge in connection.execute(
        "SELECT * FROM relationship_edges WHERE relationship_set_id = ?",
        (duplicate_id,),
    ).fetchall():
        canonical_edge_id = canonical_edges.get(_edge_value(dict(edge)))
        if canonical_edge_id is None:
            raise RuntimeError("Duplicate relationship sets contain different edges")
        connection.execute(
            "UPDATE coverage_measurements SET relationship_edge_id = ? WHERE relationship_edge_id = ?",
            (canonical_edge_id, int(edge["id"])),
        )
    for table in ("snapshot_relationship_changes", "checkpoint_relationships"):
        connection.execute(
            f"UPDATE {table} SET relationship_set_id = ? WHERE relationship_set_id = ?",
            (canonical_id, duplicate_id),
        )


def _edges_by_value(connection: sqlite3.Connection, set_id: int) -> dict[tuple[Any, ...], int]:
    return {
        _edge_value(dict(row)): int(row["id"])
        for row in connection.execute(
            "SELECT * FROM relationship_edges WHERE relationship_set_id = ?",
            (set_id,),
        ).fetchall()
    }


def _relationship_set_key(row: sqlite3.Row) -> str:
    return digest(
        [
            row["source_artifact_id"],
            row["resolver_context_hash"],
            row["analysis_signature"],
            row["content_hash"],
        ]
    )


def _relationship_content_hash(edges: list[dict[str, Any]]) -> str:
    return digest(sorted((_edge_value(row) for row in edges), key=repr))


def _insert_edges(
    connection: sqlite3.Connection,
    set_id: int,
    edges: list[dict[str, Any]],
) -> None:
    connection.executemany(
        """
        INSERT INTO relationship_edges(
            relationship_set_id, target_artifact_id, target_external,
            relationship_type, source, confidence, evidence, source_line,
            weight, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(set_id, *_edge_value(row)) for row in edges],
    )


def _edge_value(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["target_artifact_id"],
        row["target_external"],
        row["relationship_type"],
        row["source"],
        row["confidence"],
        row["evidence"],
        row["source_line"],
        row["weight"],
        row["metadata_json"],
    )
