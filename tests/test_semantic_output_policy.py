"""Executor output allowances stay native unless a caller explicitly sets a cap."""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from semantic_support import _agent_dossier

from anaxigraph.config import SemanticConfig, semantic_config_from_mapping
from anaxigraph.semantic import ClaudeSemanticProvider
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_request_analysis import analyze_semantic_request
from anaxigraph.semantic_taxonomy_partition import needs_partition, partition_limit


@pytest.mark.parametrize(
    "configured", [{}, {"max_output_tokens": None, "max_output_tokens_on_retry": None}]
)
def test_native_output_policy_round_trips_through_remote_transport(configured):
    config = semantic_config_from_mapping(configured)
    assert config.max_output_tokens is None
    assert config.max_output_tokens_on_retry is None
    assert semantic_config_from_mapping(asdict(config)) == config
    assert needs_partition({}, config, 100)
    assert partition_limit(config) < 100


@pytest.mark.parametrize("key", ["max_output_tokens", "max_output_tokens_on_retry"])
def test_explicit_output_caps_remain_validated(key):
    assert getattr(semantic_config_from_mapping({key: 48_000}), key) == 48_000
    with pytest.raises(ValueError, match=key):
        semantic_config_from_mapping({key: 255})


@pytest.mark.parametrize("inherited", [None, "64000"])
@pytest.mark.parametrize("kind", ["context", "taxonomy_review", "synthesis"])
def test_claude_uses_native_or_inherited_output_allowance(monkeypatch, inherited, kind):
    if inherited is None:
        monkeypatch.delenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", inherited)
    request = {
        "analysis_kind": kind,
        "detailed_reviews": False,
        "scope_type": "group",
        "modules": [{"path": "core.py"}],
    }
    value = _agent_dossier(request)
    value["summary"] = "Complete structured review with evidence. " * 9_000
    calls = []

    def run(command, **options):
        calls.append(options)
        assert options["env"].get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") == inherited
        payload = json.loads(options["input"].split("ANAXIGRAPH_PAYLOAD\n", 1)[1])
        assert "max_output_tokens" not in payload
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "structured_output": value,
                    "usage": {"input_tokens": 100, "output_tokens": 12_345},
                }
            ),
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    config = SemanticConfig(provider="claude")
    result = analyze_semantic_request(ClaudeSemanticProvider(config), request, config)
    assert len(calls) == 1
    assert result.value["summary"] == value["summary"]
    assert result.output_tokens == 12_345


def test_native_truncation_does_not_retry_with_an_invented_cap(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", raising=False)
    calls = []

    def run(command, **options):
        calls.append(options)
        return SimpleNamespace(
            returncode=1,
            stderr="",
            stdout=json.dumps(
                {
                    "is_error": True,
                    "result": "Claude's response exceeded the 128000 output token maximum.",
                    "usage": {"input_tokens": 40, "output_tokens": 128_000},
                }
            ),
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    config = SemanticConfig(provider="claude")
    with pytest.raises(SemanticAnalysisError) as caught:
        analyze_semantic_request(
            ClaudeSemanticProvider(config), {"analysis_kind": "context"}, config
        )
    assert len(calls) == 1
    assert caught.value.output_truncated
    assert caught.value.output_tokens == 128_000
