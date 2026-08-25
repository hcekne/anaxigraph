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
        analyzed = {
            str(item["commit_sha"])
            for item in timeline
            if item["commit_sha"] not in {"unversioned", "unknown"}
        }
        return {
            "source": "git_first_parent" if commits else "working_tree",
            "total_commits": len(commits),
            "analyzed_commits": len(analyzed),
            "timeline_frames": len(timeline),
            "first_commit": commits[0] if commits else None,
            "latest_commit": commits[-1] if commits else None,
            "sample_limit": target.history_snapshots if target else 0,
            "job": self.context.history_service.status(int(row["id"])),
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
