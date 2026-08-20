"""Git-backed architecture history import with stable lifetime sampling."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner, analysis_signature
from anaxigraph.storage import AnaxiIndex


@dataclass(frozen=True, slots=True)
class HistoryImportResult:
    total_commits: int
    selected_commits: int
    imported_snapshots: int
    first_commit: str | None
    latest_commit: str | None
    current_snapshot_id: int
    work: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_commits": self.total_commits,
            "selected_commits": self.selected_commits,
            "imported_snapshots": self.imported_snapshots,
            "first_commit": self.first_commit,
            "latest_commit": self.latest_commit,
            "current_snapshot_id": self.current_snapshot_id,
            "work": self.work,
        }


def sampled_revisions(values: list[str], limit: int) -> list[str]:
    """Evenly sample a timeline while always retaining its first and last commits."""

    if limit < 1:
        return []
    if len(values) <= limit:
        return values[:]
    if limit == 1:
        return [values[-1]]
    indexes = {round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)}
    return [values[index] for index in sorted(indexes)]


def import_git_history(
    database: AnaxiIndex,
    repository: str | Path,
    *,
    config_path: str | Path | None = None,
    max_snapshots: int = 64,
    every_commit: bool = False,
    since: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    scanner: RepositoryScanner | None = None,
) -> HistoryImportResult:
    root = Path(repository).expanduser().resolve()
    scanner = scanner or RepositoryScanner(database)
    if not git.has_commits(root):
        current = scanner.scan(root, config_path=config_path, run_type="history_current")
        return HistoryImportResult(0, 0, 0, None, None, current.snapshot_id)

    complete_history = git.revisions(root, limit=None, since=since, oldest_first=True)
    config = load_config(root, Path(config_path) if config_path else None)
    repository_id = database.ensure_repository(
        path=root,
        name=config.project_name or root.name,
        git=git.metadata(root),
    )
    signature = analysis_signature(config)
    selected = (
        complete_history
        if every_commit
        else sampled_revisions(complete_history, max(1, max_snapshots))
    )
    baseline_snapshot_id, imported, work = _import_revisions(
        database,
        scanner,
        root,
        selected,
        repository_id=repository_id,
        signature=signature,
        config_path=config_path,
        progress=progress,
    )
    current = scanner.scan(
        root,
        config_path=config_path,
        run_type="history_current",
        baseline_snapshot_id=baseline_snapshot_id,
    )
    return HistoryImportResult(
        total_commits=len(complete_history),
        selected_commits=len(selected),
        imported_snapshots=imported,
        first_commit=complete_history[0] if complete_history else None,
        latest_commit=complete_history[-1] if complete_history else None,
        current_snapshot_id=current.snapshot_id,
        work=work,
    )


def _import_revisions(
    database: AnaxiIndex,
    scanner: RepositoryScanner,
    root: Path,
    selected: list[str],
    *,
    repository_id: int,
    signature: str,
    config_path: str | Path | None,
    progress: Callable[[int, int, str], None] | None,
) -> tuple[int | None, int, dict[str, Any]]:
    baseline_snapshot_id: int | None = None
    baseline_revision: str | None = None
    imported = 0
    work = _empty_work()
    for index, commit_sha in enumerate(selected, start=1):
        if progress:
            progress(index, len(selected), commit_sha)
        existing = database.commit_snapshot(repository_id, commit_sha, signature)
        if existing is not None:
            baseline_snapshot_id = int(existing["id"])
            baseline_revision = commit_sha
            imported += 1
            continue
        stats = scanner.scan(
            root,
            config_path=config_path,
            revision=commit_sha,
            run_type="history",
            baseline_snapshot_id=baseline_snapshot_id,
            previous_revision=baseline_revision,
        )
        baseline_snapshot_id = stats.snapshot_id
        baseline_revision = commit_sha
        _add_work(work, database, stats)
        imported += 1
    return baseline_snapshot_id, imported, work


def _empty_work() -> dict[str, Any]:
    return {
        "source_reads": 0,
        "analyzed_files": 0,
        "reused_analysis": 0,
        "carried_forward": 0,
        "relationship_sources_resolved": 0,
        "relationship_sources_reused": 0,
        "relationships_copied": 0,
        "invalidation_reasons": {},
    }


def _add_work(work: dict[str, Any], database: AnaxiIndex, stats: Any) -> None:
    with database.connect() as connection:
        run = connection.execute(
            "SELECT metadata_json FROM analysis_runs WHERE id = ?", (stats.analysis_run_id,)
        ).fetchone()
        files = connection.execute(
            "SELECT metadata_json FROM file_versions WHERE snapshot_id = ?", (stats.snapshot_id,)
        ).fetchall()
    metadata = json.loads(run["metadata_json"] or "{}") if run else {}
    for key in (
        "source_reads",
        "carried_forward",
        "relationship_sources_resolved",
        "relationship_sources_reused",
        "relationships_copied",
    ):
        work[key] += int(metadata.get(key) or 0)
    work["analyzed_files"] += stats.analyzed
    work["reused_analysis"] += stats.reused
    reasons = Counter(json.loads(row["metadata_json"])["invalidation_reason"] for row in files)
    total_reasons = Counter(work["invalidation_reasons"])
    total_reasons.update(reasons)
    work["invalidation_reasons"] = dict(sorted(total_reasons.items()))
