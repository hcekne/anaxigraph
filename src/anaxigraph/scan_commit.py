"""Atomic persistence for a prepared structural scan frame."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anaxigraph import __version__
from anaxigraph.clock import utc_now
from anaxigraph.config import load_config
from anaxigraph.history_discovery import available_changes
from anaxigraph.knowledge_sync import clear_knowledge_cache, refresh_metrics
from anaxigraph.persistence.current_retention import retain_current_index
from anaxigraph.persistence.search_read import refresh_search_projection
from anaxigraph.persistence.semantic_state_carry import carry_compatible_states
from anaxigraph.persistence.temporal_cache_reindex import reindex_identical_source
from anaxigraph.portable_record import load_record
from anaxigraph.scan_persistence import (
    ingest_git_history,
    insert_file_facts,
    insert_snapshot,
    scan_consistency_metadata,
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


def complete_current_scan(
    database: Any, stats: Any, root: Path, config_path: Any, revision: Any, run_type: str
) -> None:
    if revision is not None:
        return
    root = root.expanduser().resolve()
    config = load_config(root, Path(config_path) if config_path else None)
    load_record(database, stats.repository_id, root, config=config, after_scan=True)
    if run_type == "history_current":
        with database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key,value) VALUES (?, 'true')",
                (f"history-opt-in:{stats.repository_id}",),
            )
    retain_current_index(database, stats.repository_id, config.storage)


def prepare_repository_cache(
    database: Any, root: Path, config: Any, metadata: Any, revision: Any
) -> int:
    database.storage_policy = config.storage
    repository_id = database.ensure_repository(
        path=root, name=config.project_name or root.name, git=metadata
    )
    if revision is None:
        load_record(database, repository_id, root, config=config)
    return repository_id


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
        clear_knowledge_cache(connection)
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
        graph_frame = (connection, repository_id, snapshot_id, previous_snapshot_id)
        relationships = _current_relationships(*graph_frame, prepared, artifacts, config)
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
    database.finish_cache_maintenance()
    return SnapshotCommit(snapshot_id, deleted, relationships, len(findings), coverage_count)


def _current_relationships(
    connection, repository_id, snapshot_id, previous_snapshot_id, prepared, artifacts, config
):
    result = build_snapshot_graph(
        connection,
        snapshot_id=snapshot_id,
        base_snapshot_id=previous_snapshot_id,
        prepared=prepared,
        artifacts=artifacts,
        config=config,
    )
    reindex_identical_source(
        connection, repository_id, snapshot_id, detailed=config.storage.detailed_history
    )
    carry_compatible_states(connection, repository_id, snapshot_id, previous_snapshot_id, config)
    return result


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
    metadata.pop("scan_consistency", None)
    metadata.update(
        {
            "anaxigraph_version": __version__,
            "analysis_version": analysis_version,
            "analysis_signature": signature,
            "config_path": str(config.config_path) if config.config_path else None,
            "working_tree_fingerprint": git_metadata.working_tree_fingerprint,
            "verified_commit_sha": git_metadata.commit_sha,
            **scan_consistency_metadata(git_metadata),
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
    if revision is not None:
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES (?, 'true')",
            (f"history-opt-in:{repository_id}",),
        )
    head = connection.execute(
        "SELECT commit_sha FROM snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()[0]
    ingest_git_history(
        connection,
        repository_id=repository_id,
        changes=git_changes,
        observed_head=head,
        detailed=config.storage.detailed_history,
    )
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
        refresh_search_projection(connection, repository_id, snapshot_id)
    _defer_knowledge(connection, snapshot_id)
    return findings, coverage_count


def _defer_knowledge(connection, snapshot_id):
    connection.executemany(
        "INSERT OR REPLACE INTO schema_meta VALUES (?,?)",
        (("graph-import-pending", str(snapshot_id)), ("index-compaction-pending", "true")),
    )


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
            observed_head=git_metadata.commit_sha,
            detailed=config.storage.detailed_history,
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
        refresh_metrics(connection, snapshot_id, repository_id)
        connection.execute(
            """
            UPDATE snapshots SET snapshot_kind = 'working_tree', dirty = ?,
                branch = ?, analysis_timestamp = ? WHERE id = ?
            """,
            (int(git_metadata.dirty), git_metadata.branch, utc_now(), snapshot_id),
        )
        refresh_search_projection(connection, repository_id, snapshot_id)


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
