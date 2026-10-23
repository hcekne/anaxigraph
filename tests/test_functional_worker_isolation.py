"""Actual adapter invocations deny repository tools and inherited session configuration."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fresh_eyes_functional_fixtures import functional_result

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import ClaudeSemanticProvider, CodexSemanticProvider, _codex_schema
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_fresh_eyes_functional import capability_projection
from anaxigraph.semantic_fresh_eyes_v2_contract import SCHEMAS


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_fresh_adapter_uses_empty_directory_and_no_source_tools(monkeypatch, tmp_path, provider):
    canary = tmp_path / "private_canary.py"
    canary.write_text("UNRELATED_IMPLEMENTATION_SECRET = True")
    monkeypatch.setenv("CODEX_THREAD_ID", "old-implementation-context")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "old-implementation-context")
    request = {
        "analysis_kind": "fresh_adjudication",
        "protocol_version": "fresh-eyes-recipe-v2",
        "functional_stage": "hierarchy",
        "capability_projection": capability_projection(
            {"purpose": "Complete useful work", "observable_capabilities": ["Run work"]}
        ),
    }
    captured = {}

    def run(command, **kwargs):
        if command[-2:] == ["features", "list"]:
            disabled = [command[i + 1] for i, value in enumerate(command) if value == "--disable"]
            return SimpleNamespace(
                returncode=0,
                stderr="",
                stdout="\n".join(f"{feature} stable false" for feature in disabled),
            )
        if command == ["claude", "--help"]:
            return SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=" ".join(
                    (
                        "--tools",
                        "--safe-mode",
                        "--restricted",
                        "--strict-mcp-config",
                        "--setting-sources",
                        "--system-prompt",
                        "--no-session-persistence",
                    )
                ),
            )
        captured.update(command=command, cwd=kwargs.get("cwd"))
        directory = Path(kwargs["cwd"])
        assert directory != tmp_path and not (directory / canary.name).exists()
        assert str(canary) not in kwargs["input"]
        assert "CODEX_THREAD_ID" not in kwargs["env"]
        assert "CLAUDE_SESSION_ID" not in kwargs["env"]
        value = functional_result(request)
        if provider == "codex":
            Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(value))
            assert command[command.index("--sandbox") + 1] == "read-only"
            for feature in ("shell_tool", "multi_agent", "apps", "view_image", "hooks"):
                assert any(
                    command[i : i + 2] == ["--disable", feature] for i in range(len(command))
                )
            assert "--ephemeral" in command and "--ignore-user-config" in command
            assert "project_doc_max_bytes=0" in command
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        assert command[command.index("--tools") + 1] == ""
        assert "--safe-mode" in command and "--no-session-persistence" in command
        assert "--strict-mcp-config" in command and "--restricted" in command
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"structured_output": value}), stderr=""
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    adapter = CodexSemanticProvider if provider == "codex" else ClaudeSemanticProvider
    adapter(SemanticConfig(provider=provider)).analyze(request)
    assert not Path(captured["cwd"]).exists()


def test_every_functional_schema_remains_strict_wire_compatible():
    def inspect(schema):
        if isinstance(schema, list):
            for child in schema:
                inspect(child)
        elif isinstance(schema, dict):
            if schema.get("type") == "object":
                assert set(schema["required"]) == set(schema["properties"])
                assert schema["additionalProperties"] is False
            for child in schema.values():
                inspect(child)

    for schema in SCHEMAS.values():
        inspect(_codex_schema(schema))


def test_blind_result_cannot_self_attest_verified_isolation():
    from anaxigraph.semantic_fresh_eyes_v2_contract import validate_functional

    hierarchy_request = {
        "functional_stage": "hierarchy",
        "capability_projection": capability_projection({"purpose": "Perform work"}),
    }
    brief = functional_result(hierarchy_request)
    from anaxigraph.semantic_fresh_eyes_functional import functional_scope_packet

    request = {
        "analysis_kind": "fresh_proposal",
        "protocol_version": "fresh-eyes-recipe-v2",
        "functional_stage": "proposal",
        "proposal_slot": "a",
        "functional_scope": functional_scope_packet(brief, "product"),
    }
    value = functional_result(request)
    value["isolation"]["status"] = "verified"
    with pytest.raises(SemanticAnalysisError, match="must be one of"):
        validate_functional(value, request)
