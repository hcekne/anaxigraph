from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest
import yaml

from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import (
    ClaudeSemanticProvider,
    CodexSemanticProvider,
    _result_from_json,
)
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_usage import ProviderUsage
from anaxigraph.understanding import SemanticEngine


def test_local_executor_records_tokens_from_a_failed_model_attempt(
    repository, database, monkeypatch
):
    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "max_attempts": 1,
        "max_parallel_jobs": 1,
    }
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)

    class Provider:
        name = "codex"

        def analyze(self, _request):
            raise SemanticAnalysisError(
                "invalid model JSON",
                input_tokens=120,
                output_tokens=30,
                cache_read_input_tokens=100,
                usage_reported=True,
            )

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", lambda _: Provider())
    execution = replace(config.semantic, provider="codex", model="test-model")

    result = engine.run_jobs(
        stats.repository_id,
        repository,
        config,
        limit=1,
        execution_semantic=execution,
    )

    assert result["failed"] == 1
    assert result["semantic"]["usage"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 0,
        "cost_usd": 0.0,
    }
    with database.connect() as connection:
        failed = connection.execute(
            """
            SELECT usage_source, cache_read_input_tokens
            FROM semantic_jobs WHERE status = 'failed'
            """
        ).fetchone()
    assert tuple(failed) == ("reported", 100)


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_codex_failures_keep_any_reported_usage(monkeypatch, failure):
    events = json.dumps(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 90, "output_tokens": 12},
        }
    )

    def run(*_args, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("codex", 30, output=events)
        return SimpleNamespace(returncode=1, stdout=events, stderr="model failed")

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    provider = CodexSemanticProvider(SemanticConfig(provider="codex"))

    with pytest.raises(SemanticAnalysisError) as raised:
        provider.analyze({"analysis_kind": "intrinsic"})

    assert raised.value.input_tokens == 90
    assert raised.value.output_tokens == 12


def test_invalid_provider_result_keeps_known_usage():
    usage = ProviderUsage(input_tokens=44, output_tokens=9, reported=True)

    with pytest.raises(SemanticAnalysisError) as raised:
        _result_from_json("not JSON", usage=usage)

    assert raised.value.input_tokens == 44
    assert raised.value.output_tokens == 9
    assert raised.value.usage_reported is True


_CLAUDE_USAGE = {
    "input_tokens": 2,
    "cache_creation_input_tokens": 9000,
    "cache_read_input_tokens": 30000,
    "output_tokens": 800,
}


def _claude_failure(monkeypatch, run) -> SemanticAnalysisError:
    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)

    with pytest.raises(SemanticAnalysisError) as raised:
        ClaudeSemanticProvider(SemanticConfig(provider="claude")).analyze(
            {"analysis_kind": "intrinsic"}
        )
    return raised.value


def test_claude_invalid_structured_output_keeps_summed_usage(monkeypatch):
    envelope = json.dumps({"structured_output": ["not a dossier"], "usage": _CLAUDE_USAGE})

    error = _claude_failure(
        monkeypatch,
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=envelope, stderr=""),
    )

    assert error.input_tokens == 39002
    assert error.output_tokens == 800


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_claude_failures_keep_any_reported_usage(monkeypatch, failure):
    envelope = json.dumps({"type": "result", "is_error": True, "usage": _CLAUDE_USAGE})

    def run(*_args, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("claude", 30, output=envelope)
        return SimpleNamespace(returncode=1, stdout=envelope, stderr="model failed")

    error = _claude_failure(monkeypatch, run)

    assert error.input_tokens == 39002
    assert error.output_tokens == 800


@pytest.mark.parametrize(
    ("stdout", "message", "input_tokens"),
    [
        ("not json", "valid JSON envelope", 0),
        (json.dumps({"result": "not json", "usage": _CLAUDE_USAGE}), "contain valid JSON", 39002),
    ],
)
def test_claude_malformed_output_is_reported_with_known_usage(
    monkeypatch, stdout, message, input_tokens
):
    error = _claude_failure(
        monkeypatch,
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )

    assert message in str(error)
    assert error.input_tokens == input_tokens


def test_claude_launch_failure_and_silent_exit_report_zero_usage(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("claude")

    launch = _claude_failure(monkeypatch, missing)
    silent_exit = _claude_failure(
        monkeypatch,
        lambda *_args, **_kwargs: SimpleNamespace(returncode=2, stdout="", stderr="boom"),
    )

    assert "Claude semantic run failed" in str(launch)
    assert "Claude exited with 2: boom" in str(silent_exit)
    assert (launch.input_tokens, silent_exit.input_tokens) == (0, 0)
