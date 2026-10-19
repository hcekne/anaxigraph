from __future__ import annotations

import json
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from anaxigraph import api_dashboard


def dashboard_client():
    app = FastAPI()
    api_dashboard.register_dashboard_routes(app)
    return TestClient(app)


def test_dashboard_versions_the_complete_browser_asset_graph():
    client = dashboard_client()
    response = client.get("/")
    revision = response.headers["x-anaxigraph-dashboard"]
    assert response.headers["cache-control"] == "no-cache, must-revalidate"
    assert f"/assets/app.js?v={revision}" in response.text
    assert f"/assets/styles.css?v={revision}" in response.text
    imports = json.loads(re.search(r'<script type="importmap">(.*?)</script>', response.text)[1])
    core = f"/assets/dashboard-core.js?v={revision}"
    assert imports["imports"]["/assets/dashboard-core.js"] == core
    for name in api_dashboard.DASHBOARD_ASSETS:
        asset = client.get(f"/assets/{name}?v={revision}")
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == response.headers["cache-control"]
        assert asset.headers["x-anaxigraph-dashboard"] == revision
        if name.endswith((".js", ".css")):
            for reference in re.findall(r"/assets/[\w.-]+(?:\?v=[\w]+)?", asset.text):
                assert reference.endswith(f"?v={revision}")
                assert client.get(reference).status_code == 200
    assert client.get("/assets/private.txt").status_code == 404
    assert client.get("/assets/index.html").status_code == 404
    assert client.get("/favicon.ico").content == client.get("/assets/favicon.svg").content
    assert client.head("/favicon.ico").content == b""


def test_changed_assets_get_new_urls_and_each_served_build_stays_consistent(tmp_path, monkeypatch):
    for name in {"index.html", *api_dashboard.DASHBOARD_ASSETS}:
        (tmp_path / name).write_bytes(api_dashboard.DASHBOARD.joinpath(name).read_bytes())
    monkeypatch.setattr(api_dashboard, "DASHBOARD", tmp_path)
    original = dashboard_client()
    first = original.get("/")
    first_revision = first.headers["x-anaxigraph-dashboard"]
    css = tmp_path / "workflows.css"
    css.write_text(css.read_text() + "\n.workflow-node { outline-width: 3px; }\n")
    assert original.get("/").content == first.content
    assert "outline-width: 3px" not in original.get("/assets/workflows.css").text
    updated = dashboard_client()
    second = updated.get("/")
    second_revision = second.headers["x-anaxigraph-dashboard"]
    assert first_revision != second_revision
    assert f"/assets/app.js?v={second_revision}" in second.text
    assert f"/assets/workflows.css?v={second_revision}" in updated.get("/assets/styles.css").text
    assert "outline-width: 3px" in updated.get("/assets/workflows.css").text
    assert updated.get("/assets/workflows.css").headers["content-type"].startswith("text/css")
    assert updated.get("/assets/app.js").headers["content-type"].startswith("text/javascript")
    assert updated.get("/assets/favicon.svg").headers["content-type"].startswith("image/svg+xml")
