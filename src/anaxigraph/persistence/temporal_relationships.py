"""Immutable relationship sets and sparse per-snapshot source changes."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.persistence.temporal_hashing import digest, resolver_context_hash


def legacy_relationship_sets(
    connection: sqlite3.Connection,
    snapshot_id: int,
    repository_id: int,
    files: dict[int, dict[str, Any]],
    analysis_signature: str,
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
        )
        for source_id, values in grouped.items()
        if source_id in files
    }


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


def _upsert_relationship_set(
    connection: sqlite3.Connection,
    repository_id: int,
    source_fact_id: int,
    source_artifact_id: int,
    edges: list[dict[str, Any]],
    analysis_signature: str,
) -> int:
    content = [_edge_value(row) for row in edges]
    content_hash = digest(content)
    fact = connection.execute(
        "SELECT metadata_json, created_at FROM file_facts WHERE id = ?",
        (source_fact_id,),
    ).fetchone()
    resolver_hash = resolver_context_hash(fact["metadata_json"] if fact else "{}")
    set_key = digest([source_fact_id, resolver_hash, analysis_signature, content_hash])
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
    exists = connection.execute(
        "SELECT 1 FROM relationship_edges WHERE relationship_set_id = ? LIMIT 1",
        (set_id,),
    ).fetchone()
    if not exists:
        _insert_edges(connection, set_id, edges)
    return set_id


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
