from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import (
    AnthropicSemanticProvider,
    ClaudeSemanticProvider,
    CodexSemanticProvider,
    OpenAISemanticProvider,
)


def _dossier() -> dict[str, Any]:
    return {
        "summary": "Owns repository enrollment.",
        "detailed_summary": "Builds and refreshes the durable understanding baseline.",
        "responsibilities": ["Plan semantic work"],
        "inputs": ["Deterministic graph facts"],
        "outputs": ["Versioned dossiers"],
        "side_effects": ["Writes AnaxiIndex records"],
        "public_contracts": ["Dossier schema v4"],
        "invariants": ["Never overwrite parser facts"],
        "architecture_role": "Repository intelligence service",
        "domain_concepts": ["semantic bootstrap"],
        "collaborators": ["scanner"],
        "overlaps": [],
        "extension_points": ["provider adapter"],
        "similar_modules": [],
        "pattern_opportunities": [
            {
                "name": "Provider adapter",
                "scope": "module",
                "score": 91,
                "confidence": 0.88,
                "rationale": "Multiple model runtimes share one structured contract.",
                "evidence": ["The provider protocol already separates orchestration."],
                "counter_evidence": [],
                "migration_cost": "low",
                "preconditions": ["Keep provider-specific transport outside the engine."],
            }
        ],
        "consolidation_assessment": {
            "recommendation": "keep",
            "score": 89,
            "rationale": "Keep provider adapters separate from orchestration.",
            "candidates": [],
            "evidence": ["Each adapter owns a distinct transport."],
            "counter_evidence": [],
        },
        "dead_code_candidates": [],
        "placement_guidance": "Add model runtimes behind the provider protocol.",
        "testing_guidance": ["Use a JSON-over-stdin fake provider"],
        "change_summary": "No previous dossier was supplied.",
        "risks": ["Model output is an interpretation"],
        "evidence": ["src/anaxigraph/understanding.py:1"],
        "confidence": 0.91,
    }


def test_openai_provider_uses_strict_responses_schema(monkeypatch):
    captured = {}

    def post(url, payload, *, headers, timeout):
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(_dossier())}],
                }
            ],
            "usage": {"input_tokens": 120, "output_tokens": 80},
        }

    monkeypatch.setenv("TEST_OPENAI_KEY", "secret")
    monkeypatch.setattr("anaxigraph.semantic._post_json", post)
    provider = OpenAISemanticProvider(
        SemanticConfig(
            enabled=True,
            provider="openai",
            model="gpt-test",
            api_key_env="TEST_OPENAI_KEY",
        )
    )

    result = provider.analyze({"analysis_kind": "intrinsic", "source": "untrusted source"})

    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["payload"]["store"] is False
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert captured["payload"]["text"]["format"]["schema"]["additionalProperties"] is False
    assert (
        captured["payload"]["text"]["format"]["schema"]["properties"]["pattern_opportunities"][
            "items"
        ]["additionalProperties"]
        is False
    )
    assert result.value["placement_guidance"].startswith("Add model runtimes")
    assert result.value["pattern_opportunities"][0]["score"] == 91
    assert result.input_tokens == 120
    assert result.output_tokens == 80


def test_anthropic_provider_uses_structured_output_config(monkeypatch):
    captured = {}

    def post(url, payload, *, headers, timeout):
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {
            "content": [{"type": "text", "text": json.dumps(_dossier())}],
            "usage": {"input_tokens": 90, "output_tokens": 60},
        }

    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "secret")
    monkeypatch.setattr("anaxigraph.semantic._post_json", post)
    provider = AnthropicSemanticProvider(
        SemanticConfig(
            enabled=True,
            provider="anthropic",
            model="claude-test",
            api_key_env="TEST_ANTHROPIC_KEY",
        )
    )

    result = provider.analyze({"analysis_kind": "context", "source": "untrusted source"})

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["payload"]["output_config"]["format"]["type"] == "json_schema"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert result.confidence == 0.91
    assert result.input_tokens == 90


def test_codex_provider_is_ephemeral_read_only_and_schema_constrained(monkeypatch):
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        schema_path = Path(command[command.index("--output-schema") + 1])
        assert json.loads(schema_path.read_text(encoding="utf-8"))["additionalProperties"] is False
        return SimpleNamespace(returncode=0, stdout=json.dumps(_dossier()), stderr="")

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    result = CodexSemanticProvider(
        SemanticConfig(
            enabled=True,
            provider="codex",
            model="gpt-test",
            reasoning_effort="medium",
        )
    ).analyze({"analysis_kind": "intrinsic", "source": "print('data')"})

    assert captured["command"][:2] == ["codex", "exec"]
    assert "--ephemeral" in captured["command"]
    assert captured["command"][captured["command"].index("--sandbox") + 1] == "read-only"
    assert captured["command"][captured["command"].index("--model") + 1] == "gpt-test"
    assert 'model_reasoning_effort="medium"' in captured["command"]
    assert captured["command"][-1] == "-"
    assert "untrusted data" in captured["kwargs"]["input"]
    assert "smart twelve-year-old" in captured["kwargs"]["input"]
    assert "what the number can and cannot mean" in captured["kwargs"]["input"]
    assert result.value["summary"] == "Owns repository enrollment."


def test_claude_provider_is_non_persistent_tool_free_and_schema_constrained(monkeypatch):
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        schema = json.loads(command[command.index("--json-schema") + 1])
        assert schema["additionalProperties"] is False
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "structured_output": _dossier(),
                    "usage": {"input_tokens": 70, "output_tokens": 50},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    result = ClaudeSemanticProvider(
        SemanticConfig(enabled=True, provider="claude", model="claude-test")
    ).analyze({"analysis_kind": "context", "source": "untrusted"})

    assert captured["command"][0] == "claude"
    assert "--no-session-persistence" in captured["command"]
    assert captured["command"][captured["command"].index("--tools") + 1] == ""
    assert captured["kwargs"]["check"] is False
    assert result.input_tokens == 70
    assert result.output_tokens == 50
