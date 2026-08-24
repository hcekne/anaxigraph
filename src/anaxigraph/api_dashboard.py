"""Static dashboard route registration and explicit asset allow-list."""

from __future__ import annotations

from importlib.resources import files as package_files

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

DASHBOARD_ASSETS = frozenset(
    {
        "app.js",
        "dashboard-core.js",
        "dashboard-format.js",
        "finding-controller.js",
        "findings-view.js",
        "graph-events.js",
        "graph-model.js",
        "graph-view.js",
        "history-controller.js",
        "history-view.js",
        "module-events.js",
        "module-view.js",
        "navigation.js",
        "overview-view.js",
        "repository-view.js",
        "theme-boot.js",
        "workflow-events.js",
        "styles.css",
        "themes.css",
        "favicon.svg",
        "mask-icon.svg",
    }
)
DASHBOARD = package_files("anaxigraph.dashboard")


def register_dashboard_routes(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    def dashboard_index() -> FileResponse:
        return FileResponse(str(DASHBOARD.joinpath("index.html")))

    @app.get("/assets/{name}")
    def dashboard_asset(name: str) -> FileResponse:
        if name not in DASHBOARD_ASSETS:
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(str(DASHBOARD.joinpath(name)))

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(str(DASHBOARD.joinpath("favicon.svg")), media_type="image/svg+xml")
