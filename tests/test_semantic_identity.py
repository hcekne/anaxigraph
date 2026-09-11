from __future__ import annotations

from dataclasses import replace

from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_graph import _module_scope
from anaxigraph.understanding import SemanticEngine


def test_module_scope_identity_uses_current_fact_references():
    assert _module_scope(
        "pkg/core.py",
        {"artifact_id": "17", "file_fact_id": "29"},
    ) == {
        "scope_type": "module",
        "scope_key": "pkg/core.py",
        "artifact_id": 17,
        "artifact_version_id": None,
        "file_fact_id": 29,
    }


def test_executor_and_model_changes_do_not_invalidate_semantic_documents(
    repository, database, tmp_path
):
    log = tmp_path / "semantic-executor-change.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)

    baseline = engine.bootstrap(stats.repository_id, repository, config)
    assert baseline["semantic"]["semantically_ready"] is True
    baseline_calls = len(_calls(log))

    changed_executor = replace(
        config,
        semantic=replace(
            config.semantic,
            provider="agent",
            command=(),
            model="gpt-next-model",
        ),
    )
    repeated = engine.bootstrap(stats.repository_id, repository, changed_executor)

    assert repeated["processed"] == 0
    assert engine.plan(stats.repository_id, repository, changed_executor).active_jobs == 0
    assert repeated["semantic"]["current"] == repeated["semantic"]["eligible_modules"]
    assert repeated["semantic"]["semantically_ready"] is True
    assert len(_calls(log)) == baseline_calls
