from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest
import yaml

from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import CodexSemanticProvider, _result_from_json
from anaxigraph.semantic_contract import SemanticAnalysisError
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
            raise SemanticAnalysisError("invalid model JSON", input_tokens=120, output_tokens=30)

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
        "cost_usd": 0.0,
    }


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
    with pytest.raises(SemanticAnalysisError) as raised:
        _result_from_json("not JSON", input_tokens=44, output_tokens=9)

    assert raised.value.input_tokens == 44
    assert raised.value.output_tokens == 9
