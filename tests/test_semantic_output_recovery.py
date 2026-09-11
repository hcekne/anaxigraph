"""Complex mappings stay complete; token recovery is bounded and fully accounted for."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from semantic_support import _agent_dossier

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import ClaudeSemanticProvider, CommandSemanticProvider
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_request_analysis import analyze_semantic_request
from anaxigraph.semantic_request_support import MAPPING_SCHEMA, compact_dossier
from anaxigraph.semantic_taxonomy_contract import validated_semantic_response

REQUEST = {"analysis_kind": "context", "detailed_reviews": False, "max_output_tokens": 4_000}


def test_complex_mapping_can_exceed_the_writing_target_without_losing_contracts():
    value = {
        "summary": "Coordinates order validation, reservation, payment, and rollback. " * 15,
        "responsibilities": [f"Handle order stage {index}." for index in range(6)],
        "public_contracts": [
            f"Stage {index} preserves its existing caller guarantee. " * 6 for index in range(6)
        ],
        "evidence": [f"orders/stage_{index}.py::validate" for index in range(6)],
        "confidence": 0.8,
    }
    result = validated_semantic_response(value, REQUEST)
    assert set(result.value) == set(MAPPING_SCHEMA["required"])
    assert compact_dossier(result.value) == value


def _response(*, truncated=False, invalid=False):
    return SimpleNamespace(
        returncode=0,
        stderr="",
        stdout=json.dumps(
            {
                "stop_reason": "max_tokens" if truncated else "end_turn",
                "structured_output": {"summary": "partial"}
                if invalid or truncated
                else _agent_dossier(REQUEST),
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4_000 if truncated else 120,
                    "cache_read_input_tokens": 3,
                },
            }
        ),
    )


def test_confirmed_cutoff_retries_with_headroom_and_counts_both_calls(monkeypatch):
    calls = []

    def run(_command, **options):
        calls.append(options)
        return _response(truncated=len(calls) == 1)

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    config = SemanticConfig(provider="claude")
    result = analyze_semantic_request(ClaudeSemanticProvider(config), REQUEST, config)
    assert [call["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] for call in calls] == ["4000", "8000"]
    assert '"detailed_reviews":false' in calls[1]["input"]
    assert result.input_tokens == 26
    assert result.output_tokens == 4_120
    assert result.cache_read_input_tokens == 6
    assert result.usage_reported
    assert set(result.value) == set(MAPPING_SCHEMA["required"])


@pytest.mark.parametrize("retry_ceiling,expected_calls", [(8_000, 2), (4_000, 1)])
def test_recovery_stops_at_its_configured_ceiling_and_keeps_failed_usage(
    monkeypatch, retry_ceiling, expected_calls
):
    calls = []

    def run(_command, **options):
        calls.append(options)
        return _response(truncated=True)

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    config = SemanticConfig(provider="claude", max_output_tokens_on_retry=retry_ceiling)
    with pytest.raises(SemanticAnalysisError) as caught:
        analyze_semantic_request(ClaudeSemanticProvider(config), REQUEST, config)
    assert len(calls) == expected_calls
    assert caught.value.output_truncated
    assert caught.value.input_tokens == 13 * expected_calls
    assert caught.value.cache_read_input_tokens == 3 * expected_calls


def test_invalid_shape_does_not_trigger_an_extra_headroom_call(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "anaxigraph.semantic.subprocess.run",
        lambda *a, **k: calls.append(k) or _response(invalid=True),
    )
    config = SemanticConfig(provider="claude")
    with pytest.raises(SemanticAnalysisError):
        analyze_semantic_request(ClaudeSemanticProvider(config), REQUEST, config)
    assert len(calls) == 1


def test_command_adapter_recognizes_explicit_cutoff_and_preserves_usage(monkeypatch):
    calls = []

    def run(_command, **options):
        calls.append(json.loads(options["input"]))
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "stop_reason": "max_tokens" if len(calls) == 1 else "end_turn",
                    "dossier": _agent_dossier(REQUEST),
                    "usage": {"input_tokens": 50, "output_tokens": 100},
                }
            ),
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    config = SemanticConfig(provider="command", command=("test-worker",))
    result = analyze_semantic_request(CommandSemanticProvider(config), REQUEST, config)
    assert [call["max_output_tokens"] for call in calls] == [4_000, 8_000]
    assert result.input_tokens == 100
    assert result.output_tokens == 200


@pytest.mark.parametrize("returncode", [0, 1])
def test_claude_cli_token_error_is_recognized_even_without_stop_reason(monkeypatch, returncode):
    calls = []

    def run(_command, **options):
        calls.append(options)
        if len(calls) > 1:
            return _response()
        return SimpleNamespace(
            returncode=returncode,
            stderr="",
            stdout=json.dumps(
                {
                    "is_error": True,
                    "errors": ["Claude's response exceeded the 4000 output token maximum."],
                    "usage": {"input_tokens": 12, "output_tokens": 4_000},
                }
            ),
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    config = SemanticConfig(provider="claude")
    result = analyze_semantic_request(ClaudeSemanticProvider(config), REQUEST, config)
    assert len(calls) == 2
    assert result.input_tokens == 25
