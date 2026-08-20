from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from anaxigraph.onboarding_clients import (
    client_connection_status,
    configure_client,
)


def test_codex_user_connection_preserves_unrelated_toml_and_is_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    original = '# personal preference\nmodel = "gpt-test"\n\n[mcp_servers.other]\nurl = "https://example.test/mcp"\n'
    config.write_text(original, encoding="utf-8")

    result = configure_client(
        "codex",
        scope="user",
        repository=tmp_path,
        mcp_url="http://127.0.0.1:9123/mcp",
        home=home,
        environment={},
    )

    assert result["action"] == "updated"
    assert Path(result["backup"]).read_text(encoding="utf-8") == original
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600
    content = config.read_text(encoding="utf-8")
    assert "# personal preference" in content
    parsed = tomllib.loads(content)
    assert parsed["model"] == "gpt-test"
    assert parsed["mcp_servers"]["other"]["url"] == "https://example.test/mcp"
    assert parsed["mcp_servers"]["anaxigraph"]["url"] == "http://127.0.0.1:9123/mcp"
    assert config.stat().st_mode & 0o777 == 0o600

    backups = list(config.parent.glob("config.toml.anaxigraph-*.bak"))
    repeated = configure_client(
        "codex",
        scope="user",
        repository=tmp_path,
        mcp_url="http://127.0.0.1:9123/mcp",
        home=home,
        environment={},
    )
    assert repeated["action"] == "unchanged"
    assert repeated["backup"] is None
    assert list(config.parent.glob("config.toml.anaxigraph-*.bak")) == backups


def test_codex_project_dry_run_previews_without_creating_config(tmp_path: Path):
    result = configure_client(
        "codex",
        scope="project",
        repository=tmp_path,
        mcp_url="http://127.0.0.1:8765/mcp",
        dry_run=True,
    )

    assert result["action"] == "would_create"
    assert result["path"] == str(tmp_path / ".codex/config.toml")
    assert not (tmp_path / ".codex").exists()


def test_claude_project_connection_preserves_other_servers_and_owned_fields(tmp_path: Path):
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps(
            {
                "projectNote": "preserve me",
                "mcpServers": {
                    "other": {"type": "http", "url": "https://example.test/mcp"},
                    "anaxigraph": {"type": "http", "url": "http://old.test/mcp", "x": 1},
                },
            }
        ),
        encoding="utf-8",
    )

    result = configure_client(
        "claude",
        scope="project",
        repository=tmp_path,
        mcp_url="http://127.0.0.1:8765/mcp",
    )

    assert result["action"] == "updated"
    assert Path(result["backup"]).is_file()
    parsed = json.loads(config.read_text(encoding="utf-8"))
    assert parsed["projectNote"] == "preserve me"
    assert parsed["mcpServers"]["other"]["url"] == "https://example.test/mcp"
    assert parsed["mcpServers"]["anaxigraph"] == {
        "type": "http",
        "url": "http://127.0.0.1:8765/mcp",
        "x": 1,
    }
    status = client_connection_status(
        "claude",
        scope="project",
        repository=tmp_path,
        expected_url="http://127.0.0.1:8765/mcp",
    )
    assert status["status"] == "configured"


def test_claude_user_connection_is_private_and_global(tmp_path: Path):
    home = tmp_path / "home"
    result = configure_client(
        "claude",
        scope="user",
        repository=tmp_path,
        mcp_url="http://127.0.0.1:8765/mcp",
        home=home,
    )

    config = home / ".claude.json"
    assert result["path"] == str(config)
    assert result["action"] == "created"
    assert config.stat().st_mode & 0o777 == 0o600
    assert json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["anaxigraph"] == {
        "type": "http",
        "url": "http://127.0.0.1:8765/mcp",
    }


def test_client_connection_rejects_credentials_and_symlinked_configuration(tmp_path: Path):
    with pytest.raises(ValueError, match="credentials"):
        configure_client(
            "codex",
            scope="project",
            repository=tmp_path,
            mcp_url="http://user:secret@127.0.0.1:8765/mcp",
        )

    target = tmp_path / "real-config.toml"
    target.write_text("", encoding="utf-8")
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.symlink_to(target)
    with pytest.raises(ValueError, match="symlinked"):
        configure_client(
            "codex",
            scope="project",
            repository=tmp_path,
            mcp_url="http://127.0.0.1:8765/mcp",
        )
