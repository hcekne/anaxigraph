from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from anaxigraph.environment_doctor import inspect_environment
from anaxigraph.onboarding_clients import configure_client


class _AnaxiHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback contract
        if self.path != "/healthz":
            self.send_error(404)
            return
        self._json({"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback contract
        if self.path != "/mcp":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._json(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "AnaxiMCP", "version": "test"},
                },
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, value: object) -> None:
        payload = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def anaxi_service() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AnaxiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_environment_doctor_verifies_every_local_connection_layer(
    repository: Path,
    database,
    tmp_path: Path,
    anaxi_service: str,
):
    home = tmp_path / "home"
    mcp_url = f"{anaxi_service}/mcp"
    configure_client(
        "codex",
        scope="user",
        repository=repository,
        mcp_url=mcp_url,
        home=home,
        environment={},
    )

    report = inspect_environment(
        database.path,
        database.connect,
        repository=repository,
        service_url=anaxi_service,
        client="codex",
        connection_scope="user",
        expected_mcp_url=mcp_url,
        home=home,
    )

    assert report["status"] == "healthy"
    checks = report["environment"]["checks"]
    assert {name: check["status"] for name, check in checks.items()} == {
        "repository": "ok",
        "database": "ok",
        "service": "ok",
        "mcp": "ok",
        "client": "ok",
    }
    assert checks["mcp"]["server"]["name"] == "AnaxiMCP"


def test_environment_doctor_fails_closed_for_missing_selected_client(
    repository: Path,
    database,
    tmp_path: Path,
):
    report = inspect_environment(
        database.path,
        database.connect,
        repository=repository,
        client="claude",
        connection_scope="user",
        home=tmp_path / "empty-home",
    )

    assert report["status"] == "blocked"
    assert report["environment"]["checks"]["client"]["status"] == "failed"
    assert "environment:client" in report["blockers"]


def test_environment_doctor_reports_unreachable_service(repository: Path, database):
    report = inspect_environment(
        database.path,
        database.connect,
        repository=repository,
        service_url="http://127.0.0.1:1",
        timeout=0.05,
    )

    assert report["status"] == "blocked"
    assert report["environment"]["checks"]["service"]["status"] == "failed"
    assert report["environment"]["checks"]["mcp"]["status"] == "failed"
    assert "environment:service" in report["blockers"]
    assert "environment:mcp" in report["blockers"]
