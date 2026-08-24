from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pytest
import yaml

import anaxigraph.cli_semantic_commands as semantic_commands
import anaxigraph.cli_server_commands as server_commands
import anaxigraph.cli_services as cli_services
from anaxigraph.cli import main
from anaxigraph.cli_common import default_db
from anaxigraph.config import SemanticConfig
from anaxigraph.registry import RepositoryTarget
from anaxigraph.semantic_service import SemanticServiceTarget


def _call(arguments: list[str], capsys) -> dict:
    main(arguments)
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_repository_agent_and_export_handlers_share_the_current_scan(
    repository: Path,
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    database = tmp_path / "commands.db"
    common = [str(repository), "--db", str(database), "--json"]
    scanned = _call(["scan", *common], capsys)
    reviewed = _call(["review", *common, "--status", "all"], capsys)
    scoped = _call(["scope", *common, "--goal", "Change the calculator"], capsys)
    impacted = _call(["impact", *common, "--target", "pkg/core.py"], capsys)
    collisions = _call(["collisions", *common], capsys)
    exported = _call(["export", *common], capsys)

    assert scanned["status"] == "ok"
    assert "finding_page" in reviewed
    assert scoped["goal"] == "Change the calculator"
    assert impacted["target"]["path"] == "pkg/core.py"
    assert collisions["branches"] == {}
    assert exported["graph"]["nodes"]

    finding_id = reviewed["finding_page"]["items"][0]["id"]
    changed = _call(
        [
            "finding",
            str(finding_id),
            "acknowledged",
            "--repository",
            str(repository),
            "--db",
            str(database),
            "--json",
        ],
        capsys,
    )
    assert changed == {"id": finding_id, "status": "acknowledged"}

    def stop(_interval: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("anaxigraph.cli_repository_commands.time.sleep", stop)
    with pytest.raises(SystemExit, match="130"):
        main(["watch", *common, "--interval", "0.2"])
    assert "Watching 1 repositories" in capsys.readouterr().err


def test_semantic_handlers_plan_report_run_and_resume(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "refresh": "manual",
        "include": ["pkg/**"],
        "agent_lease_seconds": 120,
    }
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    database_path = tmp_path / "semantic-commands.db"
    common = [str(repository), "--db", str(database_path), "--json"]

    planned = _call(["understand", *common, "--limit", "2", "--plan-only"], capsys)
    requires_agent = _call(["understand", *common, "--limit", "2", "--executor", "mcp"], capsys)
    status = _call(["semantic-status", *common], capsys)
    reconciled = _call(["semantic-worker", *common, "--once"], capsys)

    assert planned["semantic"]["enabled"] is True
    assert planned["status"] == "planned"
    assert requires_agent["status"] == "agent_action_required"
    assert requires_agent["complete"] is False
    assert requires_agent["next_action"]["kind"] == "connected_agent_semantic_loop"
    assert "must not report" in requires_agent["next_action"]["instruction"]
    assert status["enabled"] is True
    assert reconciled["repositories"][0]["semantic"]["semantic"]["enabled"] is True

    def stop(_interval: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(semantic_commands.time, "sleep", stop)
    with pytest.raises(SystemExit, match="130"):
        main(["semantic-worker", *common])
    captured = capsys.readouterr()
    assert '"status": "skipped"' in captured.out
    assert "Semantic reconciliation for 1 repositories" in captured.err


def test_understand_auto_detects_codex_as_the_local_agent_executor(monkeypatch):
    args = argparse.Namespace(executor="auto", model="test-model", plan_only=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "test-thread")
    monkeypatch.setattr(semantic_commands.shutil, "which", lambda command: f"/bin/{command}")

    execution, mode = semantic_commands._understand_execution(
        args, SemanticConfig(enabled=True, provider="agent")
    )

    assert mode == "codex"
    assert execution.provider == "codex"
    assert execution.model == "test-model"


def test_agent_policy_model_cannot_pin_the_runtime_executor(monkeypatch):
    args = argparse.Namespace(executor="codex", model=None, plan_only=False)
    monkeypatch.setattr(semantic_commands.shutil, "which", lambda command: f"/bin/{command}")

    execution, mode = semantic_commands._understand_execution(
        args,
        SemanticConfig(enabled=True, provider="agent", model="obsolete-policy-model"),
    )

    assert mode == "codex"
    assert execution.model == ""


def test_understand_routes_omitted_database_to_matching_service(
    repository: Path, capsys, monkeypatch
):
    policy_path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    target = SemanticServiceTarget("http://127.0.0.1:9999", 17, "Sample", "/repo")
    monkeypatch.setattr(semantic_commands, "discover_semantic_service", lambda *_a, **_k: target)
    monkeypatch.setattr(
        semantic_commands,
        "prepare_semantic_service",
        lambda *_a, **_k: {
            "status": "prepared",
            "scan": {"repository_id": 17},
            "planned": 4,
            "semantic": {"semantically_ready": False},
        },
    )
    monkeypatch.setattr(
        semantic_commands,
        "service_semantic_status",
        lambda *_a, **_k: {"semantically_ready": False, "jobs": {"pending": 4}},
    )

    result = _call(
        ["understand", str(repository), "--executor", "mcp", "--json"],
        capsys,
    )

    assert result["index"]["authority"] == "service"
    assert result["index"]["repository_id"] == 17
    assert result["next_action"]["mcp_url"] == "http://127.0.0.1:9999/mcp"
    assert result["next_action"]["repository_id"] == 17
    assert result["status"] == "agent_action_required"


def test_semantic_scheduler_reports_disabled_and_scheduled_targets(
    repository: Path,
    tmp_path: Path,
):
    target = RepositoryTarget("fixture", repository, repository / ".anaxigraph.yml", 0)
    args = argparse.Namespace(interval=None)
    database = cli_services.open_index(tmp_path / "schedule.db")

    disabled = semantic_commands._reconcile_target(
        args,
        target,
        database,
        respect_refresh_policy=False,
        next_due=None,
    )
    assert disabled["status"] == "disabled"

    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent", "refresh": "periodic"}
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    scheduled = semantic_commands._reconcile_target(
        args,
        target,
        database,
        respect_refresh_policy=True,
        next_due={"fixture": time.monotonic() + 60},
    )

    assert scheduled["status"] == "scheduled"
    assert scheduled["next_in_seconds"] > 0
    assert semantic_commands._wait_seconds({}) >= 1


def test_serve_handler_assembles_and_opens_the_selected_endpoint(
    repository: Path,
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    application = object()
    created: list[dict] = []
    runs: list[tuple[object, str, int, str]] = []
    opened: list[str] = []

    def create_application(**options):
        created.append(options)
        return application

    monkeypatch.setattr(cli_services, "APP_FACTORY", create_application)
    monkeypatch.setattr(
        server_commands.uvicorn,
        "run",
        lambda app, host, port, log_level: runs.append((app, host, port, log_level)),
    )
    monkeypatch.setattr(server_commands.webbrowser, "open", opened.append)

    main(
        [
            "serve",
            "--repository",
            str(repository),
            "--db",
            str(tmp_path / "serve.db"),
            "--host",
            "0.0.0.0",
            "--port",
            "9123",
            "--allow-agent-scan",
            "--open",
        ]
    )

    assert created[0]["repository"] == repository.resolve()
    assert created[0]["allow_scan_tool"] is True
    assert runs == [(application, "0.0.0.0", 9123, "info")]
    assert opened == ["http://127.0.0.1:9123"]
    assert "Dashboard: http://127.0.0.1:9123" in capsys.readouterr().err


def test_cli_environment_default_and_validation_errors(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    configured = tmp_path / "configured.db"
    monkeypatch.setenv("ANAXIGRAPH_DB", str(configured))
    assert default_db() == configured

    with pytest.raises(SystemExit, match="2"):
        main(["understand", str(repository), "--limit", "0"])
    assert "Semantic job limit must be at least one" in capsys.readouterr().err

    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "finding",
                "999",
                "dismissed",
                "--repository",
                str(repository),
                "--db",
                str(tmp_path / "empty.db"),
            ]
        )
    assert "Repository has not been scanned" in capsys.readouterr().err
