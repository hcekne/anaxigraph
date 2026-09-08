"""Parent judgments get bounded child claims and real boundary witnesses, not just totals."""

import json
from pathlib import Path

import pytest
from fresh_eyes_support import baseline_review

from anaxigraph.pattern_candidate_selection import candidate_decision
from anaxigraph.pattern_candidates import PatternCandidatePolicy
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.persistence.pattern_evidence_read import read_pattern_evidence
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_pattern_requests import _parent_source_evidence


def test_parent_contracts_support_work_queue_without_catalog_or_budget_growth(repository, database):
    review = baseline_review(repository, database)
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id, value_json FROM semantic_documents WHERE scope_type = 'module'"
        ).fetchall()
        for row in rows:
            value = json.loads(row["value_json"])
            value.update(
                responsibilities=["Own a durable queue of independently processed tasks."],
                public_contracts=[
                    "Only the current lease may finish a task; retries preserve idempotent effects."
                ],
            )
            connection.execute(
                "UPDATE semantic_documents SET value_json = ? WHERE id = ?",
                (json.dumps(value), row["id"]),
            )
    snapshot_id = database.latest_snapshot(review.repository_id)["id"]
    with database.connect() as connection:
        projection = read_pattern_evidence(connection, review.repository_id, snapshot_id)
    parents = [
        item
        for item in projection.items
        if item.target.level in {"subsystem", "area", "repository"}
    ]
    assert {item.target.level for item in parents} == {"subsystem", "area", "repository"}
    catalog = bundled_pattern_catalog()
    card = next(item for item in catalog.cards if item.stable_key == "work-queue")
    for parent in parents:
        witnesses = parent.feature("architecture.witnesses").value
        assert 0 < witnesses["included"] <= 8
        assert witnesses["total_modules"] == witnesses["included"] + witnesses["omitted"]
        assert all(item["public_contracts"] for item in witnesses["items"])
        assert "durable queue" in str(parent.feature("semantic.responsibilities").value)
        assert parent.feature("semantic.public_contracts").availability == "partial"
        assert "runtime" in parent.feature("graph.boundaries").value["caveat"]
        if parent.target.level == "subsystem":
            decision = candidate_decision(
                card, parent, projection, catalog.fingerprint, PatternCandidatePolicy()
            )
            assert decision.candidate is not None

    parent = next(item for item in parents if item.target.level == "repository")
    job = {"snapshot_id": snapshot_id, "metadata": {"target_evidence": parent.as_dict()}}
    source = _parent_source_evidence(
        database, job, Path(repository).resolve(), review.config.semantic
    )
    assert source["source_witnesses"]
    path = repository / source["source_witnesses"][0]["path"]
    path.write_text(path.read_text() + "\n# changed after planning\n")
    with pytest.raises(SupersededSemanticJob, match="changed after planning"):
        _parent_source_evidence(database, job, repository.resolve(), review.config.semantic)


def test_missing_parent_sources_are_explicit_and_do_not_read_files(database, tmp_path):
    job = {"metadata": {"target_evidence": {"features": []}}}
    result = _parent_source_evidence(database, job, tmp_path, None)
    assert result["source_witnesses"] == []
    assert "No current child" in result["source_caveat"]
