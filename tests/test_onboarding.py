from __future__ import annotations

import json
from pathlib import Path

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
    assert policy["project"]["name"] == "Sample Observatory"
    assert policy["coverage"] == {"required": False, "files": ["coverage.xml"]}
    assert policy["groups"]["frontend"]["paths"] == ["web/**"]
    assert policy["semantic"]["provider"] == "agent"
    assert "model" not in policy["semantic"]
    assert policy["semantic"]["agent_lease_seconds"] == 1_800
    assert load_config(repository).project_name == "Sample Observatory"
    assert "source: ." in compose
    assert "target: /repo" in compose
    assert "read_only: true" in compose
    assert '"127.0.0.1:${ANAXIGRAPH_PORT:-9123}:8765"' in compose
    assert "--history-snapshots\n      - \"37\"" in compose
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
