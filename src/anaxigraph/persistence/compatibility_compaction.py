"""Compact redundant persistence projections and terminal work packets."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from anaxigraph.persistence.temporal_hashing import digest
from anaxigraph.persistence.temporal_reads import snapshot_relationship_edges
from anaxigraph.semantic_job_state import PATTERN_METADATA_RETENTION

COMPATIBILITY_TABLES = ("file_versions", "symbols", "relationships", "group_memberships")


def compact_terminal_semantic_job_metadata(connection: sqlite3.Connection) -> None:
    connection.execute(
        "UPDATE semantic_jobs SET metadata_json = '{}' "
        "WHERE (status = 'superseded' OR (status = 'completed' "
        "AND job_kind != 'pattern_assessment')) AND metadata_json != '{}'"
    )
    connection.execute(
        """
        UPDATE semantic_jobs SET metadata_json = json_object(
            'retention', ?, 'candidate', json_extract(metadata_json, '$.candidate'))
        WHERE status = 'completed' AND job_kind = 'pattern_assessment'
          AND metadata_json != '{}' AND json_valid(metadata_json)
          AND COALESCE(json_extract(metadata_json, '$.retention'), '') != ?
        """,
        (PATTERN_METADATA_RETENTION, PATTERN_METADATA_RETENTION),
    )


def prepare_semantic_claims_for_compaction(connection: sqlite3.Connection) -> None:
    """Make immutable file facts the required semantic-claim identity."""

    columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(semantic_claims)")}
    if (
        "file_fact_id" in columns
        and int(columns["file_fact_id"]["notnull"])
        and not int(columns["artifact_version_id"]["notnull"])
    ):
        return
    missing = int(
        connection.execute(
            "SELECT COUNT(*) FROM semantic_claims WHERE file_fact_id IS NULL"
        ).fetchone()[0]
    )
    if missing:
        raise RuntimeError(f"Cannot compact {missing} semantic claims without immutable facts")
    connection.execute(_CLAIMS_V9_SCHEMA)
    connection.execute(
        """
        INSERT INTO semantic_claims_v9(
            id, artifact_version_id, file_fact_id, claim_type, value_json, source, provider,
            model, executor_id, executor_model, prompt_version, created_at, confidence,
            supporting_evidence_json
        )
        SELECT id, NULL, file_fact_id, claim_type, value_json, source, provider, model,
               executor_id, executor_model, prompt_version, created_at, confidence,
               supporting_evidence_json
        FROM semantic_claims
        """
    )
    connection.execute("DROP TABLE semantic_claims")
    connection.execute("ALTER TABLE semantic_claims_v9 RENAME TO semantic_claims")


def backfill_relationship_coverage(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        """
        SELECT cm.id, cm.snapshot_id, r.source_artifact_id, r.target_artifact_id,
               r.target_external, r.relationship_type, r.source, r.confidence, r.evidence,
               r.source_line, r.weight, r.metadata_json
        FROM coverage_measurements cm
        JOIN relationships r ON r.id = cm.relationship_id
        WHERE cm.relationship_id IS NOT NULL AND cm.relationship_edge_id IS NULL
        """
    ).fetchall()
    edges_by_snapshot: dict[int, list[dict[str, Any]]] = {}
    updates: list[tuple[int, int]] = []
    for row in rows:
        snapshot_id = int(row["snapshot_id"])
        if snapshot_id not in edges_by_snapshot:
            edges_by_snapshot[snapshot_id] = snapshot_relationship_edges(connection, snapshot_id)
        match = next(
            (edge for edge in edges_by_snapshot[snapshot_id] if _same_edge(row, edge)), None
        )
        if match is None:
            raise RuntimeError(f"Coverage row {row['id']} has no canonical relationship edge")
        updates.append((int(match["id"]), int(row["id"])))
    connection.executemany(
        "UPDATE coverage_measurements SET relationship_edge_id = ? WHERE id = ?", updates
    )
    return len(updates)


def compact_compatibility_rows(
    connection: sqlite3.Connection,
    *,
    canonical_changed: bool = False,
) -> dict[str, int]:
    """Clear validated duplicate rows while retaining empty staging tables."""

    counts = {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in COMPATIBILITY_TABLES
    }
    connection.execute("UPDATE semantic_documents SET artifact_version_id = NULL")
    connection.execute("UPDATE semantic_jobs SET artifact_version_id = NULL")
    connection.execute("UPDATE semantic_scope_states SET artifact_version_id = NULL")
    connection.execute("UPDATE coverage_measurements SET relationship_id = NULL")
    connection.execute("DELETE FROM group_memberships")
    connection.execute("DELETE FROM symbols")
    connection.execute("DELETE FROM relationships")
    connection.execute("DELETE FROM file_versions")
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
        ("compatibility_compacted_at", datetime.now(UTC).isoformat()),
    )
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
        ("compatibility_compacted_rows", json.dumps(counts, sort_keys=True)),
    )
    existing_digest = connection.execute(
        "SELECT 1 FROM schema_meta WHERE key = 'canonical_content_digest'"
    ).fetchone()
    if sum(counts.values()) or canonical_changed or existing_digest is None:
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("canonical_content_digest", canonical_content_digest(connection)),
        )
    return counts


def canonical_content_digest(connection: sqlite3.Connection) -> str:
    tables = (
        "file_facts",
        "fact_symbols",
        "snapshot_file_changes",
        "relationship_sets",
        "relationship_edges",
        "snapshot_relationship_changes",
    )
    content = []
    for table in tables:
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        content.append((table, [tuple(row) for row in rows]))
    return digest(content)


def canonical_integrity_report(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'canonical_content_digest'"
    ).fetchone()
    expected = str(row[0]) if row is not None else None
    actual = canonical_content_digest(connection)
    return {
        "status": "exact" if expected == actual else "mismatch",
        "expected_digest": expected,
        "actual_digest": actual,
    }


def _same_edge(left: sqlite3.Row, right: dict[str, Any]) -> bool:
    fields = (
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
    return all(left[field] == right[field] for field in fields)


_CLAIMS_V9_SCHEMA = """
CREATE TABLE semantic_claims_v9 (
    id INTEGER PRIMARY KEY,
    artifact_version_id INTEGER,
    file_fact_id INTEGER NOT NULL REFERENCES file_facts(id) ON DELETE CASCADE,
    claim_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    executor_id TEXT,
    executor_model TEXT,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confidence REAL NOT NULL,
    supporting_evidence_json TEXT NOT NULL DEFAULT '[]'
)
"""
