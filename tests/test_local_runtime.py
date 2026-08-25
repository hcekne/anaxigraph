from __future__ import annotations

import json
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anaxigraph.api import create_app
from anaxigraph.cli import main
from anaxigraph.local_runtime import (
    LocalRuntime,
    assert_port_available,
    build_local_app,
    local_database_path,
    local_state_root,
    run_local_service,
)
from anaxigraph.storage import AnaxiIndex


def test_local_state_paths_follow_each_operating_system_and_checkout(tmp_path: Path):
    home = tmp_path / "home"
    repository = tmp_path / "My Project"
    repository.mkdir()

    linux = local_state_root(environment={}, home=home, system="Linux")
    macos = local_state_root(environment={}, home=home, system="Darwin")
    windows = local_state_root(environment={}, home=home, system="Windows")
    database = local_database_path(
        repository,
        environment={"XDG_STATE_HOME": str(tmp_path / "state")},
        home=home,
        system="Linux",
    )

    assert linux == home / ".local/state/anaxigraph"
    assert macos == home / "Library/Application Support/AnaxiGraph"
    assert windows == home / "AppData/Local/AnaxiGraph"
    assert database.parent.parent == tmp_path / "state/anaxigraph/repositories"
    assert database.name == "anaxi-index.db"
    assert database.parent.name.startswith("my-project-")
    assert repository not in database.parents


def test_up_dry_run_previews_policy_state_and_connection_without_writes(repository: Path, capsys):
    before = (repository / ".anaxigraph.yml").read_text(encoding="utf-8")
    main(
        [
            "up",
            str(repository),
            "--semantic",
            "agent",
            "--connect",
            "codex",
            "--connect-scope",
            "project",
            "--dry-run",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "dry_run"
    assert result["mode"] == "local_loopback"
    assert result["policy"]["action"] == "would_update"
    assert result["connections"][0]["action"] == "would_create"
    assert result["semantic"]["enabled"] is True
    assert result["agent_scan"] is True
    assert (repository / ".anaxigraph.yml").read_text(encoding="utf-8") == before
    assert not (repository / ".codex").exists()
    assert not Path(result["database"]).exists()


def test_up_prepares_policy_connection_and_private_external_runtime(
    repository: Path,
    monkeypatch,
    capsys,
    tmp_path: Path,
):
    runtimes: list[LocalRuntime] = []
    monkeypatch.setenv("ANAXIGRAPH_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr("anaxigraph.up_cli.assert_port_available", lambda _port: None)
    monkeypatch.setattr(
        "anaxigraph.up_cli.run_local_service",
        lambda runtime, **_dependencies: runtimes.append(runtime),
    )

    main(
        [
            "up",
            str(repository),
            "--port",
            "9123",
            "--history-snapshots",
            "0",
            "--semantic",
            "agent",
            "--connect",
            "codex",
            "--connect-scope",
            "project",
        ]
    )

    assert len(runtimes) == 1
    runtime = runtimes[0]
    assert runtime.repository == repository.resolve()
    assert runtime.database_path.is_relative_to(tmp_path / "state")
    assert runtime.history_snapshots == 0
    assert 'url = "http://127.0.0.1:9123/mcp"' in (repository / ".codex/config.toml").read_text(
        encoding="utf-8"
    )
    policy = (repository / ".anaxigraph.yml").read_text(encoding="utf-8")
    assert "enabled: true" in policy
    error_output = capsys.readouterr().err
    assert "current scan, then adaptive history" in error_output
    assert "Ctrl-C" in error_output


def test_local_application_scans_before_becoming_healthy(repository: Path, tmp_path: Path):
    database = tmp_path / "state/anaxi-index.db"
    runtime = LocalRuntime(
        repository=repository,
        config_path=repository / ".anaxigraph.yml",
        database_path=database,
        history_snapshots=0,
    )

    app = build_local_app(runtime, index_factory=AnaxiIndex, app_factory=create_app)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        overview = client.get("/api/overview").json()
        assert overview["files"] == 8
        repositories = client.get("/api/repositories").json()
        assert repositories[0]["path"] == str(repository.resolve())
        assert repositories[0]["history_snapshots"] == 0

    assert database.is_file()


def test_local_service_secures_state_directory_and_binds_only_loopback(
    repository: Path, tmp_path: Path, monkeypatch
):
    database = tmp_path / "state/anaxi-index.db"
    runtime = LocalRuntime(
        repository=repository,
        config_path=repository / ".anaxigraph.yml",
        database_path=database,
        port=9124,
        history_snapshots=0,
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "anaxigraph.local_runtime.build_local_app",
        lambda _runtime, **_dependencies: object(),
    )
    monkeypatch.setattr(
        "anaxigraph.local_runtime.uvicorn.run",
        lambda app, **options: calls.append({"app": app, **options}),
    )

    run_local_service(runtime, index_factory=AnaxiIndex, app_factory=create_app)

    assert database.parent.stat().st_mode & 0o777 == 0o700
    assert calls == [
        {"app": calls[0]["app"], "host": "127.0.0.1", "port": 9124, "log_level": "info"}
    ]


def test_port_preflight_rejects_an_existing_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match="already in use"):
            assert_port_available(port)


def test_up_process_reaches_health_and_stops_cleanly(repository: Path, tmp_path: Path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    database = tmp_path / "external-state/anaxi-index.db"
    command = [
        sys.executable,
        "-m",
        "anaxigraph",
        "up",
        str(repository),
        "--db",
        str(database),
        "--port",
        str(port),
        "--history-snapshots",
        "0",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    healthy = False
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz", timeout=0.5
                ) as response:
                    healthy = response.status == 200
                    break
            except OSError:
                time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)

    assert healthy, stderr
    assert process.returncode == 0, stderr
    assert "AnaxiGraph local runtime" in stderr
    assert "Application shutdown complete" in stderr
    assert "stopped cleanly" in stdout
    assert database.is_file()
    assert not (repository / "anaxi-index.db").exists()
