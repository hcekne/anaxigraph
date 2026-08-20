"""Orchestrate immutable facts and snapshot-delta persistence for schema 7."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from anaxigraph.persistence.temporal_files import (
    legacy_file_facts,
    persist_file_changes,
)
from anaxigraph.persistence.temporal_hashing import analysis_signature
from anaxigraph.persistence.temporal_reconstruction import (
    reconstruct_files,
    reconstruct_relationships,
    refresh_checkpoint_if_due,
)
from anaxigraph.persistence.temporal_relationships import (
    legacy_relationship_sets,
    persist_relationship_changes,
)
from anaxigraph.persistence.temporal_schema import (
    clear_temporal_facts,
    install_temporal_schema,
)


def migrate_legacy_temporal_facts(connection: sqlite3.Connection) -> dict[str, int]:
    """Convert a materialized schema-6 timeline into immutable facts and deltas."""

    install_temporal_schema(connection)
    clear_temporal_facts(connection)
    snapshots = connection.execute(
        """
        SELECT id, repository_id, metadata_json, analysis_timestamp
        FROM snapshots
        ORDER BY repository_id,
                 CASE snapshot_kind WHEN 'commit' THEN 0 ELSE 1 END,
                 COALESCE(commit_timestamp, analysis_timestamp), id
        """
    ).fetchall()
    prior_by_repository: dict[int, int | None] = {}
    sequence_by_repository: defaultdict[int, int] = defaultdict(int)
    for snapshot in snapshots:
        repository_id = int(snapshot["repository_id"])
        snapshot_id = int(snapshot["id"])
        base_snapshot_id = prior_by_repository.get(repository_id)
        _record_snapshot(
            connection,
            snapshot_id=snapshot_id,
            repository_id=repository_id,
            base_snapshot_id=base_snapshot_id,
            sequence=sequence_by_repository[repository_id],
            signature=analysis_signature(snapshot["metadata_json"]),
        )
        prior_by_repository[repository_id] = snapshot_id
        sequence_by_repository[repository_id] += 1
    return temporal_counts(connection)


def record_snapshot_facts(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    base_snapshot_id: int | None,
    signature: str | None = None,
) -> dict[str, int]:
    """Mirror one complete legacy frame into canonical immutable facts and deltas."""

    install_temporal_schema(connection)
    row = connection.execute(
        "SELECT repository_id, metadata_json FROM snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown snapshot: {snapshot_id}")
    repository_id = int(row["repository_id"])
    effective_signature = signature or analysis_signature(row["metadata_json"])
    _record_snapshot(
        connection,
        snapshot_id=snapshot_id,
        repository_id=repository_id,
        base_snapshot_id=base_snapshot_id,
        sequence=_next_sequence(
            connection,
            base_snapshot_id,
        ),
        signature=effective_signature,
    )
    return temporal_counts(connection)


def temporal_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "file_facts",
        "fact_symbols",
        "snapshot_file_changes",
        "relationship_sets",
        "relationship_edges",
        "snapshot_relationship_changes",
        "snapshot_checkpoints",
        "checkpoint_files",
        "checkpoint_relationships",
    )
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def _record_snapshot(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    repository_id: int,
    base_snapshot_id: int | None,
    sequence: int,
    signature: str,
) -> None:
    connection.execute(
        "UPDATE snapshots SET base_snapshot_id = ?, sequence = ? WHERE id = ?",
        (base_snapshot_id, sequence, snapshot_id),
    )
    previous_files = reconstruct_files(connection, base_snapshot_id)
    current_files = legacy_file_facts(connection, snapshot_id, signature)
    persist_file_changes(connection, snapshot_id, previous_files, current_files)
    previous_sets = reconstruct_relationships(connection, base_snapshot_id)
    current_sets = legacy_relationship_sets(
        connection,
        snapshot_id,
        repository_id,
        current_files,
        signature,
    )
    persist_relationship_changes(connection, snapshot_id, previous_sets, current_sets)
    refresh_checkpoint_if_due(connection, snapshot_id)


def _next_sequence(
    connection: sqlite3.Connection,
    base_snapshot_id: int | None,
) -> int:
    if base_snapshot_id is not None:
        row = connection.execute(
            "SELECT sequence FROM snapshots WHERE id = ?",
            (base_snapshot_id,),
        ).fetchone()
        if row is not None:
            return int(row[0]) + 1
    return 0
