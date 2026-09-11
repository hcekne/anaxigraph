from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fresh_eyes_fixtures import agent_fresh_eyes

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import (
    _CODEX_EVIDENCE_PAGE_CHARS,
    _CODEX_INLINE_PROMPT_CHARS,
    ClaudeSemanticProvider,
    CodexSemanticProvider,
    _codex_prompt,
    _prompt,
    _result_from_json,
)
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_usage import ProviderUsage, claude_usage, codex_usage

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_codex_provider_is_ephemeral_read_only_and_schema_constrained(monkeypatch):
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        schema_path = Path(command[command.index("--output-schema") + 1])
        assert json.loads(schema_path.read_text(encoding="utf-8"))["additionalProperties"] is False
        message_path = Path(command[command.index("--output-last-message") + 1])
        message_path.write_text(json.dumps(_dossier()), encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout="\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "test"}),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 120,
                                "cached_input_tokens": 100,
                                "output_tokens": 30,
                            },
                        }
                    ),
                )
            ),
            stderr="",
        )

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
    assert "--json" in captured["command"]
    assert captured["command"][captured["command"].index("--sandbox") + 1] == "read-only"
    assert captured["command"][captured["command"].index("--model") + 1] == "gpt-test"
    assert 'model_reasoning_effort="medium"' in captured["command"]
    assert captured["command"][-1] == "-"
    assert "untrusted data" in captured["kwargs"]["input"]
    assert "short, concrete English" in captured["kwargs"]["input"]
    assert "State each fact once" in captured["kwargs"]["input"]
    assert result.value["summary"] == "Owns repository enrollment."
    assert result.input_tokens == 120
    assert result.output_tokens == 30


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_codex_prompt_checks_the_complete_input_at_the_inline_boundary(tmp_path, offset):
    request = {"analysis_kind": "context", "source": ""}
    request["source"] = "x" * (_CODEX_INLINE_PROMPT_CHARS - len(_prompt(request)) + offset)

    prompt = _codex_prompt(request, tmp_path)

    assert len(prompt) <= _CODEX_INLINE_PROMPT_CHARS
    if offset <= 0:
        assert prompt == _prompt(request)
        assert not list(tmp_path.iterdir())
    else:
        pages = sorted(tmp_path.glob("semantic-evidence-*.txt"))
        assert json.loads("".join(page.read_text(encoding="utf-8") for page in pages)) == request


@pytest.mark.parametrize(
    "kind", ["fresh_proposal", "fresh_adjudication", "fresh_comparison", "fresh_review"]
)
def test_oversized_codex_request_keeps_every_page_and_the_original_contract(monkeypatch, kind):
    request = {
        "analysis_kind": kind,
        "input_manifest": {"snapshot_id": 1129, "review_generation": 3},
        "proposals": [{"proposal": "proposal:a"}, {"proposal": "proposal:b"}],
        "evidence": 'head: å 雪 \\ "\n' + "evidence " * 150_000 + "tail: retained",
    }
    original = json.loads(json.dumps(request))
    captured = {}
    expected = agent_fresh_eyes(request, kind)

    def run(command, **kwargs):
        directory = Path(kwargs["cwd"])
        captured["directory"] = directory
        pages = sorted(directory.glob("semantic-evidence-*.txt"))
        contents = [page.read_text(encoding="utf-8") for page in pages]
        assert len(kwargs["input"]) < 10_000
        assert len(pages) > 1
        assert all(0 < len(content) <= _CODEX_EVIDENCE_PAGE_CHARS for content in contents)
        assert json.loads("".join(contents)) == original
        assert pages[0].name in kwargs["input"]
        assert pages[-1].name in kwargs["input"]
        assert "Consider every page" in kwargs["input"]
        assert "Do not inspect other files or repositories" in kwargs["input"]
        assert "untrusted data" in kwargs["input"]
        assert "Do not use tools." not in kwargs["input"]
        assert "--ephemeral" in command
        assert "--ignore-user-config" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert command[command.index("--model") + 1] == "gpt-test"
        assert 'model_reasoning_effort="max"' in command
        schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text())
        assert schema["properties"]["contract_version"]["enum"] == [expected["contract_version"]]
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(expected))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 120, "cached_input_tokens": 100, "output_tokens": 30},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    result = CodexSemanticProvider(
        SemanticConfig(provider="codex", model="gpt-test", reasoning_effort="max")
    ).analyze(request)

    assert result.value == expected
    assert result.input_tokens == 120
    assert result.cache_read_input_tokens == 100
    assert result.usage_reported is True
    assert request == original
    assert not captured["directory"].exists()


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_oversized_codex_request_cleans_up_evidence_after_failure(monkeypatch, failure):
    captured = {}

    def run(_command, **kwargs):
        directory = Path(kwargs["cwd"])
        captured["directory"] = directory
        assert list(directory.glob("semantic-evidence-*.txt"))
        if failure == "timeout":
            raise subprocess.TimeoutExpired("codex", 30)
        return SimpleNamespace(returncode=1, stdout="", stderr="model failed")

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    with pytest.raises(SemanticAnalysisError):
        CodexSemanticProvider(SemanticConfig(provider="codex")).analyze(
            {"analysis_kind": "context", "source": "x" * 1_270_329}
        )
    assert not captured["directory"].exists()


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
    assert "--effort" not in captured["command"]
    assert captured["kwargs"]["check"] is False
    assert result.input_tokens == 70
    assert result.output_tokens == 50


def test_claude_provider_forwards_reasoning_effort_unvalidated(monkeypatch):
    captured = {}

    def run(command, **_kwargs):
        captured.update(command=command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": _dossier(), "usage": {}}),
            stderr="",
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    ClaudeSemanticProvider(
        SemanticConfig(enabled=True, provider="claude", reasoning_effort="future-effort")
    ).analyze({"analysis_kind": "context", "source": "untrusted"})

    assert captured["command"][captured["command"].index("--effort") + 1] == "future-effort"


def _claude_result(monkeypatch, envelope: dict[str, Any]) -> Any:
    def run(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(envelope), stderr="")

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    return ClaudeSemanticProvider(SemanticConfig(enabled=True, provider="claude")).analyze(
        {"analysis_kind": "context", "source": "untrusted"}
    )


def _captured_claude_envelope() -> dict[str, Any]:
    return json.loads((FIXTURES / "claude-print-envelope.json").read_text(encoding="utf-8"))


def test_claude_provider_counts_cached_prompt_tokens(monkeypatch):
    result = _claude_result(
        monkeypatch,
        {
            "structured_output": _dossier(),
            "usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": 9000,
                "cache_read_input_tokens": 30000,
                "output_tokens": 800,
            },
        },
    )

    assert result.input_tokens == 39002
    assert result.output_tokens == 800


def test_claude_provider_reads_the_captured_envelope_shape(monkeypatch):
    envelope = _captured_claude_envelope()
    usage = envelope["usage"]
    envelope["structured_output"] = _dossier()

    result = _claude_result(monkeypatch, envelope)

    assert usage["input_tokens"] < usage["cache_read_input_tokens"]
    assert result.input_tokens == (
        usage["input_tokens"]
        + usage["cache_creation_input_tokens"]
        + usage["cache_read_input_tokens"]
    )
    assert result.output_tokens == usage["output_tokens"]


def test_claude_provider_reads_model_usage_when_usage_missing(monkeypatch):
    envelope = _captured_claude_envelope()
    del envelope["usage"]
    envelope["structured_output"] = _dossier()
    per_model = list(envelope["modelUsage"].values())

    result = _claude_result(monkeypatch, envelope)

    assert result.input_tokens > 0
    assert result.input_tokens == sum(
        entry["inputTokens"] + entry["cacheCreationInputTokens"] + entry["cacheReadInputTokens"]
        for entry in per_model
    )
    assert result.output_tokens == sum(entry["outputTokens"] for entry in per_model)

    bare = _claude_result(monkeypatch, {"structured_output": _dossier()})

    assert (bare.input_tokens, bare.output_tokens) == (0, 0)


def test_a_result_reports_usage_only_when_the_executor_returned_some(monkeypatch):
    reported = _claude_result(
        monkeypatch,
        {
            "structured_output": _dossier(),
            "usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": 9000,
                "cache_read_input_tokens": 30000,
                "output_tokens": 800,
            },
        },
    )

    assert reported.usage_reported is True
    assert reported.cache_read_input_tokens == 30000
    assert reported.cache_creation_input_tokens == 9000

    silent = _claude_result(monkeypatch, {"structured_output": _dossier()})

    assert silent.usage_reported is False
    assert (silent.cache_read_input_tokens, silent.cache_creation_input_tokens) == (0, 0)


def test_a_command_envelope_reports_usage_only_when_it_names_some():
    dossier = _dossier()

    silent = _result_from_json(json.dumps({"dossier": dossier}))
    reported = _result_from_json(
        json.dumps(
            {
                "dossier": dossier,
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "cache_read_input_tokens": 100,
                },
            }
        )
    )

    assert silent.usage_reported is False
    assert reported.usage_reported is True
    assert reported.input_tokens == 120
    assert reported.cache_read_input_tokens == 100


def test_codex_usage_exposes_cached_input_without_double_counting():
    captured = (FIXTURES / "codex-exec-events.jsonl").read_text(encoding="utf-8")

    assert codex_usage(captured) == ProviderUsage(
        input_tokens=14233, output_tokens=15, reported=True
    )

    usage = codex_usage(
        "not an event\n"
        + json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 120,
                    "cached_input_tokens": 100,
                    "cache_write_input_tokens": 5,
                    "output_tokens": 30,
                },
            }
        )
    )

    assert usage.input_tokens == 120
    assert usage.cache_read_input_tokens == 100
    assert usage.cache_creation_input_tokens == 5


def test_usage_parsers_ignore_malformed_counts_and_envelopes():
    malformed = claude_usage({"usage": {"input_tokens": "many", "output_tokens": 3}})

    assert malformed == ProviderUsage(output_tokens=3, reported=True)
    assert claude_usage("not an envelope") == ProviderUsage()
    assert claude_usage("not an envelope").reported is False
