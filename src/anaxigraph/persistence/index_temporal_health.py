"""Snapshot-lineage and bounded-reconstruction health checks."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_hashing import digest
from anaxigraph.persistence.temporal_reconstruction import (
    CHECKPOINT_INTERVAL,
    canonical_state_hashes,
    reconstruct_files_with_diagnostics,
    reconstruct_relationships_with_diagnostics,
)


def refresh_canonical_content_digest(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
        ("canonical_content_digest", _canonical_content_digest(connection)),
    )


def canonical_integrity_report(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'canonical_content_digest'"
    ).fetchone()
    expected = str(row[0]) if row is not None else None
    actual = _canonical_content_digest(connection)
    return {
        "status": "exact" if expected == actual else "mismatch",
        "expected_digest": expected,
        "actual_digest": actual,
    }


def _canonical_content_digest(connection: sqlite3.Connection) -> str:
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


def lineage_report(connection: sqlite3.Connection) -> dict[str, Any]:
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


def reconstruction_report(connection: sqlite3.Connection) -> dict[str, Any]:
    snapshots = connection.execute("SELECT id FROM snapshots ORDER BY id").fetchall()
    checkpoints = {
        int(row["snapshot_id"]): dict(row)
        for row in connection.execute("SELECT * FROM snapshot_checkpoints").fetchall()
    }
    issues: list[dict[str, Any]] = []
    maximum_depth = 0
    for snapshot in snapshots:
        snapshot_id = int(snapshot["id"])
        files, file_diagnostics = reconstruct_files_with_diagnostics(connection, snapshot_id)
        relationships, relationship_diagnostics = reconstruct_relationships_with_diagnostics(
            connection,
            snapshot_id,
        )
        depth = max(
            file_diagnostics.traversed_deltas,
            relationship_diagnostics.traversed_deltas,
        )
        maximum_depth = max(maximum_depth, depth)
        checkpoint = checkpoints.get(snapshot_id)
        if checkpoint and not _checkpoint_matches(checkpoint, files, relationships):
            issues.append({"snapshot_id": snapshot_id, "problem": "checkpoint_content_mismatch"})
        if depth > CHECKPOINT_INTERVAL:
            issues.append({"snapshot_id": snapshot_id, "problem": "delta_budget_exceeded"})
    return {
        "status": "bounded" if not issues else "invalid",
        "delta_budget": CHECKPOINT_INTERVAL,
        "maximum_traversed_deltas": maximum_depth,
        "checkpoint_count": len(checkpoints),
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


def _checkpoint_matches(
    checkpoint: dict[str, Any],
    files: dict[int, dict[str, Any]],
    relationships: dict[int, int],
) -> bool:
    file_hash, relationship_hash = canonical_state_hashes(files, relationships)
    return (
        int(checkpoint["file_count"]) == len(files)
        and int(checkpoint["relationship_source_count"]) == len(relationships)
        and checkpoint["file_state_hash"] == file_hash
        and checkpoint["relationship_state_hash"] == relationship_hash
    )
