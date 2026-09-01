from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import anaxigraph.cli_semantic_commands as semantic_commands
import anaxigraph.cli_server_commands as server_commands
import anaxigraph.cli_services as cli_services
import anaxigraph.repository_watch as repository_watch
import anaxigraph.semantic_execution as semantic_execution
from anaxigraph.cli import main
from anaxigraph.cli_common import default_db
from anaxigraph.registry import RepositoryTarget
from anaxigraph.semantic_service import SemanticServiceTarget


def _call(arguments: list[str], capsys) -> dict:
    main(arguments)
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_registry_watcher_refreshes_history_once_per_new_git_head(repository, monkeypatch):
    target = RepositoryTarget("sample", repository, history_snapshots=8)
    heads = iter(("first", "first", "second"))
    calls = []
    service = SimpleNamespace(
        database=SimpleNamespace(repository=lambda _path: {"id": 1}),
        latest_imported_commit=lambda _repository_id: "first",
        status=lambda _repository_id: {
            "status": "complete",
            "result": {"latest_commit": "first"},
        },
        start=lambda value, **options: calls.append((value.key, options)),
    )
    monkeypatch.setattr(repository_watch.git, "has_commits", lambda _path: True)
    monkeypatch.setattr(
        repository_watch.git,
        "metadata",
        lambda _path: SimpleNamespace(commit_sha=next(heads)),
    )
    watcher = repository_watch.RepositoryWatchService(
        service.database,
        (target,),
        interval_seconds=0.2,
        scanner_factory=lambda _database: None,
        config_loader=lambda _path, _config: None,
        semantic_factory=lambda _database: None,
        history_service=service,
    )

    watcher._refresh_history(target)
    watcher._refresh_history(target)
    watcher._refresh_history(target)

    assert calls == [("sample", {"after_revision": "first"})]
    assert watcher._observed_heads == {"sample": "second"}


def test_repository_agent_and_export_handlers_share_the_current_scan(
    repository: Path,
    tmp_path: Path,
    capsys,
):
    database = tmp_path / "commands.db"
    common = [str(repository), "--db", str(database), "--json"]
    scanned = _call(["scan", *common], capsys)
    reviewed = _call(["review", *common, "--status", "all"], capsys)
    scoped = _call(["guide", *common, "--goal", "Change the calculator"], capsys)
    impacted = _call(["impact", *common, "--target", "pkg/core.py"], capsys)
    patterns = _call(["patterns", *common, "--limit", "1"], capsys)
    candidate_explanations = _call(
        ["patterns", *common, "--candidates", "--pattern", "circular-dependency", "--limit", "1"],
        capsys,
    )
    charter = _call(["charter", *common], capsys)
    corrected_charter = _call(
        [
            "charter",
            *common,
            "--correct-section",
            "purpose",
            "--statement",
            "Provide sample calculator behavior.",
            "--author",
            "test owner",
            "--rationale",
            "The source map alone cannot establish the intended user outcome.",
        ],
        capsys,
    )
    exported = _call(["export", *common], capsys)

    assert scanned["status"] == "ok"
    assert "finding_page" in reviewed
    assert scoped["goal"] == "Change the calculator"
    assert scoped["architecture_decision"]["verification"]["rescan_argv"]
    assert impacted["target"]["path"] == "pkg/core.py"
    assert patterns["contract_version"] == "pattern-query-v1"
    assert patterns["index"]["authority"] == "local"
    assert patterns["total"] == 0
    assert candidate_explanations["contract_version"] == "pattern-candidate-query-v1"
    assert charter["contract_version"] == "architecture-charter-v1"
    assert charter["state"] == "provisional"
    assert charter["complete"] is False
    assert charter["responsibilities"]
    assert (
        corrected_charter["purpose"]["statement"]
        != (corrected_charter["purpose"]["presented_statement"])
    )
    assert corrected_charter["declared_context"][0]["author"] == "test owner"
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


def test_search_command_uses_the_shared_ranked_projection(repository: Path, tmp_path: Path, capsys):
    database = tmp_path / "search.db"

    main(["scan", str(repository), "--db", str(database), "--json"])
    capsys.readouterr()
    main(["search", "Calculator", str(repository), "--db", str(database), "--json"])
    result = json.loads(capsys.readouterr().out)

    assert result["query"] == "Calculator"
    assert result["results"][0]["path"] == "pkg/core.py"
    assert result["results"][0]["search"]["contract_version"] == "module-search-fts-v1"


def test_semantic_handlers_plan_report_and_resume(repository: Path, tmp_path: Path, capsys):
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

    assert planned["semantic"]["enabled"] is True
    assert planned["status"] == "planned"
    assert requires_agent["status"] == "agent_action_required"
    assert requires_agent["complete"] is False
    assert requires_agent["next_action"]["kind"] == "connected_agent_semantic_loop"
    assert "must not report" in requires_agent["next_action"]["instruction"]
    assert status["enabled"] is True


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
        "anaxigraph.cli_pattern_commands.discover_semantic_service",
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
        "anaxigraph.cli_pattern_commands.service_pattern_evaluations", query_service
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
    assert created[0]["watch_interval"] == 10.0
    assert runs == [(application, "0.0.0.0", 9123, "info")]
    assert opened == ["http://127.0.0.1:9123"]
    assert "Dashboard: http://127.0.0.1:9123" in capsys.readouterr().err


def test_registry_service_does_not_force_a_blocking_startup_scan(
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

    assert created[0]["scan_on_start"] is False
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
