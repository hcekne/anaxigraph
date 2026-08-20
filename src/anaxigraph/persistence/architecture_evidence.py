"""Canonical deterministic evidence for architecture evaluation."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_reads import (
    snapshot_files,
    snapshot_relationship_edges,
    symbols_for_files,
)


def architecture_evidence(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    files = snapshot_files(connection, snapshot_id)
    artifact_types = _artifact_types(connection, files)
    for file in files:
        file["snapshot_id"] = snapshot_id
        file["artifact_type"] = artifact_types[int(file["artifact_id"])]
    return (
        files,
        symbols_for_files(connection, files),
        snapshot_relationship_edges(connection, snapshot_id),
    )


def _artifact_types(
    connection: sqlite3.Connection,
    files: list[dict[str, Any]],
) -> dict[int, str]:
    ids = sorted(int(file["artifact_id"]) for file in files)
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"SELECT id, artifact_type FROM artifacts WHERE id IN ({placeholders})", ids
    ).fetchall()
    return {int(row["id"]): str(row["artifact_type"]) for row in rows}
