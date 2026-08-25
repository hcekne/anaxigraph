"""Incremental repository scanner and graph builder."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
from anaxigraph.scan_commit import commit_snapshot, refresh_existing_snapshot
from anaxigraph.scan_preparation import (
    analysis_counts,
    content_fingerprint,
    invalidation_counts,
    prepare_files,
)
from anaxigraph.scan_preparation import (
    analysis_signature as _analysis_signature,
)
from anaxigraph.scan_snapshot import RelationshipBuildResult, previous_analysis_records
from anaxigraph.storage import AnaxiIndex

ANALYSIS_VERSION = 4

ScanProgress = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]


class ScanCancelled(RuntimeError):
    """Raised at a safe checkpoint when an asynchronous scan is cancelled."""


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
        progress: ScanProgress | None = None,
        is_cancelled: CancelCheck | None = None,
    ) -> ScanStats:
        with self.database.scan_lock():
            return self._scan(
                repository,
                config_path=config_path,
                revision=revision,
                run_type=run_type,
                baseline_snapshot_id=baseline_snapshot_id,
                previous_revision=previous_revision,
                progress=progress,
                is_cancelled=is_cancelled,
            )

    def _scan(
        self,
        repository: str | Path,
        *,
        config_path: str | Path | None = None,
        revision: str | None = None,
        run_type: str = "scan",
        baseline_snapshot_id: int | None = None,
        previous_revision: str | None = None,
        progress: ScanProgress | None = None,
        is_cancelled: CancelCheck | None = None,
    ) -> ScanStats:
        started = time.monotonic()
        checkpoint = _scan_checkpoint(progress, is_cancelled)
        checkpoint("starting", 0, None, None)
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
            checkpoint("discovering", 0, None, None, run_id=run_id)
            signature = analysis_signature(config)
            discovered, previous, discovery, previous_snapshot_id = self._discover_frame(
                repository_id,
                root,
                config,
                revision=revision,
                baseline_snapshot_id=baseline_snapshot_id,
                previous_revision=previous_revision,
                signature=signature,
                progress=lambda completed, total, path: checkpoint(
                    "discovering", completed, total, path, run_id=run_id
                ),
            )
            checkpoint("fingerprinting", 0, len(discovered), None, run_id=run_id)
            fingerprint = content_fingerprint(
                discovered,
                config,
                git_metadata,
                analysis_version=ANALYSIS_VERSION,
                registry=self.registry,
            )
            existing_snapshot = self.database.snapshot_by_fingerprint(repository_id, fingerprint)
            if existing_snapshot:
                checkpoint("refreshing", 0, 1, None, run_id=run_id)
                return self._complete_unchanged_scan(
                    repository_id,
                    run_id,
                    existing_snapshot,
                    root,
                    config,
                    git_metadata,
                    signature,
                    revision,
                    discovery,
                    len(discovered),
                    started,
                    checkpoint,
                )
            checkpoint("analyzing", 0, len(discovered), None, run_id=run_id)
            prepared = prepare_files(
                discovered,
                previous,
                config,
                self.registry,
                analysis_version=ANALYSIS_VERSION,
                progress=lambda completed, total, path: checkpoint(
                    "analyzing", completed, total, path, run_id=run_id
                ),
            )
            checkpoint("invalidating", 0, len(prepared), None, run_id=run_id)
            apply_invalidation_plan(prepared, previous)
            checkpoint("git_history", 0, 1, None, run_id=run_id)
            git_changes = available_changes(root)
            persistence_steps = 7
            checkpoint("persisting", 0, persistence_steps, None, run_id=run_id)
            committed = commit_snapshot(
                self.database,
                repository_id=repository_id,
                root=root,
                config=config,
                git_metadata=git_metadata,
                fingerprint=fingerprint,
                signature=signature,
                revision=revision,
                previous_snapshot_id=previous_snapshot_id,
                prepared=prepared,
                git_changes=git_changes,
                progress=lambda completed: checkpoint(
                    "persisting", completed, persistence_steps, None, run_id=run_id
                ),
                analysis_version=ANALYSIS_VERSION,
            )
            analyzed, reused, errors = analysis_counts(prepared)
            duration = int((time.monotonic() - started) * 1_000)
            self.database.finish_run(
                run_id,
                snapshot_id=committed.snapshot_id,
                status="completed_with_errors" if errors else "completed",
                discovered=len(discovered),
                analyzed=analyzed,
                reused=reused,
                error_count=errors,
                metadata=_run_metadata(
                    discovery,
                    duration,
                    revision,
                    deleted=committed.deleted,
                    **_relationship_metadata(committed.relationships),
                    coverage_measurements=committed.coverage_count,
                    findings=committed.finding_count,
                    invalidation_reasons=invalidation_counts(prepared),
                ),
            )
            stats = ScanStats(
                repository_id=repository_id,
                snapshot_id=committed.snapshot_id,
                analysis_run_id=run_id,
                discovered=len(discovered),
                analyzed=analyzed,
                reused=reused,
                deleted=committed.deleted,
                relationships=committed.relationships.total,
                findings=committed.finding_count,
                duration_ms=duration,
            )
            checkpoint("complete", len(discovered), len(discovered), None, run_id=run_id)
            return stats
        except ScanCancelled:
            self.database.finish_run(
                run_id,
                snapshot_id=None,
                status="cancelled",
                error="Scan cancelled by operator",
            )
            raise
        except Exception as exc:
            self.database.finish_run(
                run_id,
                snapshot_id=None,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:4_000],
            )
            raise

    def _complete_unchanged_scan(
        self,
        repository_id: int,
        run_id: int,
        snapshot: dict[str, Any],
        root: Path,
        config: AnaxiGraphConfig,
        git_metadata: Any,
        signature: str,
        revision: str | None,
        discovery: DiscoveryResult,
        discovered: int,
        started: float,
        checkpoint: Callable[..., None],
    ) -> ScanStats:
        snapshot_id = int(snapshot["id"])
        counts = refresh_existing_snapshot(
            self.database,
            repository_id=repository_id,
            snapshot=snapshot,
            root=root,
            git_metadata=git_metadata,
            config=config,
            signature=signature,
            revision=revision,
            analysis_version=ANALYSIS_VERSION,
        )
        duration = int((time.monotonic() - started) * 1_000)
        self.database.finish_run(
            run_id,
            snapshot_id=snapshot_id,
            status="unchanged",
            discovered=discovered,
            reused=discovered,
            metadata=_run_metadata(discovery, duration, revision),
        )
        stats = ScanStats(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            analysis_run_id=run_id,
            discovered=discovered,
            analyzed=0,
            reused=discovered,
            deleted=0,
            relationships=counts["relationships"],
            findings=counts["findings"],
            duration_ms=duration,
        )
        checkpoint("complete", discovered, discovered, None, run_id=run_id)
        return stats

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
        progress: Callable[[int, int, str], None] | None = None,
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
            progress=progress,
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


def _scan_checkpoint(
    progress: ScanProgress | None,
    is_cancelled: CancelCheck | None,
) -> Callable[..., None]:
    def checkpoint(
        phase: str,
        completed: int,
        total: int | None,
        current_path: str | None,
        *,
        run_id: int | None = None,
    ) -> None:
        if phase != "complete" and is_cancelled is not None and is_cancelled():
            raise ScanCancelled("Scan cancelled by operator")
        if progress is not None:
            progress(
                {
                    "phase": phase,
                    "completed": completed,
                    "total": total,
                    "current_path": current_path,
                    "analysis_run_id": run_id,
                }
            )

    return checkpoint
