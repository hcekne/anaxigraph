"""Canonical deterministic evidence for architecture evaluation."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_reads import (
    artifact_types_for_files,
    snapshot_files,
    snapshot_relationship_edges,
    symbols_for_files,
)


def architecture_evidence(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    files = snapshot_files(connection, snapshot_id)
    artifact_types = artifact_types_for_files(connection, files)
    for file in files:
        file["snapshot_id"] = snapshot_id
        file["artifact_type"] = artifact_types[int(file["artifact_id"])]
    return (
        files,
        symbols_for_files(connection, files),
        snapshot_relationship_edges(connection, snapshot_id),
    )
