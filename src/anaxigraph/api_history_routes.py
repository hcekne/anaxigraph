"""Git history import and trend routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import anaxigraph.api_support as api_support
import anaxigraph.git as git


def history_router(context: Any) -> APIRouter:
    return HistoryRoutes(context).router


class HistoryRoutes:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.router = APIRouter()
        self.router.add_api_route("/api/history", self.history, methods=["GET"])
        self.router.add_api_route("/api/history/import", self.import_history, methods=["POST"])
        self.router.add_api_route("/api/history/cancel", self.cancel, methods=["POST"])
        self.router.add_api_route("/api/trends", self.trends, methods=["GET"])

    def history(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        target = self.context.target_for_path(Path(row["path"]))
        timeline = self.context.database.timeline_snapshots(int(row["id"]), limit=2_000)
        commits = []
        if target and git.has_commits(target.path):
            commits = git.revisions(target.path, limit=None, oldest_first=True)
        job = self.context.history_service.status(int(row["id"]))
        summary = _timeline_summary(timeline, commits, job)
        return {
            "source": "git_first_parent" if commits else "working_tree",
            "total_commits": len(commits),
            "analyzed_commits": summary["saved_commit_maps"],
            "timeline_frames": len(timeline),
            "first_commit": commits[0] if commits else None,
            "latest_commit": commits[-1] if commits else None,
            "sample_limit": target.history_snapshots if target else 0,
            "timeline": summary,
            "job": job,
        }

    def import_history(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        target = self.context.target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(
                status_code=403,
                detail="This indexed repository is not mounted as a scan target",
            )
        if not git.has_commits(target.path):
            raise HTTPException(status_code=400, detail="Repository has no Git history")
        self.context.admit_operation(int(row["id"]), "history_import", hold=False)
        started = self.context.history_service.start(target)
        return {
            "status": _start_status(started),
            "repository_id": row["id"],
            "job": started.get("job"),
        }

    def cancel(self, repository_id: int | None = None) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        return self.context.history_service.cancel(int(row["id"]))

    def trends(
        self,
        repository_id: int | None = None,
        limit: int = Query(default=100, ge=1, le=1_000),
    ) -> dict[str, Any]:
        row = self.context.selected_repository(repository_id)
        return api_support.repository_trends(self.context.database, int(row["id"]), limit=limit)


def _start_status(started: dict[str, Any]) -> str:
    if started.get("started"):
        return "started"
    if started.get("resumed"):
        return "resumed"
    return str(started.get("reason", "already_running"))


def _timeline_summary(
    frames: list[dict[str, Any]], revisions: list[str], job: dict[str, Any]
) -> dict[str, Any]:
    saved = [frame for frame in frames if frame.get("snapshot_kind") == "commit"]
    last = (job.get("result") or {}).get("latest_commit")
    last = last or (saved[-1].get("commit_sha") if saved else None)
    position = {revision: index for index, revision in enumerate(revisions)}.get(str(last or ""))
    tail = len(revisions) if position is None else len(revisions) - position - 1
    status = str(job.get("status") or "")
    if status in {"queued", "enumerating", "importing", "finalizing"}:
        state = "updating"
    elif not revisions:
        state = "unversioned"
    elif not saved:
        state = "not_imported"
    else:
        state = "stale" if tail else "current"
    return {
        "state": state,
        "needs_update": state in {"not_imported", "stale", "failed", "cancelled"},
        "saved_commit_maps": len(saved),
        "unmapped_tail_commits": max(0, tail),
    }
