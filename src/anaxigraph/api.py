"""REST API, dashboard host, and combined MCP application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

import anaxigraph.api_dashboard as api_dashboard
import anaxigraph.api_support as api_support
from anaxigraph import __version__
from anaxigraph.api_context import ApiContext, build_api_context
from anaxigraph.api_lifespan import application_lifespan
from anaxigraph.api_limits import RequestBodyLimitMiddleware
from anaxigraph.api_routes import register_api_routes
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.storage import AnaxiIndex


def create_app(
    *,
    database: AnaxiIndex,
    repository: Path | None = None,
    config_path: Path | None = None,
    scan_on_start: bool = False,
    enable_mcp: bool = True,
    allowed_hosts: list[str] | None = None,
    allow_scan_tool: bool = False,
    repository_targets: tuple[api_support.RepositoryTarget, ...] = (),
    repository_history_snapshots: int | str = 0,
    watch_interval: float | None = None,
) -> FastAPI:
    targets = _repository_targets(
        repository_targets,
        repository,
        config_path,
        repository_history_snapshots,
    )
    default_repository = targets[0].path if targets else repository
    context = build_api_context(database, targets, default_repository, watch_interval)
    mcp_servers = (
        _mcp_servers(
            context,
            config_path=config_path,
            allowed_hosts=allowed_hosts,
            allow_scan_tool=allow_scan_tool,
        )
        if enable_mcp
        else None
    )
    app = FastAPI(
        title="AnaxiGraph API",
        version=__version__,
        description="Temporal architecture, graph, findings, and bounded agent task context.",
        lifespan=application_lifespan(
            context,
            scan_on_start=scan_on_start,
            mcp_servers=mcp_servers,
        ),
    )
    app.add_middleware(RequestBodyLimitMiddleware)
    register_api_routes(app, context)
    api_dashboard.register_dashboard_routes(app)
    if mcp_servers is not None:
        normal, executor = mcp_servers
        app.mount("/executor", executor.streamable_http_app())
        app.mount("/", normal.streamable_http_app())
    return app


def _mcp_servers(
    context: ApiContext,
    *,
    config_path: Path | None,
    allowed_hosts: list[str] | None,
    allow_scan_tool: bool,
):
    shared = {
        "database": context.database,
        "repository": context.default_repository,
        "config_path": config_path,
        "allowed_hosts": allowed_hosts,
        "repository_targets": context.targets,
        "history_service": context.history_service,
    }
    return (
        create_anaxi_mcp_server(
            **shared,
            allow_scan_tool=allow_scan_tool,
            profile="normal",
        ),
        create_anaxi_mcp_server(
            **shared,
            allow_scan_tool=False,
            profile="executor",
        ),
    )


def _repository_targets(
    configured: tuple[api_support.RepositoryTarget, ...],
    repository: Path | None,
    config_path: Path | None,
    history_snapshots: int | str,
) -> tuple[api_support.RepositoryTarget, ...]:
    targets = list(configured)
    if repository is not None and all(
        target.path.resolve() != repository.resolve() for target in targets
    ):
        targets.insert(
            0,
            api_support.RepositoryTarget(
                key="default",
                path=repository.resolve(),
                config_path=config_path.resolve() if config_path else None,
                history_snapshots=history_snapshots,
            ),
        )
    return tuple(targets)
