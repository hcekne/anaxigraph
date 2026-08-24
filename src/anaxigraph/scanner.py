"""Incremental repository scanner and graph builder."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from anaxigraph import __version__
from anaxigraph.analyzers import AnalyzerRegistry, builtin_registry
from anaxigraph.config import AnaxiGraphConfig, load_config
from anaxigraph.history_discovery import (
    DiscoveredFile,
    DiscoveryResult,
    apply_invalidation_plan,
    available_changes,
    discover_files,
    repository_metadata,
)
from anaxigraph.models import ScanStats
from anaxigraph.scan_persistence import (
    ingest_git_history,
    insert_snapshot,
    insert_versions,
    upsert_artifacts,
    upsert_groups,
)
from anaxigraph.scan_preparation import (
    analysis_counts,
    content_fingerprint,
    invalidation_counts,
    prepare_files,
)
from anaxigraph.scan_preparation import (
    analysis_signature as _analysis_signature,
)
from anaxigraph.scan_snapshot import (
    RelationshipBuildResult,
    build_snapshot_graph,
    clear_snapshot_staging,
    previous_analysis_records,
    refresh_snapshot_intelligence,
    snapshot_artifacts,
    snapshot_counts,
)
from anaxigraph.storage import AnaxiIndex, utc_now
from anaxigraph.understanding import SemanticEngine

ANALYSIS_VERSION = 4


class RepositoryScanner:
    def __init__(
        self,
        database: AnaxiIndex,
        *,
        registry: AnalyzerRegistry | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or builtin_registry()

    def scan(
        self,
        repository: str | Path,
        *,
        config_path: str | Path | None = None,
        revision: str | None = None,
        run_type: str = "scan",
        baseline_snapshot_id: int | None = None,
        previous_revision: str | None = None,
    ) -> ScanStats:
        started = time.monotonic()
        root = Path(repository).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Repository does not exist or is not a directory: {root}")
        config = load_config(root, Path(config_path) if config_path else None)
        git_metadata = repository_metadata(root, revision)
        repository_id = self.database.ensure_repository(
            path=root,
            name=config.project_name or root.name,
            git=git_metadata,
        )
        run_id = self.database.start_run(repository_id, run_type)
        try:
            signature = analysis_signature(config)
            discovered, previous, discovery, previous_snapshot_id = self._discover_frame(
                repository_id,
                root,
                config,
                revision=revision,
                baseline_snapshot_id=baseline_snapshot_id,
                previous_revision=previous_revision,
                signature=signature,
            )
            fingerprint = content_fingerprint(
                discovered,
                config,
                git_metadata,
                analysis_version=ANALYSIS_VERSION,
            )
            existing_snapshot = self.database.snapshot_by_fingerprint(repository_id, fingerprint)
            if existing_snapshot:
                existing_id = int(existing_snapshot["id"])
                snapshot_metadata = json.loads(existing_snapshot["metadata_json"] or "{}")
                snapshot_metadata.update(
                    {
                        "anaxigraph_version": __version__,
                        "analysis_version": ANALYSIS_VERSION,
                        "analysis_signature": signature,
                        "config_path": str(config.config_path) if config.config_path else None,
                    }
                )
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE snapshots SET metadata_json = ? WHERE id = ?",
                        (json.dumps(snapshot_metadata, sort_keys=True), existing_id),
                    )
                if revision is None:
                    self._refresh_existing_snapshot(
                        repository_id, existing_id, root, git_metadata, config
                    )
                with self.database.connect() as connection:
                    counts = snapshot_counts(connection, existing_id)
                duration = int((time.monotonic() - started) * 1_000)
                self.database.finish_run(
                    run_id,
                    snapshot_id=existing_id,
                    status="unchanged",
                    discovered=len(discovered),
                    reused=len(discovered),
                    metadata=_run_metadata(discovery, duration, revision),
                )
                stats = ScanStats(
                    repository_id=repository_id,
                    snapshot_id=existing_id,
                    analysis_run_id=run_id,
                    discovered=len(discovered),
                    analyzed=0,
                    reused=len(discovered),
                    deleted=0,
                    relationships=counts["relationships"],
                    findings=counts["findings"],
                    duration_ms=duration,
                )
                if revision is None and config.semantic.enabled:
                    SemanticEngine(self.database).plan(repository_id, root, config)
                return stats

            prepared = prepare_files(
                discovered,
                previous,
                config,
                self.registry,
                analysis_version=ANALYSIS_VERSION,
            )
            apply_invalidation_plan(prepared, previous)
            git_changes = available_changes(root)
            with self.database.transaction() as connection:
                snapshot_id = insert_snapshot(
                    connection,
                    repository_id=repository_id,
                    git_metadata=git_metadata,
                    fingerprint=fingerprint,
                    revision=revision,
                    config=config,
                    analysis_version=ANALYSIS_VERSION,
                    signature=signature,
                )
                artifacts, deleted = upsert_artifacts(
                    connection,
                    repository_id=repository_id,
                    prepared=prepared,
                    commit_sha=git_metadata.commit_sha,
                )
                insert_versions(
                    connection,
                    snapshot_id=snapshot_id,
                    prepared=prepared,
                    artifacts=artifacts,
                    config=config,
                    analysis_version=ANALYSIS_VERSION,
                )
                relationship_build = build_snapshot_graph(
                    connection,
                    snapshot_id=snapshot_id,
                    base_snapshot_id=previous_snapshot_id,
                    prepared=prepared,
                    artifacts=artifacts,
                    config=config,
                )
                relationship_count = relationship_build.total
                upsert_groups(
                    connection,
                    repository_id=repository_id,
                    config=config,
                )
                ingest_git_history(
                    connection,
                    repository_id=repository_id,
                    changes=git_changes,
                )
                findings, coverage_count = refresh_snapshot_intelligence(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    config=config,
                    manage_finding_lifecycle=revision is None,
                    root=root if revision is None else None,
                    artifacts=artifacts,
                )
                if revision is None:
                    connection.execute(
                        "UPDATE repositories SET current_snapshot_id = ?, updated_at = ? WHERE id = ?",
                        (snapshot_id, utc_now(), repository_id),
                    )
                clear_snapshot_staging(connection)

            analyzed, reused, errors = analysis_counts(prepared)
            duration = int((time.monotonic() - started) * 1_000)
            self.database.finish_run(
                run_id,
                snapshot_id=snapshot_id,
                status="completed_with_errors" if errors else "completed",
                discovered=len(discovered),
                analyzed=analyzed,
                reused=reused,
                error_count=errors,
                metadata=_run_metadata(
                    discovery,
                    duration,
                    revision,
                    deleted=deleted,
                    **_relationship_metadata(relationship_build),
                    coverage_measurements=coverage_count,
                    findings=len(findings),
                    invalidation_reasons=invalidation_counts(prepared),
                ),
            )
            stats = ScanStats(
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                analysis_run_id=run_id,
                discovered=len(discovered),
                analyzed=analyzed,
                reused=reused,
                deleted=deleted,
                relationships=relationship_count,
                findings=len(findings),
                duration_ms=duration,
            )
            if revision is None and config.semantic.enabled:
                SemanticEngine(self.database).plan(repository_id, root, config)
            return stats
        except Exception as exc:
            self.database.finish_run(
                run_id,
                snapshot_id=None,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:4_000],
            )
            raise

    def _refresh_existing_snapshot(
        self,
        repository_id: int,
        snapshot_id: int,
        root: Path,
        git_metadata: Any,
        config: AnaxiGraphConfig,
    ) -> None:
        git_changes = available_changes(root)
        self.database.set_current_snapshot(repository_id, snapshot_id)
        with self.database.transaction() as connection:
            ingest_git_history(
                connection,
                repository_id=repository_id,
                changes=git_changes,
            )
            connection.execute("DELETE FROM metrics WHERE snapshot_id = ?", (snapshot_id,))
            connection.execute(
                "DELETE FROM coverage_measurements WHERE snapshot_id = ?", (snapshot_id,)
            )
            artifacts = snapshot_artifacts(connection, snapshot_id)
            refresh_snapshot_intelligence(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                manage_finding_lifecycle=True,
                root=root,
                config=config,
                artifacts=artifacts,
            )
            connection.execute(
                """
                UPDATE snapshots SET snapshot_kind = 'working_tree', dirty = ?,
                    branch = ?, analysis_timestamp = ? WHERE id = ?
                """,
                (int(git_metadata.dirty), git_metadata.branch, utc_now(), snapshot_id),
            )

    def _discover_frame(
        self,
        repository_id: int,
        root: Path,
        config: AnaxiGraphConfig,
        *,
        revision: str | None,
        baseline_snapshot_id: int | None,
        previous_revision: str | None,
        signature: str,
    ) -> tuple[
        list[DiscoveredFile],
        dict[str, dict[str, Any]],
        DiscoveryResult,
        int | None,
    ]:
        latest = self.database.latest_snapshot(repository_id)
        previous_snapshot_id = (
            baseline_snapshot_id
            if baseline_snapshot_id is not None or revision is not None
            else (int(latest["id"]) if latest else None)
        )
        with self.database.connect() as connection:
            previous = previous_analysis_records(connection, previous_snapshot_id)
        discovery = discover_files(
            root,
            config,
            revision=revision,
            previous_revision=previous_revision,
            previous=previous,
            analysis_version=ANALYSIS_VERSION,
            allow_carry=self._snapshot_signature(previous_snapshot_id) == signature,
        )
        return list(discovery.files), previous, discovery, previous_snapshot_id

    def _snapshot_signature(self, snapshot_id: int | None) -> str | None:
        if snapshot_id is None:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        metadata = json.loads(row["metadata_json"] or "{}") if row else {}
        return metadata.get("analysis_signature")


def _relationship_metadata(result: RelationshipBuildResult) -> dict[str, int]:
    return {
        "relationships": result.total,
        "relationships_copied": result.copied,
        "relationship_sources_resolved": result.resolved_sources,
        "relationship_sources_reused": result.reused_sources,
    }


def _run_metadata(
    discovery: DiscoveryResult,
    duration: int,
    revision: str | None,
    **values: Any,
) -> dict[str, Any]:
    return {
        "duration_ms": duration,
        "revision": revision,
        "source_reads": discovery.source_reads,
        "carried_forward": discovery.carried_forward,
        **values,
    }


def analysis_signature(config: AnaxiGraphConfig) -> str:
    return _analysis_signature(config, analysis_version=ANALYSIS_VERSION)
