from __future__ import annotations

import importlib
from dataclasses import replace

import pytest
from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_freshness import legacy_input_matches, semantic_digest
from anaxigraph.understanding import SemanticEngine


def _v5_hash(contract, prompt, evidence):
    original = dict(evidence)
    if contract in {"module-intrinsic-v1", "module-context-v1"}:
        original.pop("detailed_reviews", None)
    if contract == "module-context-v1":
        original.pop("intrinsic_source", None)
    return semantic_digest({"input_contract": contract, "prompt": prompt, "evidence": original})


@pytest.mark.parametrize(
    ("scope", "kind", "contract", "evidence"),
    [
        ("module", "intrinsic", "module-intrinsic-v1", {"path": "a.py", "structural_hash": "a"}),
        ("module", "context", "module-context-v1", {"intrinsic_intent": "a", "relationships": []}),
        ("group", "synthesis", "group-synthesis-v1", {"documents": [["a.py", "intent", "hash"]]}),
        ("repository", "synthesis", "architecture-charter-v1", {"documents": [["group", "hash"]]}),
        ("taxonomy", "taxonomy_proposal", "taxonomy-proposal-v1", {"modules": ["a.py"]}),
    ],
)
def test_released_v5_stable_hash_requires_identical_original_evidence(
    scope, kind, contract, evidence
):
    record = {
        "schema_version": "repository-understanding-v5",
        "prompt_version": "v1",
        "scope_type": scope,
        "document_kind": kind,
        "input_hash": _v5_hash(contract, "v1", evidence),
    }
    current = dict(evidence)
    if scope == "module":
        current["detailed_reviews"] = False
    if kind == "context":
        current["intrinsic_source"] = "new-signature-for-unchanged-source"
    kwargs = {"input_contract": contract} if scope == "taxonomy" else {}
    assert legacy_input_matches(record, current, prompt_version="v1", **kwargs)
    assert not legacy_input_matches(
        record, {**current, "changed": True}, prompt_version="v1", **kwargs
    )
    assert not legacy_input_matches(record, current, prompt_version="v2", **kwargs)
    assert not legacy_input_matches(
        {**record, "schema_version": "unknown"}, current, prompt_version="v1", **kwargs
    )
    if scope == "module":
        assert not legacy_input_matches(
            record, {**current, "detailed_reviews": True}, prompt_version="v1"
        )


def _old_map(repository, database, tmp_path, monkeypatch):
    log = tmp_path / "old-map.log"
    _semantic_config(repository, _fake_provider(tmp_path), log)
    config = load_config(repository)
    scanner = RepositoryScanner(database)
    baseline = scanner.scan(repository)
    with monkeypatch.context() as legacy:
        for name in (
            "semantic_module_intrinsic",
            "semantic_module_context",
            "semantic_scope_plan",
            "semantic_taxonomy_plan",
            "semantic_pattern_plan",
        ):
            module = importlib.import_module("anaxigraph." + name)
            if hasattr(module, "semantic_input_hash"):
                legacy.setattr(module, "semantic_input_hash", _v5_hash)
        assert SemanticEngine(database).bootstrap(baseline.repository_id, repository, config)[
            "semantic"
        ]["semantically_ready"]
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_documents SET schema_version = 'repository-understanding-v5'"
        )
        connection.execute(
            "UPDATE semantic_taxonomies SET schema_version = 'repository-understanding-v5'"
        )
    return baseline, replace(config, semantic=replace(config.semantic, detailed_reviews=False)), log


def _saved_documents(database):
    with database.transaction() as connection:
        return dict(connection.execute("SELECT id,value_json FROM semantic_documents").fetchall())


def test_upgrade_reuses_old_map_and_supersedes_redundant_pending_jobs(
    repository, database, tmp_path, monkeypatch
):
    baseline, config, log = _old_map(repository, database, tmp_path, monkeypatch)
    engine = SemanticEngine(database)
    documents = _saved_documents(database)
    calls = _calls(log)
    with monkeypatch.context() as broken:
        broken.setattr("anaxigraph.semantic_records.legacy_input_matches", lambda *a, **k: False)
        queued = engine.plan(baseline.repository_id, repository, config)
        assert queued.enqueued == 8
        assert queued.active_jobs == 8
    repaired = engine.plan(baseline.repository_id, repository, config)
    assert repaired.enqueued == 0
    assert repaired.active_jobs == 0
    assert repaired.status["current"] == repaired.status["eligible_modules"] == 8
    assert repaired.status["semantically_ready"] is True
    assert _calls(log) == calls
    assert _saved_documents(database) == documents
    repeated = engine.plan(baseline.repository_id, repository, config)
    assert repeated.enqueued == repeated.active_jobs == 0
    assert _saved_documents(database) == documents


def test_changed_body_with_same_role_does_not_reuse_legacy_context(
    repository, database, tmp_path, monkeypatch
):
    baseline, config, log = _old_map(repository, database, tmp_path, monkeypatch)
    engine = SemanticEngine(database)
    assert engine.plan(baseline.repository_id, repository, config).status["semantically_ready"]
    calls = len(_calls(log))
    original = _saved_documents(database)
    path = repository / "pkg/core.py"
    path.write_text(path.read_text().replace("return double(value)", "return double(value) + 1"))
    changed = RepositoryScanner(database).scan(repository, run_type="update")
    result = engine.bootstrap(changed.repository_id, repository, config)
    assert result["semantic"]["semantically_ready"]
    new_calls = _calls(log)[calls:]
    assert [c for c in new_calls if c["kind"] == "intrinsic"] == [
        {"kind": "intrinsic", "path": "pkg/core.py"}
    ]
    assert {"kind": "context", "path": "pkg/core.py"} in new_calls
    saved = _saved_documents(database)
    assert all(saved[key] == value for key, value in original.items())
