from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_freshness import legacy_input_matches, semantic_digest
from anaxigraph.semantic_graph import _intent_fingerprint, _interface_hash
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


def _legacy_module_value(path, kind):
    """Synthetic released-v5 payload, never a relabelled graph annotation."""
    return {
        "summary": f"Archived {kind} understanding for {path}.",
        "detailed_summary": f"Historical source-grounded responsibilities of {path}.",
        "responsibilities": [f"Own the behavior in {path}"],
        "inputs": [],
        "outputs": [],
        "side_effects": [],
        "public_contracts": ["Preserve caller-visible results and failures."],
        "invariants": [],
        "domain_concepts": [],
        "architecture_role": "Archived module role",
    }


def _seed_legacy_modules(database, baseline, semantic):
    """Insert the original v5 envelope, input identity, source fact and provenance."""
    with database.transaction() as connection:
        inventory, relationships = semantic_inventory(connection, baseline.snapshot_id)
        for path, module in inventory.items():
            if not semantic.includes_path(path):
                continue
            evidence = {
                "path": path,
                "language": module["language"],
                "analyzer": module["analyzer"],
                "structural_hash": module["structural_hash"],
                "interface_hash": _interface_hash(module),
                "analysis_contract": module["analysis_contract"],
            }
            for kind, contract in (
                ("intrinsic", "module-intrinsic-v1"),
                ("context", "module-context-v1"),
            ):
                value = _legacy_module_value(path, kind)
                inputs = (
                    evidence
                    if kind == "intrinsic"
                    else {
                        "intrinsic_intent": _intent_fingerprint(
                            _legacy_module_value(path, "intrinsic")
                        ),
                        "group": module.get("declared_group") or module.get("inferred_group"),
                        "relationships": [
                            {
                                **relation,
                                "neighbor_interface": _interface_hash(inventory[relation["path"]])
                                if relation["path"] in inventory
                                else "",
                                "neighbor_intent": _intent_fingerprint(
                                    _legacy_module_value(relation["path"], "intrinsic")
                                )
                                if relation["path"] in inventory
                                else "",
                            }
                            for relation in relationships.get(path, [])
                        ],
                    }
                )
                connection.execute(
                    """INSERT INTO semantic_documents(repository_id,snapshot_id,scope_type,scope_key,
                    artifact_id,file_fact_id,document_kind,input_hash,intent_fingerprint,value_json,
                    source,provider,model,prompt_version,schema_version,confidence,created_at)
                    VALUES (?,?,'module',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        baseline.repository_id,
                        baseline.snapshot_id,
                        path,
                        module["artifact_id"],
                        module["file_fact_id"],
                        kind,
                        _v5_hash(contract, semantic.prompt_version, inputs),
                        _intent_fingerprint(value),
                        json.dumps(value),
                        "archived-v5",
                        "historical-provider",
                        "historical-model",
                        semantic.prompt_version,
                        "repository-understanding-v5",
                        0.8,
                        datetime.now(UTC).isoformat(),
                    ),
                )


def _old_map(repository, database, tmp_path, monkeypatch):
    log = tmp_path / "old-map.log"
    _semantic_config(repository, _fake_provider(tmp_path), log, detailed_reviews=False)
    config = load_config(repository)
    baseline = RepositoryScanner(database).scan(repository)
    _seed_legacy_modules(database, baseline, config.semantic)
    assert SemanticEngine(database).bootstrap(baseline.repository_id, repository, config)[
        "semantic"
    ]["semantically_ready"]
    assert not [call for call in _calls(log) if call["kind"] == "annotation"]
    return baseline, config, log


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
        broken.setattr(
            "anaxigraph.knowledge_annotation_plan.compatible_legacy", lambda *a, **k: None
        )
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


def test_changed_body_with_same_role_replaces_legacy_understanding_with_one_annotation(
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
    assert [c for c in new_calls if c["kind"] == "annotation"] == [
        {"kind": "annotation", "path": "pkg/core.py"}
    ]
    assert not [call for call in new_calls if call["kind"] in {"intrinsic", "context"}]
    saved = _saved_documents(database)
    assert all(saved[key] == value for key, value in original.items())


@pytest.mark.parametrize("invalidated", ["prompt", "schema", "age"])
def test_legacy_adoption_respects_prompt_supported_schema_and_age_policy(
    repository, database, tmp_path, monkeypatch, invalidated
):
    baseline, config, log = _old_map(repository, database, tmp_path, monkeypatch)
    original = _saved_documents(database)
    if invalidated == "prompt":
        config = replace(config, semantic=replace(config.semantic, prompt_version="updated-policy"))
    else:
        column, value = (
            ("schema_version", "unknown-format")
            if invalidated == "schema"
            else ("created_at", "2000-01-01T00:00:00+00:00")
        )
        with database.transaction() as connection:
            connection.execute(
                f"UPDATE semantic_documents SET {column}=? WHERE document_kind IN ('intrinsic','context')",
                (value,),
            )
        if invalidated == "age":
            config = replace(config, semantic=replace(config.semantic, max_age_days=1))
    calls = _calls(log)
    planned = SemanticEngine(database).plan(baseline.repository_id, repository, config)
    assert planned.enqueued >= 8
    assert planned.status["current"] == 0
    assert _calls(log) == calls
    assert _saved_documents(database) == original


def test_reused_legacy_graph_preserves_provenance_and_distinguishes_extracted_functions(
    repository, database, tmp_path, monkeypatch
):
    baseline, config, _ = _old_map(repository, database, tmp_path, monkeypatch)
    from anaxigraph.knowledge_detail import entity_detail

    detail = entity_detail(database, baseline.repository_id, "module:pkg/util.py")
    assert detail["node"]["readiness"] == "legacy_reused"
    assert detail["node"]["provenance"]["annotation"]["model"] == "historical-model"
    assert detail["node"]["overview"] == "Archived intrinsic understanding for pkg/util.py."
    assert detail["functions"] and all(
        node["readiness"] == "structural" for node in detail["functions"]
    )
    original = _saved_documents(database)
    forced = SemanticEngine(database).plan(baseline.repository_id, repository, config, force=True)
    assert forced.enqueued >= 8
    assert _saved_documents(database) == original
