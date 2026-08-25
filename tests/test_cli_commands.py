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
import anaxigraph.semantic_execution as semantic_execution
from anaxigraph.cli import main
from anaxigraph.cli_common import default_db
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
    patterns = _call(["patterns", *common, "--limit", "1"], capsys)
    candidate_explanations = _call(
        ["patterns", *common, "--candidates", "--pattern", "circular-dependency", "--limit", "1"],
        capsys,
    )
    exported = _call(["export", *common], capsys)

    assert scanned["status"] == "ok"
    assert "finding_page" in reviewed
    assert scoped["goal"] == "Change the calculator"
    baseline_path = tmp_path / "verification-baseline.json"
    baseline_path.write_text(
        json.dumps(scoped["architecture_decision"]["verification"]["post_change_baseline"]),
        encoding="utf-8",
    )
    compared = _call(
        [
            "scope",
            *common,
            "--goal",
            "Change the calculator",
            "--verification-baseline",
            str(baseline_path),
        ],
        capsys,
    )
    assert (
        compared["architecture_decision"]["verification"]["post_change_comparison"]["status"]
        == "rescan_required"
    )
    assert impacted["target"]["path"] == "pkg/core.py"
    assert collisions["branches"] == {}
    assert patterns["contract_version"] == "pattern-query-v1"
    assert patterns["index"]["authority"] == "local"
    assert patterns["total"] == 0
    assert candidate_explanations["contract_version"] == "pattern-candidate-query-v1"
    assert exported["contract_version"] == "anaxigraph-export-v1"
    assert exported["graph"]["nodes"]
    assert exported["graph"]["counts"]["page_internal_nodes"] <= 250
    assert exported["findings"]["shown"] <= 200

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


def test_understand_routes_omitted_database_to_matching_service(
    repository: Path, capsys, monkeypatch
):
    target = SemanticServiceTarget(
        "http://127.0.0.1:9999",
        17,
        "Sample",
        "/repo",
        config_authority={
            "registry_key": "sample",
            "service_config_path": "/repo/.anaxigraph.yml",
        },
        semantic_policy={"enabled": True, "provider": "agent"},
    )
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


def test_understand_background_passes_runtime_codex_settings(repository, capsys, monkeypatch):
    target = SemanticServiceTarget(
        "http://127.0.0.1:9999",
        17,
        "Sample",
        "/repo",
        config_authority={
            "registry_key": "sample",
            "service_config_path": "/repo/.anaxigraph.yml",
        },
        semantic_policy={
            "enabled": True,
            "provider": "agent",
            "max_parallel_jobs": 8,
        },
    )
    captured = {}

    def launch(args, selected_repository, execution, mode, service):
        captured.update(
            repository=selected_repository,
            model=execution.model,
            effort=execution.reasoning_effort,
            parallel_jobs=execution.max_parallel_jobs,
            mode=mode,
            service=service,
        )
        return {"status": "running", "complete": False}

    monkeypatch.setattr(semantic_commands, "discover_semantic_service", lambda *_a, **_k: target)
    monkeypatch.setattr(semantic_commands, "launch_understand_background", launch)
    monkeypatch.setattr(semantic_execution.shutil, "which", lambda command: f"/bin/{command}")

    result = _call(
        [
            "understand",
            str(repository),
            "--executor",
            "codex",
            "--model",
            "gpt-5.6-terra",
            "--reasoning-effort",
            "medium",
            "--parallel-jobs",
            "30",
            "--background",
            "--json",
        ],
        capsys,
    )

    assert result == {"status": "running", "complete": False}
    assert captured == {
        "repository": repository.resolve(),
        "model": "gpt-5.6-terra",
        "effort": "medium",
        "parallel_jobs": 8,
        "mode": "codex",
        "service": target,
    }


def test_understand_disabled_service_names_authoritative_policy(repository, capsys, monkeypatch):
    target = SemanticServiceTarget(
        "http://127.0.0.1:9999",
        17,
        "Sample",
        "/repo",
        config_authority={
            "registry_key": "sample",
            "service_config_path": "/config/policies/sample.yml",
        },
        semantic_policy={"enabled": False, "provider": "agent"},
    )
    monkeypatch.setattr(semantic_commands, "discover_semantic_service", lambda *_a, **_k: target)

    with pytest.raises(SystemExit, match="2"):
        main(["understand", str(repository), "--executor", "mcp", "--json"])

    error = capsys.readouterr().err
    assert "/config/policies/sample.yml" in error
    assert "registry key 'sample'" in error


def test_understand_reports_scan_required_without_opening_mcp(repository, capsys, monkeypatch):
    target = SemanticServiceTarget(
        "http://127.0.0.1:9999",
        17,
        "Sample",
        "/repo",
        semantic_policy={"enabled": True, "provider": "agent"},
    )
    monkeypatch.setattr(semantic_commands, "discover_semantic_service", lambda *_a, **_k: target)
    monkeypatch.setattr(
        semantic_commands,
        "prepare_semantic_service",
        lambda *_a, **_k: {
            "status": "scan_required",
            "recommended_action": "Run the explicit repository scan.",
        },
    )
    monkeypatch.setattr(
        semantic_commands,
        "execute_remote_semantics",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("MCP execution started")),
    )

    result = _call(
        ["understand", str(repository), "--executor", "mcp", "--json"],
        capsys,
    )

    assert result["status"] == "scan_required"
    assert result["complete"] is False
    assert result["recommended_action"] == "Run the explicit repository scan."


def test_pattern_query_uses_the_matching_authoritative_service(repository, capsys, monkeypatch):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 17, "Sample", "/repo")
    captured = {}

    monkeypatch.setattr(
        "anaxigraph.cli_pattern_calibration.discover_semantic_service",
        lambda *_a, **_k: target,
    )

    def query_service(service, request, *, snapshot_id=None):
        captured.update(
            service=service,
            target=request.target,
            limit=request.limit,
            snapshot_id=snapshot_id,
        )
        return {"contract_version": "pattern-query-v1", "total": 1, "items": [{}]}

    monkeypatch.setattr(
        "anaxigraph.cli_pattern_calibration.service_pattern_evaluations", query_service
    )
    result = _call(
        [
            "patterns",
            str(repository),
            "--service-url",
            target.base_url,
            "--target",
            "module:pkg/core.py",
            "--snapshot-id",
            "7",
            "--limit",
            "1",
            "--json",
        ],
        capsys,
    )

    assert result["index"] == target.identity()
    assert captured == {
        "service": target,
        "target": "module:pkg/core.py",
        "limit": 1,
        "snapshot_id": 7,
    }


def test_until_complete_cannot_return_a_successful_partial_result():
    args = argparse.Namespace(until_complete=True)
    result = {
        "complete": False,
        "semantic": {"jobs": {"pending": 3, "retry": 1, "running": 0, "failed": 0}},
    }

    with pytest.raises(RuntimeError, match="pending=3, retry=1"):
        semantic_commands._require_requested_completion(args, result)


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
    assert created[0]["scan_on_start"] is False
    assert runs == [(application, "0.0.0.0", 9123, "info")]
    assert opened == ["http://127.0.0.1:9123"]
    assert "Dashboard: http://127.0.0.1:9123" in capsys.readouterr().err


def test_registry_service_scans_on_start_without_relying_on_a_compose_flag(
    repository: Path,
    tmp_path: Path,
    monkeypatch,
):
    registry = tmp_path / "repositories.yml"
    registry.write_text(
        yaml.safe_dump({"repositories": {"sample": {"path": str(repository)}}}),
        encoding="utf-8",
    )
    created: list[dict] = []
    monkeypatch.setattr(cli_services, "APP_FACTORY", lambda **options: created.append(options))
    monkeypatch.setattr(server_commands.uvicorn, "run", lambda *_args, **_options: None)

    main(
        [
            "serve",
            "--registry",
            str(registry),
            "--db",
            str(tmp_path / "registry.db"),
        ]
    )

    assert created[0]["scan_on_start"] is True
    assert created[0]["repository_targets"][0].path == repository.resolve()


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
