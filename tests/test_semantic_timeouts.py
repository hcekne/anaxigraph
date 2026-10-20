"""Long model calls, explicit deadlines, and readable historical failures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from semantic_support import _agent_dossier

from anaxigraph.config import SemanticConfig, semantic_config_from_mapping
from anaxigraph.semantic import (
    ClaudeSemanticProvider,
    CodexSemanticProvider,
    CommandSemanticProvider,
)
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_timeouts import readable_failure


@pytest.mark.parametrize("policy", [{}, {"timeout_seconds": None}, {"timeout_seconds": 420}])
def test_model_deadlines_are_opt_in_and_survive_policy_transport(policy):
    config = semantic_config_from_mapping(policy)
    assert config.timeout_seconds == policy.get("timeout_seconds")
    transported = semantic_config_from_mapping({"timeout_seconds": config.timeout_seconds})
    assert transported.timeout_seconds == config.timeout_seconds


@pytest.mark.parametrize("value", [0, -1])
def test_explicit_model_deadline_must_be_positive(value):
    with pytest.raises(ValueError, match="semantic.timeout_seconds must be at least 1"):
        semantic_config_from_mapping({"timeout_seconds": value})


@pytest.mark.parametrize(
    ("provider", "name"),
    [
        (ClaudeSemanticProvider, "Claude"),
        (CodexSemanticProvider, "Codex"),
        (CommandSemanticProvider, "Semantic command"),
    ],
)
def test_timeout_reports_model_stage_and_partition_instead_of_command(monkeypatch, provider, name):
    def run(command, **options):
        assert options["timeout"] == 420
        raise subprocess.TimeoutExpired(command + ["sensitive payload " * 500], 420)

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    config = SemanticConfig(timeout_seconds=420, model="test-model", command=("fixture",))
    with pytest.raises(SemanticAnalysisError) as raised:
        provider(config).analyze(
            {"analysis_kind": "taxonomy_review_chunk", "chunk": {"index": 3, "total": 30}}
        )
    message = str(raised.value)
    assert message.startswith(f"{name} (test-model) timed out after 420 seconds")
    assert "taxonomy review chunk (partition 3/30)" in message
    assert "semantic.timeout_seconds" in message
    assert "null" in message
    assert len(message) < 400
    assert "sensitive payload" not in message and "--json-schema" not in message


@pytest.mark.parametrize("deadline", [None, 420])
def test_claude_call_uses_optional_deadline_without_other_output_limits(monkeypatch, deadline):
    request = {
        "analysis_kind": "taxonomy_review",
        "candidate_taxonomy": {
            "summary": "Test map",
            "areas": [],
            "facets": [],
            "confidence": 0.8,
            "evidence": [],
        },
    }
    expected = _agent_dossier(request)
    monkeypatch.delenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", raising=False)

    def run(command, **options):
        assert options["timeout"] == deadline
        assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in options["env"]
        assert "--model" in command and "--effort" in command
        return SimpleNamespace(
            returncode=0, stderr="", stdout=json.dumps({"structured_output": expected})
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    result = ClaudeSemanticProvider(
        SemanticConfig(timeout_seconds=deadline, model="test-model", reasoning_effort="max")
    ).analyze(request)
    assert result.value == expected


@pytest.mark.parametrize("provider", ["Claude", "Codex", "Semantic command"])
def test_legacy_timeout_dump_keeps_cause_before_display_truncation(provider):
    prefix = (
        f"{provider} semantic run failed"
        if provider != "Semantic command"
        else f"{provider} failed"
    )
    legacy = f"SemanticAnalysisError: {prefix}: {subprocess.TimeoutExpired(['cli', 'schema' * 1000], 300)}"
    assert len(legacy) > 1000
    message = readable_failure(legacy)
    assert message.startswith(f"{provider} timed out after 300 seconds")
    assert len(message) < 400
    assert "schema" not in message


def test_unrelated_failures_are_preserved_and_bounded():
    assert readable_failure(None) is None
    assert readable_failure("Claude exited with 1: API error") == "Claude exited with 1: API error"
    assert readable_failure("x" * 2000) == "x" * 1000


@pytest.mark.parametrize("deadline", [None, 1])
def test_claude_subprocess_can_finish_or_obey_an_explicit_deadline(tmp_path, monkeypatch, deadline):
    """Exercise real process waiting and termination with a local fake CLI, never a model."""
    executable = tmp_path / "claude"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        "request = json.loads(sys.stdin.read().split('ANAXIGRAPH_PAYLOAD\\n', 1)[1])\n"
        "time.sleep(1.2)\n"
        "print(json.dumps({'structured_output': {'verdict': 'approve', 'summary': 'Reviewed', "
        "'taxonomy': request['candidate_taxonomy'], 'issues': [], 'confidence': 0.8, "
        "'evidence': []}, 'usage': {'input_tokens': 100, 'output_tokens': 20}}))\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    request = {
        "analysis_kind": "taxonomy_review",
        "candidate_taxonomy": {
            "summary": "Test map",
            "areas": [],
            "facets": [],
            "confidence": 0.8,
            "evidence": [],
        },
    }
    provider = ClaudeSemanticProvider(SemanticConfig(timeout_seconds=deadline))
    if deadline is not None:
        with pytest.raises(SemanticAnalysisError, match="Claude timed out after 1 seconds"):
            provider.analyze(request)
    else:
        result = provider.analyze(request)
        assert result.value["verdict"] == "approve"
        assert result.input_tokens == 100
        assert result.output_tokens == 20
