"""Static dashboard route registration and explicit asset allow-list."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files as package_files

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

DASHBOARD_ASSETS = frozenset(
    {
        "app.js",
        "dashboard-core.js",
        "dashboard-format.js",
        "entity-client.js",
        "graph-subjects.js",
        "entity-inspector.js",
        "semantic-graph-layout.js",
        "semantic-graph.css",
        "dashboard-shell.css",
        "finding-controller.js",
        "findings-view.js",
        "fresh-eyes-view.js",
        "graph-events.js",
        "graph-model.js",
        "graph-regions.css",
        "graph-regions.js",
        "graph-view.js",
        "history-controller.js",
        "history-view.js",
        "journey-navigation.css",
        "module-events.js",
        "module-loading.js",
        "module-view.js",
        "navigation.js",
        "overview-view.js",
        "patterns.css",
        "patterns-render.js",
        "patterns-view.js",
        "repository-view.js",
        "reassessment-view.js",
        "reassessment.css",
        "theme-boot.js",
        "workflow-events.js",
        "workflow-freshness.js",
        "workflow-activity.js",
        "workflow-model.js",
        "workflow-render.js",
        "workflow-run-copy.js",
        "architecture-workflow.js",
        "architecture-planning-view.js",
        "architecture-plan-diagram.js",
        "architecture-planning.css",
        "workflow-settings.js",
        "workflows-view.js",
        "workflows.css",
        "styles.css",
        "themes.css",
        "favicon.svg",
        "mask-icon.svg",
    }
)
DASHBOARD = package_files("anaxigraph.dashboard")


def _dashboard_responses() -> dict[str, Response]:
    sources = {
        name: DASHBOARD.joinpath(name).read_bytes()
        for name in sorted({"index.html", *DASHBOARD_ASSETS})
    }
    digest = hashlib.sha256()
    for name, content in sources.items():
        digest.update(name.encode() + b"\0" + content + b"\0")
    revision = digest.hexdigest()[:16]
    imports = {
        f"/assets/{name}": f"/assets/{name}?v={revision}"
        for name in sources
        if name.endswith(".js")
    }
    head = (
        f'<meta name="anaxigraph-dashboard-build" content="{revision}" />'
        f'<script type="importmap">{json.dumps({"imports": imports})}</script>'
    ).encode()
    media = {
        "html": "text/html",
        "js": "text/javascript",
        "css": "text/css",
        "svg": "image/svg+xml",
    }
    responses = {}
    for name, content in sources.items():
        if name.endswith((".html", ".js", ".css")):
            content = re.sub(rb"(/assets/[\w.-]+)", rb"\1?v=" + revision.encode(), content)
        if name == "index.html":
            content = content.replace(b"<head>", b"<head>" + head, 1)
        responses[name] = Response(
            content,
            media_type=media[name.rsplit(".", 1)[1]],
            headers={
                "Cache-Control": "no-cache, must-revalidate",
                "X-AnaxiGraph-Dashboard": revision,
            },
        )
    return responses


def register_dashboard_routes(app: FastAPI) -> None:
    # Capture one coherent build, including imported modules and nested stylesheets.
    responses = _dashboard_responses()

    @app.get("/", response_class=HTMLResponse)
    def dashboard_index() -> Response:
        return responses["index.html"]

    @app.get("/assets/{name}")
    def dashboard_asset(name: str) -> Response:
        if name not in DASHBOARD_ASSETS:
            raise HTTPException(status_code=404, detail="Asset not found")
        return responses[name]

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    def favicon() -> Response:
        return responses["favicon.svg"]
