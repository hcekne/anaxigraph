"""REST API, dashboard host, and combined MCP application."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from anaxigraph import __version__, api_coverage, api_dashboard, api_support, git
from anaxigraph.agent import agent_scope, branch_collisions, finding_context, impact_analysis
from anaxigraph.api_semantic import SemanticRefreshCoordinator
from anaxigraph.config import load_config
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


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
    history_service = api_support.HistoryJobService(database)
    semantic_refresh = SemanticRefreshCoordinator(database)

    def target_for_path(path: Path) -> RepositoryTarget | None:
        resolved = path.resolve()
        return next((target for target in targets if target.path.resolve() == resolved), None)

    def visible_repositories() -> list[dict[str, Any]]:
        rows = database.repositories()
        if targets:
            rows = [row for row in rows if target_for_path(Path(row["path"])) is not None]
        return rows

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
                    semantic_refresh.start(target)
        if mcp is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield

    app = FastAPI(
        title="AnaxiGraph API",
        version=__version__,
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
        return api_support.product_glossary()

    @app.get("/api/overview")
    def overview(
        repository_id: int | None = None, snapshot_id: int | None = None
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        result = database.overview(int(row["id"]), snapshot_id)
        result["coverage"] = api_coverage.coverage_diagnostics(
            row, selected_config(row), result.get("coverage") or {}
        )
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

    @app.get("/api/groups")
    def groups(
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        layer: str = Query(default="effective", pattern="^(effective|semantic|policy|inferred)$"),
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return {
            "layer": layer,
            "groups": database.group_hierarchy(int(row["id"]), snapshot_id, layer=layer),
        }

    @app.get("/api/taxonomy")
    def taxonomy(
        repository_id: int | None = None, snapshot_id: int | None = None
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        result = database.semantic_taxonomy(int(row["id"]), snapshot_id)
        if result is None:
            raise HTTPException(status_code=404, detail="No current semantic taxonomy")
        return result

    @app.get("/api/semantic")
    def semantic_status(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        result = SemanticEngine(database).status(int(row["id"]), selected_config(row).semantic)
        result["worker"] = semantic_refresh.status_for(Path(row["path"]))
        return result

    @app.post("/api/semantic/refresh")
    def refresh_semantics(
        repository_id: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
        wait: bool = False,
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
        if wait:
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
                plan_only=True,
            )
            return {"status": "prepared", "scan": stats.as_dict(), **result}
        started = semantic_refresh.start(target, force=force, retry_failed=retry_failed)
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
        view: str = Query(default="attention", pattern="^(attention|diagnostics)$"),
        cursor: str = Query(default="", max_length=2_000),
        page_size: int | None = Query(default=None, ge=1, le=200),
        status: list[str] = Query(default=[]),
        severity: list[str] = Query(default=[]),
        finding_type: list[str] = Query(default=[]),
        module: str = Query(default="", max_length=2_000),
        architecture_area: str = Query(default="", max_length=250),
        minimum_confidence: float = Query(default=0, ge=0, le=1),
    ) -> dict[str, Any]:
        row = selected_repository(repository_id)
        try:
            return api_support.query_findings(
                database,
                int(row["id"]),
                selected_config(row),
                view=view,
                cursor=cursor,
                page_size=page_size,
                statuses=tuple(status),
                severities=tuple(severity),
                finding_types=tuple(finding_type),
                module=module,
                architecture_area=architecture_area,
                minimum_confidence=minimum_confidence,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/findings/{finding_id}/status")
    def finding_status(
        finding_id: int,
        request: api_support.FindingStatusRequest,
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
    def scope(request: api_support.ScopeRequest) -> dict[str, Any]:
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
    def impact(request: api_support.ImpactRequest) -> dict[str, Any]:
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
            semantic_refresh.start(target)
        return stats.as_dict()

    @app.get("/api/trends")
    def trends(repository_id: int | None = None, limit: int = 100) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return api_support.repository_trends(database, int(row["id"]), limit=limit)

    @app.get("/api/export")
    def export(repository_id: int | None = None) -> dict[str, Any]:
        row = selected_repository(repository_id)
        return {
            "overview": database.overview(int(row["id"])),
            "graph": database.graph(int(row["id"]), include_external=True),
            "findings": api_support.collect_finding_ledger(
                database, int(row["id"]), selected_config(row)
            ),
            "snapshots": database.snapshots(int(row["id"])),
            "semantic_taxonomy": database.semantic_taxonomy(int(row["id"])),
        }

    api_dashboard.register_dashboard_routes(app)
    if mcp is not None:
        app.mount("/", mcp.streamable_http_app())
    return app
