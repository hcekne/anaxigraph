from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from anaxigraph.cli import main
from anaxigraph.config import load_config
from anaxigraph.onboarding import initialize_repository


def test_initializer_generates_reviewable_policy_and_read_only_sidecar(repository: Path):
    (repository / ".anaxigraph.yml").unlink()
    (repository / "ignored" / "secret.py").unlink()
    (repository / "ignored").rmdir()
    result = initialize_repository(
        repository,
        project_name="Sample Observatory",
        port=9123,
        history_snapshots=37,
    )

    assert result["project_name"] == "Sample Observatory"
    assert result["detected"]["groups"] == [
        "frontend",
        "pkg",
        "testing",
        "documentation",
    ]
    assert result["detected"]["architecture_policy"] == "docs/architecture.md"
    assert result["detected"]["coverage_files"] == ["coverage.xml"]
    assert [item["action"] for item in result["files"]] == ["created", "created"]

    policy_path = repository / ".anaxigraph.yml"
    compose_path = repository / "compose.anaxigraph.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    compose = compose_path.read_text(encoding="utf-8")
    compose_config = yaml.safe_load(compose)
    assert policy["project"]["name"] == "Sample Observatory"
    assert policy["coverage"] == {"required": False, "files": ["coverage.xml"]}
    assert policy["groups"]["frontend"]["paths"] == ["web/**"]
    assert policy["semantic"]["provider"] == "agent"
    assert policy["semantic"]["refresh"] == "on_scan"
    assert "model" not in policy["semantic"]
    assert policy["semantic"]["agent_lease_seconds"] == 1_800
    assert load_config(repository).project_name == "Sample Observatory"
    assert "source: ." in compose
    assert "target: /repo" in compose
    assert "read_only: true" in compose
    assert '"127.0.0.1:${ANAXIGRAPH_PORT:-9123}:8765"' in compose
    assert '--history-snapshots\n      - "37"' in compose
    assert set(compose_config["services"]) == {"anaxigraph"}
    assert compose_config["x-anaxigraph-service"]["environment"] == {
        "ANAXIGRAPH_WATCH_INTERVAL": "${ANAXIGRAPH_WATCH_INTERVAL:-10}"
    }
    assert compose_config["x-anaxigraph-service"]["tmpfs"] == [
        "/tmp:size=${ANAXIGRAPH_TMPFS_SIZE:-512m},mode=1777"
    ]
    assert "--scan-on-start" not in compose_config["services"]["anaxigraph"]["command"]
    assert "--allow-agent-scan" in compose_config["services"]["anaxigraph"]["command"]
    assert "start_with_watch" not in result["commands"]
    assert result["commands"]["connect_codex"] == (
        "codex mcp add anaxigraph --url http://127.0.0.1:9123/mcp"
    )


def test_initializer_never_overwrites_without_force(repository: Path):
    config = repository / ".anaxigraph.yml"
    compose = repository / "compose.anaxigraph.yml"
    config.write_text("project:\n  name: Hand edited\n", encoding="utf-8")
    compose.write_text("services: {}\n", encoding="utf-8")

    result = initialize_repository(repository, project_name="Replacement")
    assert [item["action"] for item in result["files"]] == ["skipped", "skipped"]
    assert "Hand edited" in config.read_text(encoding="utf-8")
    assert compose.read_text(encoding="utf-8") == "services: {}\n"

    forced = initialize_repository(repository, project_name="Replacement", force=True)
    assert [item["action"] for item in forced["files"]] == [
        "overwritten",
        "overwritten",
    ]
    assert load_config(repository).project_name == "Replacement"
    assert '--history-snapshots\n      - "auto"' in compose.read_text(encoding="utf-8")


def test_initializer_dry_run_and_json_cli_do_not_write(repository: Path, capsys):
    (repository / ".anaxigraph.yml").unlink()
    main(
        [
            "init",
            str(repository),
            "--project-name",
            "Sample Observatory",
            "--dry-run",
            "--json",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "dry_run"
    assert [item["action"] for item in result["files"]] == [
        "would_create",
        "would_create",
    ]
    assert not (repository / ".anaxigraph.yml").exists()
    assert not (repository / "compose.anaxigraph.yml").exists()


def test_initializer_can_generate_local_policy_only(repository: Path):
    (repository / ".anaxigraph.yml").unlink()
    result = initialize_repository(
        repository,
        project_name="Sample Observatory",
        compose_name=None,
    )

    assert len(result["files"]) == 1
    assert result["commands"]["start"] is None
    assert not (repository / "compose.anaxigraph.yml").exists()


def test_agent_semantic_option_updates_only_its_existing_policy_block(repository: Path):
    config = repository / ".anaxigraph.yml"
    config.write_text(
        "# preserve this explanation\n"
        "project:\n"
        "  name: Hand Edited\n"
        "semantic:\n"
        "  enabled: false  # old choice\n"
        "  provider: command\n"
        "  model: custom-model\n",
        encoding="utf-8",
    )

    result = initialize_repository(repository, compose_name=None, semantic_mode="agent")

    assert result["files"][0]["action"] == "updated"
    content = config.read_text(encoding="utf-8")
    assert "# preserve this explanation" in content
    assert "model: custom-model" in content
    policy = yaml.safe_load(content)
    assert policy["project"]["name"] == "Hand Edited"
    assert policy["semantic"]["enabled"] is True
    assert policy["semantic"]["provider"] == "agent"

    repeated = initialize_repository(repository, compose_name=None, semantic_mode="agent")
    assert repeated["files"][0]["action"] == "unchanged"
    assert config.read_text(encoding="utf-8") == content


def test_cli_previews_semantics_and_project_connection_without_writing(repository: Path, capsys):
    (repository / ".anaxigraph.yml").unlink()

    main(
        [
            "init",
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
    assert result["semantic"]["enabled"] is True
    assert result["connections"][0]["action"] == "would_create"
    assert result["connections"][0]["path"].endswith("/.codex/config.toml")
    assert not (repository / ".anaxigraph.yml").exists()
    assert not (repository / ".codex").exists()


def test_cli_semantic_and_project_connection_are_safe_to_repeat(repository: Path, capsys):
    arguments = [
        "init",
        str(repository),
        "--no-compose",
        "--semantic",
        "agent",
        "--connect",
        "codex",
        "--connect-scope",
        "project",
        "--json",
    ]

    main(arguments)
    created = json.loads(capsys.readouterr().out)
    policy_content = (repository / ".anaxigraph.yml").read_text(encoding="utf-8")
    client_content = (repository / ".codex/config.toml").read_text(encoding="utf-8")
    assert created["files"][0]["action"] == "updated"
    assert created["connections"][0]["action"] == "created"

    main(arguments)
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["files"][0]["action"] == "unchanged"
    assert repeated["connections"][0]["action"] == "unchanged"
    assert (repository / ".anaxigraph.yml").read_text(encoding="utf-8") == policy_content
    assert (repository / ".codex/config.toml").read_text(encoding="utf-8") == client_content


def test_cli_prints_the_selected_connection_and_semantic_next_step(repository: Path, capsys):
    main(
        [
            "init",
            str(repository),
            "--no-compose",
            "--semantic",
            "agent",
            "--connect",
            "claude",
            "--connect-scope",
            "project",
        ]
    )

    output = capsys.readouterr().out
    assert "claude MCP" in output
    assert "Restart the configured coding client" in output
    assert "Bootstrap or resume AnaxiGraph semantic understanding" in output
    assert "coding agent supplies the reasoning and tokens" in output


def test_cli_start_runs_the_generated_compose_service(repository: Path, monkeypatch, capsys):
    calls: list[tuple[list[str], str]] = []
    original_run = subprocess.run

    def run(command, **options):
        if command[0] == "git":
            return original_run(command, **options)
        cwd = options["cwd"]
        calls.append((command, cwd))
        assert options["check"] is False
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("anaxigraph.onboarding_cli.subprocess.run", run)
    main(["init", str(repository), "--start", "--json"])

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "started"
    assert calls == [
        (["docker", "compose", "-f", "compose.anaxigraph.yml", "up", "-d"], str(repository))
    ]


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["--start", "--dry-run"], "--start cannot be combined with --dry-run"),
        (["--start", "--no-compose"], "--start requires a generated Compose file"),
    ],
)
def test_cli_rejects_incompatible_start_modes(
    repository: Path,
    arguments: list[str],
    message: str,
    capsys,
):
    with pytest.raises(SystemExit) as raised:
        main(["init", str(repository), *arguments])

    assert raised.value.code == 2
    assert message in capsys.readouterr().err
