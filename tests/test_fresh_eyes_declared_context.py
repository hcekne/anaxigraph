"""Declared Charter context reaches only the repository-aware fresh-eyes packets."""

from __future__ import annotations

import json

from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.architecture_charter_corrections import save_charter_correction
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_freshness import semantic_digest, semantic_input_hash
from anaxigraph.understanding import SemanticEngine

_NO_DECLARED_CONTEXT = {"included": 0, "fingerprint": None, "keys": []}
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
_COMPARISON_INCLUDED = [
    "reference_design",
    "current_charter",
    "responsibility_map",
    "area_summaries",
    "module_dossiers",
    "patterns",
    "dependency_evidence",
    "findings",
    "history",
]
_REVIEW_INCLUDED = ["capability_brief", "as_built_comparison", "engineering_economics"]


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


def _by_kind(requests) -> dict:
    return {item["analysis_kind"]: item for item in requests}


def _manifests(status) -> dict:
    return {item["job_kind"]: item for item in status["input_manifests"]}


def test_a_refuted_concern_reaches_the_comparison_and_review_packets_only(repository, database):
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
    requests: list[dict] = []
    _drain(engine, repository_id, repository, config, prefix="review", requests=requests)

    packets = _by_kind(requests)
    declared = packets["fresh_comparison"]["current_system"]["declared_context"]
    assert declared == [
        {
            "section": "coherence_concerns",
            "key": "temp-tables",
            "disposition": "refute",
            "statement": "",
            "inferred_statement": _CONCERN["statement"],
            "author": "repository owner",
            "rationale": _REFUTED_REASON,
            "document_id": refutation["document_id"],
        }
    ]
    assert packets["fresh_review"]["declared_context"] == declared
    assert "declared_context" in packets["fresh_comparison"]["contract"]
    assert "declared_context" not in json.dumps(packets["fresh_proposal"])
    assert "declared_context" not in json.dumps(packets["fresh_adjudication"])

    comparison_manifest = packets["fresh_comparison"]["input_manifest"]
    assert comparison_manifest["included"] == [*_COMPARISON_INCLUDED, "declared_context"]
    assert packets["fresh_review"]["input_manifest"]["included"] == [
        *_REVIEW_INCLUDED,
        "declared_context",
    ]
    assert comparison_manifest["current_system"]["declared_context"] == {
        "fingerprint": semantic_digest(declared),
        "included": 1,
        "keys": [
            {
                "section": "coherence_concerns",
                "key": "temp-tables",
                "disposition": "refute",
                "document_id": refutation["document_id"],
            }
        ],
    }
    status = engine.fresh_eyes_status(repository_id, config.semantic)
    assert status["declared_context"] == comparison_manifest["current_system"]["declared_context"]


def test_saving_then_withdrawing_a_correction_requeues_only_comparison_and_review(
    repository, database
):
    engine, repository_id, snapshot_id, config = _baseline(repository, database)
    engine.start_fresh_eyes_review(repository_id, repository, config)
    _drain(engine, repository_id, repository, config, prefix="first-review")
    first = engine.fresh_eyes_status(repository_id, config.semantic)
    reference_ids = [stage["document_id"] for stage in first["stages"][:3]]
    assert first["declared_context"] == _NO_DECLARED_CONTEXT

    target = {"section": "invariants", "key": "read-only-source", "author": "repository owner"}
    correction = save_charter_correction(
        database,
        repository_id,
        statement=_DECLARED_INVARIANT,
        rationale=_DECLARED_REASON,
        **target,
    )
    corrected = engine.start_fresh_eyes_review(repository_id, repository, config)

    assert corrected["status"] == "already_started"
    assert corrected["plan_stage"] == "fresh_eyes_comparison"
    assert corrected["review"]["fingerprints"]["comparison"] != first["fingerprints"]["comparison"]
    with database.connect() as connection:
        queued = [
            row[0]
            for row in connection.execute(
                "SELECT job_kind FROM semantic_jobs WHERE snapshot_id = ? "
                "AND scope_type = 'fresh_eyes' AND status = 'pending'",
                (snapshot_id,),
            ).fetchall()
        ]
    assert queued == ["fresh_comparison"]

    requests: list[dict] = []
    _drain(engine, repository_id, repository, config, prefix="second-review", requests=requests)
    second = engine.fresh_eyes_status(repository_id, config.semantic)
    assert [stage["document_id"] for stage in second["stages"][:3]] == reference_ids
    assert _by_kind(requests)["fresh_comparison"]["current_system"]["declared_context"] == [
        {
            "section": "invariants",
            "key": "read-only-source",
            "disposition": "correct",
            "statement": _DECLARED_INVARIANT,
            "inferred_statement": "Repository source remains read-only during analysis.",
            "author": "repository owner",
            "rationale": _DECLARED_REASON,
            "document_id": correction["document_id"],
        }
    ]
    assert second["declared_context"]["keys"] == [
        {
            "section": "invariants",
            "key": "read-only-source",
            "disposition": "correct",
            "document_id": correction["document_id"],
        }
    ]

    save_charter_correction(
        database,
        repository_id,
        rationale="The Charter now states the invariant directly.",
        active=False,
        **target,
    )
    withdrawn = engine.start_fresh_eyes_review(repository_id, repository, config)

    assert withdrawn["plan_stage"] == "fresh_eyes_complete"
    assert withdrawn["review"]["declared_context"] == _NO_DECLARED_CONTEXT
    assert withdrawn["review"]["fingerprints"] == first["fingerprints"]
    assert [stage["document_id"] for stage in withdrawn["review"]["stages"]] == [
        stage["document_id"] for stage in first["stages"]
    ]


def test_a_repository_without_corrections_keeps_every_stored_fingerprint(repository, database):
    engine, repository_id, _snapshot_id, config = _baseline(repository, database)
    engine.start_fresh_eyes_review(repository_id, repository, config)
    requests: list[dict] = []
    _drain(engine, repository_id, repository, config, prefix="review", requests=requests)
    status = engine.fresh_eyes_status(repository_id, config.semantic)

    manifests = _manifests(status)
    comparison = manifests["fresh_comparison"]["manifest"]
    review = manifests["fresh_review"]["manifest"]
    assert comparison["included"] == _COMPARISON_INCLUDED
    assert review["included"] == _REVIEW_INCLUDED
    assert "declared_context" not in comparison
    assert "declared_context" not in comparison["current_system"]
    assert "declared_context" not in review
    assert comparison["reference_fingerprint"] == status["fingerprints"]["reference"]
    assert status["fingerprints"]["comparison"] == semantic_digest(
        {
            "reference_fingerprint": status["fingerprints"]["reference"],
            "current_system": comparison["current_system"],
        }
    )
    for kind, contract in (
        ("fresh_comparison", "fresh-eyes-comparison-v1"),
        ("fresh_review", "fresh-eyes-review-v1"),
    ):
        assert manifests[kind]["input_hash"] == semantic_input_hash(
            contract, config.semantic.prompt_version, manifests[kind]["manifest"]
        )
    packets = _by_kind(requests)
    assert "declared_context" not in json.dumps(packets["fresh_comparison"]["current_system"])
    assert "declared_context" not in packets["fresh_review"]
    assert status["declared_context"] == _NO_DECLARED_CONTEXT
