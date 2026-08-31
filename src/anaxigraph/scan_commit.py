"""Atomic persistence for a prepared structural scan frame."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anaxigraph import __version__
from anaxigraph.clock import utc_now
from anaxigraph.history_discovery import available_changes
from anaxigraph.persistence.search_read import refresh_search_projection
from anaxigraph.scan_persistence import (
    ingest_git_history,
    insert_file_facts,
    insert_snapshot,
    upsert_artifacts,
    upsert_groups,
)
from anaxigraph.scan_snapshot import (
    RelationshipBuildResult,
    build_snapshot_graph,
    refresh_snapshot_intelligence,
    snapshot_artifacts,
    snapshot_counts,
)

PersistProgress = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class SnapshotCommit:
    snapshot_id: int
    deleted: int
    relationships: RelationshipBuildResult
    finding_count: int
    coverage_count: int


def commit_snapshot(
    database: Any,
    *,
    repository_id: int,
    root: Path,
    config: Any,
    git_metadata: Any,
    fingerprint: str,
    signature: str,
    revision: str | None,
    previous_snapshot_id: int | None,
    prepared: list[Any],
    git_changes: list[Any],
    progress: PersistProgress,
    analysis_version: int,
) -> SnapshotCommit:
    with database.transaction() as connection:
        snapshot_id, artifacts, deleted = _persist_files(
            connection,
            repository_id,
            config,
            git_metadata,
            fingerprint,
            signature,
            revision,
            previous_snapshot_id,
            prepared,
            progress,
            analysis_version,
        )
        relationships = build_snapshot_graph(
            connection,
            snapshot_id=snapshot_id,
            base_snapshot_id=previous_snapshot_id,
            prepared=prepared,
            artifacts=artifacts,
            config=config,
        )
        findings, coverage_count = _finish_snapshot(
            connection,
            repository_id,
            snapshot_id,
            root,
            config,
            revision,
            artifacts,
            git_changes,
            progress,
        )
    return SnapshotCommit(snapshot_id, deleted, relationships, len(findings), coverage_count)


def refresh_existing_snapshot(
    database: Any,
    *,
    repository_id: int,
    snapshot: dict[str, Any],
    root: Path,
    git_metadata: Any,
    config: Any,
    signature: str,
    revision: str | None,
    analysis_version: int,
) -> dict[str, int]:
    snapshot_id = int(snapshot["id"])
    metadata = json.loads(snapshot["metadata_json"] or "{}")
    metadata.update(
        {
            "anaxigraph_version": __version__,
            "analysis_version": analysis_version,
            "analysis_signature": signature,
            "config_path": str(config.config_path) if config.config_path else None,
            "working_tree_fingerprint": git_metadata.working_tree_fingerprint,
        }
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE snapshots SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata, sort_keys=True), snapshot_id),
        )
    if revision is None:
        _refresh_current_intelligence(
            database, repository_id, snapshot_id, root, git_metadata, config
        )
    else:
        refresh_historical_snapshot_intelligence(
            database,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            config=config,
        )
    with database.connect() as connection:
        return snapshot_counts(connection, snapshot_id)


def _persist_files(
    connection: Any,
    repository_id: int,
    config: Any,
    git_metadata: Any,
    fingerprint: str,
    signature: str,
    revision: str | None,
    previous_snapshot_id: int | None,
    prepared: list[Any],
    progress: PersistProgress,
    analysis_version: int,
) -> tuple[int, dict[str, int], int]:
    snapshot_id = insert_snapshot(
        connection,
        repository_id=repository_id,
        git_metadata=git_metadata,
        fingerprint=fingerprint,
        revision=revision,
        config=config,
        analysis_version=analysis_version,
        signature=signature,
    )
    progress(1)
    artifacts, deleted = upsert_artifacts(
        connection,
        repository_id=repository_id,
        prepared=prepared,
        commit_sha=git_metadata.commit_sha,
    )
    progress(2)
    insert_file_facts(
        connection,
        snapshot_id=snapshot_id,
        base_snapshot_id=previous_snapshot_id,
        prepared=prepared,
        artifacts=artifacts,
        config=config,
        analysis_version=analysis_version,
        signature=signature,
    )
    progress(3)
    return snapshot_id, artifacts, deleted


def _finish_snapshot(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    root: Path,
    config: Any,
    revision: str | None,
    artifacts: dict[str, int],
    git_changes: list[Any],
    progress: PersistProgress,
) -> tuple[list[Any], int]:
    progress(4)
    upsert_groups(connection, repository_id=repository_id, config=config)
    progress(5)
    ingest_git_history(connection, repository_id=repository_id, changes=git_changes)
    progress(6)
    findings, coverage_count = refresh_snapshot_intelligence(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        config=config,
        manage_finding_lifecycle=revision is None,
        root=root if revision is None else None,
        artifacts=artifacts,
    )
    progress(7)
    if revision is None:
        connection.execute(
            "UPDATE repositories SET current_snapshot_id = ?, updated_at = ? WHERE id = ?",
            (snapshot_id, utc_now(), repository_id),
        )
        refresh_search_projection(connection, repository_id, snapshot_id, force=True)
    return findings, coverage_count


def _refresh_current_intelligence(
    database: Any,
    repository_id: int,
    snapshot_id: int,
    root: Path,
    git_metadata: Any,
    config: Any,
) -> None:
    database.set_current_snapshot(repository_id, snapshot_id)
    with database.transaction() as connection:
        ingest_git_history(
            connection,
            repository_id=repository_id,
            changes=available_changes(root),
        )
        connection.execute("DELETE FROM metrics WHERE snapshot_id = ?", (snapshot_id,))
        connection.execute(
            "DELETE FROM coverage_measurements WHERE snapshot_id = ?", (snapshot_id,)
        )
        refresh_snapshot_intelligence(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            manage_finding_lifecycle=True,
            root=root,
            config=config,
            artifacts=snapshot_artifacts(connection, snapshot_id),
        )
        connection.execute(
            """
            UPDATE snapshots SET snapshot_kind = 'working_tree', dirty = ?,
                branch = ?, analysis_timestamp = ? WHERE id = ?
            """,
            (int(git_metadata.dirty), git_metadata.branch, utc_now(), snapshot_id),
        )
        refresh_search_projection(connection, repository_id, snapshot_id, force=True)


def refresh_historical_snapshot_intelligence(
    database: Any,
    *,
    repository_id: int,
    snapshot_id: int,
    config: Any,
) -> None:
    """Refresh derived findings for a retained frame without changing current state."""

    with database.transaction() as connection:
        connection.execute("DELETE FROM metrics WHERE snapshot_id = ?", (snapshot_id,))
        connection.execute("DELETE FROM finding_occurrences WHERE snapshot_id = ?", (snapshot_id,))
        refresh_snapshot_intelligence(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            manage_finding_lifecycle=False,
            root=None,
            config=config,
            artifacts=snapshot_artifacts(connection, snapshot_id),
        )
