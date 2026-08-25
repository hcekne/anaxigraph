"""Git-backed architecture history import with stable lifetime sampling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.config import load_config
from anaxigraph.history_frames import materialize_revision
from anaxigraph.languages import detect_language
from anaxigraph.scanner import RepositoryScanner, analysis_signature


class HistoryImportCancelled(RuntimeError):
    """Raised between atomic frames when a durable history job requests cancellation."""


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


@dataclass(frozen=True, slots=True)
class _HistoryPlan:
    complete: list[str]
    selected: list[str]
    repository_id: int
    signature: str
    summaries: dict[str, git.RevisionSummary]
    config: Any


@dataclass(frozen=True, slots=True)
class _ImportContext:
    database: Any
    scanner: RepositoryScanner
    root: Path
    plan: _HistoryPlan
    config_path: str | Path | None
    progress: Callable[[int, int, str], None] | None
    job_progress: Callable[[dict[str, Any]], None] | None
    should_cancel: Callable[[], bool] | None


@dataclass(slots=True)
class _FrameState:
    baseline_snapshot_id: int | None = None
    baseline_revision: str | None = None
    imported: int = 0
    work: dict[str, Any] = field(default_factory=dict)


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
    database: Any,
    repository: str | Path,
    *,
    config_path: str | Path | None = None,
    max_snapshots: int | str = "auto",
    every_commit: bool = False,
    since: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    job_progress: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    scanner: RepositoryScanner | None = None,
) -> HistoryImportResult:
    root = Path(repository).expanduser().resolve()
    scanner = scanner or RepositoryScanner(database)
    if not git.has_commits(root):
        current = scanner.scan(root, config_path=config_path, run_type="history_current")
        return HistoryImportResult(0, 0, 0, None, None, current.snapshot_id)

    plan = _history_plan(
        database,
        root,
        config_path=config_path,
        max_snapshots=max_snapshots,
        every_commit=every_commit,
        since=since,
    )
    _notify(
        job_progress,
        stage="enumerated",
        total_commits=len(plan.complete),
        total_frames=len(plan.selected),
    )
    state = _import_revisions(
        _ImportContext(
            database, scanner, root, plan, config_path, progress, job_progress, should_cancel
        )
    )
    _raise_if_cancelled(should_cancel)
    current_snapshot_id = _finalize_history(scanner, root, config_path, job_progress, state, plan)
    return HistoryImportResult(
        total_commits=len(plan.complete),
        selected_commits=len(plan.selected),
        imported_snapshots=state.imported,
        first_commit=plan.complete[0] if plan.complete else None,
        latest_commit=plan.complete[-1] if plan.complete else None,
        current_snapshot_id=current_snapshot_id,
        work=state.work,
    )


def _history_plan(
    database: Any,
    root: Path,
    *,
    config_path: str | Path | None,
    max_snapshots: int | str,
    every_commit: bool,
    since: str | None,
) -> _HistoryPlan:
    complete = git.revisions(root, limit=None, since=since, oldest_first=True)
    config = load_config(root, Path(config_path) if config_path else None)
    repository_id = database.ensure_repository(
        path=root, name=config.project_name or root.name, git=git.metadata(root)
    )
    selected = _selected_revisions(root, complete, config, max_snapshots, every_commit)
    summaries = {item.commit_sha: item for item in git.revision_summaries(root)}
    return _HistoryPlan(
        complete,
        selected,
        repository_id,
        analysis_signature(config),
        summaries,
        config,
    )


def _import_revisions(context: _ImportContext) -> _FrameState:
    state = _FrameState(work=_empty_work())
    for index, commit_sha in enumerate(context.plan.selected, start=1):
        _import_revision(context, state, index, commit_sha)
    return state


def _import_revision(
    context: _ImportContext, state: _FrameState, index: int, commit_sha: str
) -> None:
    _raise_if_cancelled(context.should_cancel)
    summary = context.plan.summaries.get(commit_sha)
    _notify_frame_started(context, state, index, commit_sha, summary)
    if context.progress:
        context.progress(index, len(context.plan.selected), commit_sha)
    reused = materialize_revision(context, state, commit_sha)
    state.baseline_revision = commit_sha
    state.imported += 1
    _notify_frame_complete(
        context.job_progress,
        index,
        context.plan.selected,
        commit_sha,
        summary,
        state.baseline_snapshot_id,
        state.work,
        reused_frame=reused,
    )


def _notify_frame_started(
    context: _ImportContext,
    state: _FrameState,
    index: int,
    commit_sha: str,
    summary: git.RevisionSummary | None,
) -> None:
    _notify(
        context.job_progress,
        stage="frame_started",
        frame=index,
        completed_frames=index - 1,
        total_frames=len(context.plan.selected),
        commit_sha=commit_sha,
        commit_subject=summary.subject if summary else "",
        commit_date=summary.committed_at if summary else None,
        last_complete_snapshot_id=state.baseline_snapshot_id,
        work=state.work,
    )


def _finalize_history(
    scanner: RepositoryScanner,
    root: Path,
    config_path: str | Path | None,
    job_progress: Callable[[dict[str, Any]], None] | None,
    state: _FrameState,
    plan: _HistoryPlan,
) -> int:
    _notify(
        job_progress,
        stage="finalizing",
        completed_frames=state.imported,
        total_frames=len(plan.selected),
        last_complete_snapshot_id=state.baseline_snapshot_id,
        work=state.work,
    )
    current = scanner.scan(
        root,
        config_path=config_path,
        run_type="history_current",
        baseline_snapshot_id=state.baseline_snapshot_id,
    )
    return current.snapshot_id


def _notify_frame_complete(
    callback: Callable[[dict[str, Any]], None] | None,
    index: int,
    selected: list[str],
    commit_sha: str,
    summary: git.RevisionSummary | None,
    snapshot_id: int,
    work: dict[str, Any],
    *,
    reused_frame: bool,
) -> None:
    _notify(
        callback,
        stage="frame_complete",
        frame=index,
        completed_frames=index,
        total_frames=len(selected),
        commit_sha=commit_sha,
        commit_subject=summary.subject if summary else "",
        commit_date=summary.committed_at if summary else None,
        last_complete_snapshot_id=snapshot_id,
        reused_frame=reused_frame,
        work=work,
    )


def _notify(callback: Callable[[dict[str, Any]], None] | None, **event: Any) -> None:
    if callback is not None:
        callback(event)


def _raise_if_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise HistoryImportCancelled("History import cancelled after its last complete frame")


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


def adaptive_history_limit(file_count: int) -> int:
    if file_count <= 500:
        return 32
    if file_count <= 2_000:
        return 24
    if file_count <= 5_000:
        return 16
    return 12


def _selected_revisions(
    root: Path, values: list[str], config: Any, limit: int | str, every_commit: bool
) -> list[str]:
    if every_commit:
        return values
    resolved = resolve_history_limit(root, config, limit)
    return representative_revisions(root, values, max(1, resolved))


def resolve_history_limit(root: Path, config: Any, value: int | str) -> int:
    if isinstance(value, int):
        if not 0 <= value <= 2_000:
            raise ValueError("History frame limit must be between 0 and 2000")
        return value
    if value != "auto":
        raise ValueError("History frame limit must be 'auto' or an integer between 0 and 2000")
    paths = git.files_at_revision(root, "HEAD") if git.has_commits(root) else git.listed_files(root)
    eligible = sum(
        not config.is_ignored(path) and detect_language(path) is not None for path in paths
    )
    return adaptive_history_limit(eligible)


def representative_revisions(root: Path, values: list[str], limit: int) -> list[str]:
    if len(values) <= limit or limit < 2:
        return sampled_revisions(values, limit)
    eligible = set(values)
    summaries = [item for item in git.revision_summaries(root) if item.commit_sha in eligible]
    selected = {values[0], values[-1]}
    tagged = [value for value in values if value in git.tagged_revisions(root)]
    _add_sampled(selected, tagged, limit - len(selected))
    architecture = [item.commit_sha for item in summaries if _architecture_change(item.paths)]
    _add_sampled(selected, architecture, (limit - len(selected) + 1) // 2)
    calendar = list({item.committed_at[:7]: item.commit_sha for item in summaries}.values())
    _add_sampled(selected, calendar, (limit - len(selected) + 1) // 2)
    for value in reversed(values):
        if len(selected) >= limit:
            break
        selected.add(value)
    return [value for value in values if value in selected]


def _add_sampled(selected: set[str], candidates: list[str], count: int) -> None:
    available = [value for value in candidates if value not in selected]
    selected.update(sampled_revisions(available, min(max(0, count), len(available))))


def _architecture_change(paths: tuple[str, ...]) -> bool:
    markers = (
        ".anaxigraph",
        "architecture",
        "dockerfile",
        "compose",
        "package.json",
        "pyproject.toml",
        "requirements",
        "migration",
        "schema",
        ".github/workflows",
    )
    return any(any(marker in path.lower() for marker in markers) for path in paths)
