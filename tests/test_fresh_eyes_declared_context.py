"""Implementation context belongs to source-aware Planning, never blind Fresh Eyes."""

from __future__ import annotations

import json

from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.architecture_charter_corrections import save_charter_correction
from anaxigraph.architecture_plan_evidence import current_graph_evidence
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_evidence import current_charter
from anaxigraph.understanding import SemanticEngine

_DECLARED_INVARIANT = "Analysis never writes to the target repository, by design."


_DECLARED_REASON = "The invariant is a deliberate product promise, not an accident."


_REFUTED_REASON = "Every connection opens its own temporary projection, so no reader shares one."


_CONCERN = {
    "key": "temp-tables",
    "name": "Temporary projection tables",
    "statement": "Temporary projection tables may be read by another connection.",
    "related": [],
    "entry_points": ["pkg/core.py"],
    "evidence": ["snapshot projection review"],
    "counter_evidence": [],
    "confidence": 0.6,
}


def _drain(engine, repository_id, repository, config, *, prefix, requests=None) -> None:
    """Run the connected agent queue to completion, optionally capturing every packet."""
    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"{prefix}-{index}",
            agent_model="fixture-model",
        )
        if packet["status"] == "complete":
            return
        assert packet["status"] == "work", packet
        if requests is not None:
            requests.append(packet["analysis_request"])
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
        )
    raise AssertionError("Semantic work did not converge")


def _baseline(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _drain(engine, stats.repository_id, repository, config, prefix="baseline")
    return engine, stats.repository_id, stats.snapshot_id, config


def _add_inferred_concern(database, snapshot_id) -> None:
    """Give the inferred Charter one coherence concern a principal can refute."""
    with database.transaction() as connection:
        row = connection.execute(
            """
            SELECT sd.id, sd.value_json FROM semantic_scope_states ss
            JOIN semantic_documents sd ON sd.id = ss.context_document_id
            WHERE ss.snapshot_id = ? AND ss.scope_type = 'repository'
            """,
            (snapshot_id,),
        ).fetchone()
        charter = json.loads(row["value_json"])
        charter["coherence_concerns"] = [_CONCERN]
        connection.execute(
            "UPDATE semantic_documents SET value_json = ? WHERE id = ?",
            (json.dumps(charter, sort_keys=True), int(row["id"])),
        )


def _planning(database, repository_id, snapshot_id):
    with database.connect() as connection:
        return current_graph_evidence(
            connection, repository_id, snapshot_id, current_charter(connection, snapshot_id)
        )


def test_source_context_reaches_planning_and_no_fresh_eyes_pass(repository, database):
    engine, repository_id, snapshot_id, config = _baseline(repository, database)
    _add_inferred_concern(database, snapshot_id)
    refutation = save_charter_correction(
        database,
        repository_id,
        section="coherence_concerns",
        key="temp-tables",
        author="repository owner",
        rationale=_REFUTED_REASON,
        disposition="refute",
    )
    engine.start_fresh_eyes_review(repository_id, repository, config)
    requests = []
    _drain(engine, repository_id, repository, config, prefix="review", requests=requests)
    assert {item["analysis_kind"] for item in requests} == {
        "fresh_proposal",
        "fresh_adjudication",
        "fresh_comparison",
        "fresh_review",
    }
    for packet in requests:
        encoded = json.dumps(packet)
        assert _REFUTED_REASON not in encoded
        assert "temp-tables" not in encoded
        assert "declared_context" not in packet
        assert "current_system" not in packet
    current, _ = _planning(database, repository_id, snapshot_id)
    declared = current["declared_context"]
    assert len(declared) == 1
    assert declared[0]["rationale"] == _REFUTED_REASON
    assert declared[0]["inferred_statement"] == _CONCERN["statement"]
    assert declared[0]["document_id"] == refutation["document_id"]


def test_implementation_corrections_preserve_functional_alternatives(repository, database):
    engine, repository_id, snapshot_id, config = _baseline(repository, database)
    engine.start_fresh_eyes_review(repository_id, repository, config)
    _drain(engine, repository_id, repository, config, prefix="first-review")
    first = engine.fresh_eyes_status(repository_id, config.semantic)
    identifiers = [item["document_id"] for item in first["stages"]]
    target = {"section": "invariants", "key": "read-only-source", "author": "repository owner"}
    save_charter_correction(
        database, repository_id, statement=_DECLARED_INVARIANT, rationale=_DECLARED_REASON, **target
    )
    corrected = engine.start_fresh_eyes_review(repository_id, repository, config)
    assert corrected["plan_stage"] == "fresh_eyes_complete"
    assert [item["document_id"] for item in corrected["review"]["stages"]] == identifiers
    current, _ = _planning(database, repository_id, snapshot_id)
    assert current["declared_context"][0]["statement"] == _DECLARED_INVARIANT
    save_charter_correction(
        database, repository_id, rationale="The Charter now states it.", active=False, **target
    )
    current, _ = _planning(database, repository_id, snapshot_id)
    assert current["declared_context"] == []
    assert engine.start_fresh_eyes_review(repository_id, repository, config)["review"]["ready"]


def test_planning_fingerprint_tracks_saved_implementation_context(repository, database):
    _engine, repository_id, snapshot_id, _config = _baseline(repository, database)
    current, before = _planning(database, repository_id, snapshot_id)
    assert current["declared_context"] == []
    target = {"section": "invariants", "key": "read-only-source", "author": "repository owner"}
    save_charter_correction(
        database, repository_id, statement=_DECLARED_INVARIANT, rationale=_DECLARED_REASON, **target
    )
    current, after = _planning(database, repository_id, snapshot_id)
    assert current["declared_context"]
    assert before["packet_fingerprint"] != after["packet_fingerprint"]
    assert before["graph_node_ids"] == after["graph_node_ids"]
