"""REST API, dashboard host, and combined MCP application."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from importlib.resources import files as package_files
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from anaxigraph import git
from anaxigraph.agent import agent_scope, branch_collisions, finding_context, impact_analysis
from anaxigraph.config import load_config
from anaxigraph.guidance import product_glossary
from anaxigraph.history_jobs import HistoryJobService
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


class ScopeRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=2_000)
    branch: str | None = Field(default=None, max_length=250)
    repository_id: int | None = None


class ImpactRequest(BaseModel):
    target: str = Field(min_length=1, max_length=1_000)
    branch: str | None = Field(default=None, max_length=250)
    repository_id: int | None = None


class FindingStatusRequest(BaseModel):
    status: str


def create_app(
    *,
    database: AnaxiIndex,
    repository: Path | None = None,
    config_path: Path | None = None,
    scan_on_start: bool = False,
    enable_mcp: bool = True,
    allowed_hosts: list[str] | None = None,
    allow_scan_tool: bool = False,
    repository_targets: tuple[RepositoryTarget, ...] = (),
    repository_history_snapshots: int | str = 0,
) -> FastAPI:
    targets = list(repository_targets)
    if repository is not None and all(
        target.path.resolve() != repository.resolve() for target in targets
    ):
        targets.insert(
            0,
            RepositoryTarget(
                key="default",
                path=repository.resolve(),
                config_path=config_path.resolve() if config_path else None,
                history_snapshots=repository_history_snapshots,
            ),
        )
    default_repository = targets[0].path if targets else repository
    history_service = HistoryJobService(database)
    semantic_jobs: dict[str, dict[str, Any]] = {}
    semantic_lock = threading.Lock()

    def target_for_path(path: Path) -> RepositoryTarget | None:
        resolved = path.resolve()
        return next((target for target in targets if target.path.resolve() == resolved), None)

    def visible_repositories() -> list[dict[str, Any]]:
        rows = database.repositories()
        if targets:
            rows = [row for row in rows if target_for_path(Path(row["path"])) is not None]
        return rows

    def semantic_worker(target: RepositoryTarget, force: bool, retry_failed: bool) -> None:
        key = str(target.path.resolve())
        with semantic_lock:
            semantic_jobs[key] = {"status": "running"}
        try:
            config = load_config(target.path, target.config_path)
            stats = RepositoryScanner(database).scan(
                target.path,
                config_path=target.config_path,
                run_type="semantic_reconcile",
            )
            result = SemanticEngine(database).bootstrap(
                stats.repository_id,
                target.path,
                config,
                force=force,
                retry_failed=retry_failed,
            )
            with semantic_lock:
                semantic_jobs[key] = {
                    "status": "complete",
                    "scan": stats.as_dict(),
                    **result,
                }
        except Exception as exc:  # Background failures are intentionally visible in the UI.
            with semantic_lock:
                semantic_jobs[key] = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:2_000],
                }

    def start_semantic_refresh(
        target: RepositoryTarget, *, force: bool = False, retry_failed: bool = False
    ) -> bool:
        key = str(target.path.resolve())
        config = load_config(target.path, target.config_path)
        if not config.semantic.enabled:
            return False
        repository_row = database.repository(target.path)
        if repository_row is not None:
            durable_status = SemanticEngine(database).status(
                int(repository_row["id"]), config.semantic
            )
            if int(durable_status.get("jobs", {}).get("running", 0)) > 0:
                return False
        with semantic_lock:
            if semantic_jobs.get(key, {}).get("status") in {"queued", "running"}:
                return False
            semantic_jobs[key] = {"status": "queued"}
        threading.Thread(
            target=semantic_worker,
            args=(target, force, retry_failed),
            name=f"anaxigraph-semantic-{target.key}",
            daemon=True,
        ).start()
        return True

    mcp = (
        create_anaxi_mcp_server(
            database=database,
            repository=default_repository,
            config_path=config_path,
            allowed_hosts=allowed_hosts,
            allow_scan_tool=allow_scan_tool,
            repository_targets=tuple(targets),
            history_service=history_service,
        )
        if enable_mcp
        else None
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        history_service.recover(targets)
        if scan_on_start:
            for target in targets:
                await asyncio.to_thread(
                    RepositoryScanner(database).scan,
                    target.path,
                    config_path=target.config_path,
                )
            for target in targets:
                history_service.start(target)
                config = load_config(target.path, target.config_path)
                if config.semantic.enabled and config.semantic.refresh in {"on_scan", "periodic"}:
                    start_semantic_refresh(target)
        if mcp is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield

    app = FastAPI(
        title="AnaxiGraph API",
        version="0.1.0",
        description="Temporal architecture, graph, findings, and bounded agent task context.",
        lifespan=lifespan,
    )

    def selected_repository(repository_id: int | None = None) -> dict[str, Any]:
        row = (
            database.repository(repository_id)
            if repository_id
            else (
                database.repository(default_repository)
                if default_repository
                else database.repository()
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="No analyzed repository found")
        if targets and target_for_path(Path(row["path"])) is None:
            raise HTTPException(status_code=404, detail="Repository is not in the active registry")
        return row

    def selected_config(row: dict[str, Any]):
        row_path = Path(row["path"]).resolve()
        target = target_for_path(row_path)
        return load_config(target.path, target.config_path) if target else load_config(row_path)

    def coverage_diagnostics(row: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
        root = Path(row["path"]).resolve()
        config = selected_config(row)
        inputs = []
        for configured in config.coverage_files:
            path = Path(configured)
            candidate = path if path.is_absolute() else root / path
            inputs.append(
                {
                    "path": configured,
                    "exists": candidate.is_file(),
                    "format": "lcov"
                    if candidate.name == "lcov.info"
                    else candidate.suffix.lstrip(".") or "unknown",
                }
            )
        imported = coverage.get("line_coverage") is not None
        available = sum(1 for item in inputs if item["exists"])
        return {
            **coverage,
            "state": "imported" if imported else "unmatched" if available else "missing",
            "required": config.coverage_required,
            "configured_inputs": inputs,
            "available_inputs": available,
        }

    def is_scan_target(row: dict[str, Any]) -> bool:
        return target_for_path(Path(row["path"])) is not None

    @app.get("/healthz")
    def health() -> dict[str, str]:
        try:
            with database.connect() as connection:
                connection.execute("SELECT 1").fetchone()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="AnaxiIndex unavailable") from exc
        return {"status": "ok"}

    @app.get("/api/repositories")
    def repositories() -> list[dict[str, Any]]:
        target_order = {str(target.path.resolve()): index for index, target in enumerate(targets)}
        rows = visible_repositories()
        rows.sort(
            key=lambda row: (
                (
                    0,
                    target_order[str(Path(row["path"]).resolve())],
                )
                if str(Path(row["path"]).resolve()) in target_order
                else (1, 0)
            )
        )
        result = []
        for row in rows:
            target = target_for_path(Path(row["path"]))
            config = selected_config(row)
            result.append(
                {
                    **row,
                    "scannable": target is not None,
                    "registry_key": target.key if target else None,
                    "default": bool(
                        targets and Path(row["path"]).resolve() == targets[0].path.resolve()
                    ),
                    "config_path": str(
                        (target.config_path if target else None) or config.config_path or ""
                    ),
                    "history_snapshots": target.history_snapshots if target else None,
                }
            )
        return result

    @app.get("/api/glossary")
    def glossary() -> dict[str, Any]:
        return product_glossary()

    @app.get("/api/overview")
    def overview(
        repository_id: int | None = None, snapshot_id: int | None = None
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        result = database.overview(int(row["id"]), snapshot_id)
        result["coverage"] = coverage_diagnostics(row, result.get("coverage") or {})
        if snapshot_id is None:
            result["semantic"] = SemanticEngine(database).status(
                int(row["id"]), selected_config(row).semantic
            )
        return result

    @app.get("/api/modules")
    def modules(
        repository_id: int | None = None, snapshot_id: int | None = None
    ) -> list[dict[str, Any]]:
        row = selected_repository(repository_id)
        return database.modules(int(row["id"]), snapshot_id)

    @app.get("/api/semantic")
    def semantic_status(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        result = SemanticEngine(database).status(int(row["id"]), selected_config(row).semantic)
        with semantic_lock:
            result["worker"] = dict(
                semantic_jobs.get(str(Path(row["path"]).resolve()), {"status": "idle"})
            )
        return result

    @app.post("/api/semantic/refresh")
    def refresh_semantics(
        repository_id: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        target = target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(
                status_code=403,
                detail="This indexed repository is not mounted as a semantic-analysis target",
            )
        config = selected_config(row)
        if not config.semantic.enabled:
            raise HTTPException(
                status_code=400,
                detail="Semantic analysis is disabled in this repository's .anaxigraph.yml",
            )
        started = start_semantic_refresh(target, force=force, retry_failed=retry_failed)
        return {
            "status": "started" if started else "already_running",
            "repository_id": row["id"],
        }

    @app.get("/api/graph")
    def graph(
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        include_external: bool = False,
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return database.graph(int(row["id"]), snapshot_id, include_external=include_external)

    @app.get("/api/file")
    def file_details(
        path: str = Query(min_length=1, max_length=2_000),
        repository_id: int | None = None,
        snapshot_id: int | None = None,
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        result = database.file_details(int(row["id"]), path, snapshot_id)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found in snapshot")
        return result

    @app.get("/api/search")
    def search(
        q: str = Query(min_length=2, max_length=1_000),
        repository_id: int | None = None,
        limit: int = Query(default=30, ge=1, le=100),
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return {"query": q, "results": database.search(int(row["id"]), q, limit=limit)}

    @app.get("/api/snapshots")
    def snapshots(
        repository_id: int | None = None,
        limit: int = Query(default=100, ge=1, le=1_000),
    ) -> list[dict[str, Any]]:
        row = selected_repository(repository_id)
        return database.timeline_snapshots(int(row["id"]), limit=limit)

    @app.get("/api/history")
    def history(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        target = target_for_path(Path(row["path"]))
        timeline = database.timeline_snapshots(int(row["id"]), limit=2_000)
        commits = []
        if target and git.has_commits(target.path):
            commits = git.revisions(target.path, limit=None, oldest_first=True)
        job = history_service.status(int(row["id"]))
        analyzed_commit_shas = {
            str(item["commit_sha"])
            for item in timeline
            if item["commit_sha"] not in {"unversioned", "unknown"}
        }
        return {
            "source": "git_first_parent" if commits else "working_tree",
            "total_commits": len(commits),
            "analyzed_commits": len(analyzed_commit_shas),
            "timeline_frames": len(timeline),
            "first_commit": commits[0] if commits else None,
            "latest_commit": commits[-1] if commits else None,
            "sample_limit": target.history_snapshots if target else 0,
            "job": job,
        }

    @app.post("/api/history/import")
    def import_history(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        target = target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(
                status_code=403,
                detail="This indexed repository is not mounted as a scan target",
            )
        if not git.has_commits(target.path):
            raise HTTPException(status_code=400, detail="Repository has no Git history")
        started = history_service.start(target)
        return {
            "status": (
                "started"
                if started.get("started")
                else "resumed"
                if started.get("resumed")
                else started.get("reason", "already_running")
            ),
            "repository_id": row["id"],
            "job": started.get("job"),
        }

    @app.post("/api/history/cancel")
    def cancel_history(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return history_service.cancel(int(row["id"]))

    @app.get("/api/findings")
    def findings(
        repository_id: int | None = None,
        status: list[str] = Query(default=[]),
        limit: int = Query(default=500, ge=1, le=2_000),
    ) -> list[dict[str, Any]]:
        row = selected_repository(repository_id)
        return database.findings(int(row["id"]), statuses=tuple(status), limit=limit)

    @app.post("/api/findings/{finding_id}/status")
    def finding_status(
        finding_id: int,
        request: FindingStatusRequest,
        repository_id: int | None = None,
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        try:
            updated = database.update_finding_status(int(row["id"]), finding_id, request.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Finding not found")
        return {"id": finding_id, "status": request.status}

    @app.get("/api/findings/{finding_id}/context")
    def finding_agent_context(
        finding_id: int,
        repository_id: int | None = None,
        branch: str | None = Query(default=None, max_length=250),
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        try:
            return finding_context(
                database,
                repository_id=int(row["id"]),
                finding_id=finding_id,
                branch=branch,
                config=selected_config(row),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent-scope")
    def scope(request: ScopeRequest) -> dict[str, Any]:
        row = selected_repository(request.repository_id)
        try:
            return agent_scope(
                database,
                repository_id=int(row["id"]),
                goal=request.goal,
                branch=request.branch,
                config=selected_config(row),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/impact")
    def impact(request: ImpactRequest) -> dict[str, Any]:
        row = selected_repository(request.repository_id)
        try:
            return impact_analysis(
                database,
                repository_id=int(row["id"]),
                target=request.target,
                branch=request.branch,
                config=selected_config(row),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/branch-collisions")
    def collisions(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return branch_collisions(database, repository_id=int(row["id"]))

    @app.post("/api/scan")
    async def scan(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        target = target_for_path(Path(row["path"]))
        if target is None:
            raise HTTPException(
                status_code=403,
                detail="This indexed repository is read-only in the current server process",
            )
        stats = await asyncio.to_thread(
            RepositoryScanner(database).scan,
            target.path,
            config_path=target.config_path,
        )
        config = selected_config(row)
        if config.semantic.enabled and config.semantic.refresh == "on_scan":
            start_semantic_refresh(target)
        return stats.as_dict()

    @app.get("/api/trends")
    def trends(repository_id: int | None = None, limit: int = 100) -> dict[str, Any]:
        row = selected_repository(repository_id)
        with database.connect() as connection:
            metric_rows = connection.execute(
                """
                SELECT s.id AS snapshot_id, s.commit_sha, s.analysis_timestamp,
                       m.name, m.value
                FROM snapshots s JOIN metrics m ON m.snapshot_id = s.id
                WHERE s.repository_id = ? AND m.entity_type = 'repository'
                ORDER BY COALESCE(datetime(s.commit_timestamp), s.analysis_timestamp) DESC,
                         s.id DESC LIMIT ?
                """,
                (row["id"], max(1, min(limit, 1_000)) * 20),
            ).fetchall()
        grouped: dict[int, dict[str, Any]] = {}
        for metric in metric_rows:
            item = grouped.setdefault(
                int(metric["snapshot_id"]),
                {
                    "snapshot_id": metric["snapshot_id"],
                    "commit_sha": metric["commit_sha"],
                    "analysis_timestamp": metric["analysis_timestamp"],
                    "metrics": {},
                },
            )
            item["metrics"][metric["name"]] = metric["value"]
        return {"snapshots": list(reversed(list(grouped.values())[:limit]))}

    dashboard = package_files("anaxigraph.dashboard")

    @app.get("/", response_class=HTMLResponse)
    def dashboard_index() -> FileResponse:
        return FileResponse(str(dashboard.joinpath("index.html")))

    @app.get("/assets/{name}")
    def dashboard_asset(name: str) -> FileResponse:
        if name not in {"app.js", "history-view.js", "styles.css", "favicon.svg", "mask-icon.svg"}:
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(str(dashboard.joinpath(name)))

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(str(dashboard.joinpath("favicon.svg")), media_type="image/svg+xml")

    @app.get("/api/export")
    def export(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return {
            "overview": database.overview(int(row["id"])),
            "graph": database.graph(int(row["id"]), include_external=True),
            "findings": database.findings(int(row["id"])),
            "snapshots": database.snapshots(int(row["id"])),
        }

    if mcp is not None:
        app.mount("/", mcp.streamable_http_app())
    return app
