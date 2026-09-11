from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_grounding import GROUNDING_CAVEAT, read_review_grounding
from anaxigraph.understanding import SemanticEngine


def _recommendation(rank: int, title: str, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "rank": rank,
        "title": title,
        "action": "refactor",
        "mission_capability": "Explain and guide repository changes.",
        "current_evidence": ["The review found duplicated orchestration."],
        "reference_insight": "One durable reasoning path is sufficient.",
        "smallest_change": "Keep one path and delete the other.",
        "expected_benefit": "Less code and one behavior to verify.",
        "expected_deletions": [],
        "protected_behavior": ["Read-only repository analysis"],
        "affected_contracts": [],
        "risks": [],
        "counter_evidence": [],
        "reasons_not_to_proceed": [],
        "dependencies": [],
        "verification": ["Run semantic lifecycle tests."],
        "reversible": True,
        "confidence": 0.7,
    }
    value.update(overrides)
    return value


def _review(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": "fresh-eyes-review-v1",
        "summary": "Keep the sound boundary and test one small consolidation.",
        "mission_alignment": "The change keeps guidance simple.",
        "recommendations": recommendations,
        "rejected_ideas": [],
        "sequence": ["Verify behavior"],
        "caveats": ["The recommendation remains optional."],
        "confidence": 0.7,
        "evidence": ["mission-filtered-comparison"],
    }


def _comparison(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": "fresh-eyes-comparison-v1",
        "summary": "The current system already has the core boundary.",
        "mappings": [],
        "current_strengths": ["Source remains read-only during analysis."],
        "candidate_changes": candidates,
        "unknowns": ["Runtime behavior still needs verification."],
        "confidence": 0.7,
        "evidence": ["reference-to-current-map"],
    }


def _candidate(title: str, classification: str) -> dict[str, Any]:
    return {
        "title": title,
        "classification": classification,
        "explanation": "One durable path can serve the same capability.",
        "affected_responsibilities": ["Understanding"],
        "evidence": ["comparison:duplicate-flow"],
        "counter_evidence": [],
        "migration_cost": "low",
    }


def _complete(engine, repository_id, repository, config, values=None) -> None:
    """Drain the queue, substituting fixture values for the named fresh-eyes stages."""

    values = values or {}
    for index in range(500):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"grounding-{index}",
            agent_model="fixture-model",
        )
        if packet["status"] == "complete":
            return
        assert packet["status"] == "work", packet
        dossier = values.get(packet["job"]["kind"]) or _agent_dossier(packet["analysis_request"])
        engine.submit_agent_work(
            repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=dossier,
        )
    raise AssertionError("Semantic queue did not converge")


def _reviewed(repository, database, values=None):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    _complete(engine, stats.repository_id, repository, config)
    engine.start_fresh_eyes_review(stats.repository_id, repository, config)
    _complete(engine, stats.repository_id, repository, config, values)
    return engine, stats.repository_id, config


def _grounding(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(item["rank"]): item["grounding"] for item in result["recommendations"]}


def _counts(connection) -> tuple[int, int]:
    documents = connection.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0]
    grounding = connection.execute(
        "SELECT COUNT(*) FROM semantic_documents WHERE document_kind = 'fresh_grounding'"
    ).fetchone()[0]
    return int(documents), int(grounding)


def _state_digest(connection) -> str:
    """Fingerprint every row a read could plausibly mutate."""

    rows = connection.execute(
        "SELECT id, snapshot_id, document_kind, input_hash, value_json FROM semantic_documents "
        "ORDER BY id"
    ).fetchall()
    states = connection.execute(
        "SELECT snapshot_id, scope_type, scope_key, status, reason, context_document_id "
        "FROM semantic_scope_states ORDER BY snapshot_id, scope_type, scope_key"
    ).fetchall()
    return sha256(
        json.dumps([[tuple(row) for row in rows], [tuple(row) for row in states]]).encode()
    ).hexdigest()


def _latest_review_id(connection) -> int:
    row = connection.execute(
        "SELECT id FROM semantic_documents WHERE document_kind = 'fresh_review' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["id"])


def test_reference_resolution_is_reported_separately_from_claim_support(repository, database):
    values = {
        "fresh_comparison": _comparison(
            [_candidate("Consolidate duplicate orchestration", "already_satisfies")]
        ),
        "fresh_review": _review(
            [
                _recommendation(
                    1,
                    "Split the calculation service",
                    current_evidence=["`pkg/core.py` defines `Calculator` twice over"],
                ),
                _recommendation(
                    2,
                    "Delete the second orchestration branch",
                    current_evidence=["`pkg/missing.py` holds the duplicate branch"],
                ),
                _recommendation(3, "Explain the durable queue in prose only"),
                _recommendation(
                    4,
                    "Consolidate duplicate orchestration",
                    current_evidence=["`pkg/util.py` still has the second path"],
                ),
            ]
        ),
    }

    engine, repository_id, config = _reviewed(repository, database, values)
    result = engine.fresh_eyes_status(repository_id, config.semantic)

    grounded = _grounding(result)
    assert grounded[1]["status"] == "references_resolved"
    assert grounded[1]["evidence_state"] == {
        "reference_resolution": "resolved",
        "claim_support": "unchecked",
        "behavior_verification": "unchecked",
    }
    assert {
        (check["kind"], check["value"], check["result"]) for check in grounded[1]["checks"]
    } == {
        ("path", "pkg/core.py", "exists"),
        ("symbol", "Calculator", "exists"),
    }
    assert grounded[2]["status"] == "needs_test"
    assert [check["value"] for check in grounded[2]["checks"]] == ["pkg/missing.py"]
    assert "pkg/missing.py" in grounded[2]["reason"]
    assert grounded[3] == {
        "status": "needs_test",
        "reason": "The recommendation cites no checkable identifier.",
        "evidence_state": {
            "reference_resolution": "none_cited",
            "claim_support": "unchecked",
            "behavior_verification": "unchecked",
        },
        "checks": [],
    }
    assert grounded[4]["status"] == "already_satisfied"
    assert "already_satisfies" in grounded[4]["reason"]
    summary = result["grounding_summary"]
    assert summary["counts"] == {
        "references_resolved": 1,
        "name_already_present": 0,
        "already_satisfied": 1,
        "needs_test": 2,
        "stale": 0,
    }
    assert (
        summary["reviewed_snapshot_id"] == summary["current_snapshot_id"] == result["snapshot_id"]
    )
    assert "regular-expression identifier extraction" in summary["method"]
    assert GROUNDING_CAVEAT in result["caveats"]


def test_an_existing_name_is_reported_as_a_name_match_not_as_satisfied(repository, database):
    (repository / "web" / "api_routes.ts").write_text(
        "export function prepare(): string {\n  return 'ready';\n}\n", encoding="utf-8"
    )
    values = {
        "fresh_review": _review(
            [
                _recommendation(
                    1,
                    "Prepare AI work without a new scan",
                    smallest_change="Add a `/api/semantic/prepare` route for preparing work.",
                )
            ]
        )
    }

    engine, repository_id, config = _reviewed(repository, database, values)
    result = engine.fresh_eyes_status(repository_id, config.semantic)

    grounded = _grounding(result)[1]
    assert grounded["status"] == "name_already_present"
    assert "already exists by name" in grounded["reason"]
    assert "Read what it does" in grounded["reason"]
    assert grounded["evidence_state"]["claim_support"] == "unchecked"
    assert ("route", "/api/semantic/prepare", "exists") in {
        (check["kind"], check["value"], check["result"]) for check in grounded["checks"]
    }


def test_rescan_of_cited_file_marks_recommendation_stale_without_new_model_work(
    repository, database
):
    values = {
        "fresh_review": _review(
            [
                _recommendation(
                    1,
                    "Split the calculation service",
                    current_evidence=["`pkg/core.py` carries two responsibilities"],
                ),
                _recommendation(2, "Explain the durable queue in prose only"),
            ]
        )
    }
    engine, repository_id, _config = _reviewed(repository, database, values)
    with database.connect() as connection:
        review_id = _latest_review_id(connection)
        reviewed_snapshot = int(
            connection.execute("SELECT MAX(id) AS id FROM snapshots").fetchone()["id"]
        )
        before = read_review_grounding(
            connection,
            repository_id=repository_id,
            snapshot_id=reviewed_snapshot,
            review_id=review_id,
        )
    assert [item["status"] for item in before["recommendations"]] == [
        "references_resolved",
        "needs_test",
    ]

    (repository / "pkg" / "core.py").write_text(
        '"""Public calculation service."""\n\n'
        "from .util import double\n\n"
        "class Calculator:\n"
        '    """Owns calculation behavior."""\n\n'
        "    def calculate(self, value: int) -> int:\n"
        "        return double(value) + 1\n",
        encoding="utf-8",
    )
    stats = RepositoryScanner(database).scan(repository)

    with database.connect() as connection:
        documents, grounding_rows = _counts(connection)
        after = read_review_grounding(
            connection,
            repository_id=repository_id,
            snapshot_id=stats.snapshot_id,
            review_id=review_id,
        )
        assert _counts(connection) == (documents, grounding_rows)
    assert stats.snapshot_id > reviewed_snapshot
    assert [item["status"] for item in after["recommendations"]] == ["stale", "needs_test"]
    assert "pkg/core.py" in after["recommendations"][0]["reason"]
    assert after["recommendations"][0]["checks"][0]["result"] == "changed"
    assert after["recommendations"][1] == before["recommendations"][1]
    assert after["summary"]["current_snapshot_id"] == stats.snapshot_id
    assert after["summary"]["reviewed_snapshot_id"] == reviewed_snapshot
    assert after["summary"]["counts"] == {
        "references_resolved": 0,
        "name_already_present": 0,
        "already_satisfied": 0,
        "needs_test": 1,
        "stale": 1,
    }
    assert engine.fresh_eyes_status(repository_id)["state"] == "stale"


def test_grounding_document_is_written_once_and_reads_do_not_write(repository, database):
    engine, repository_id, config = _reviewed(repository, database)
    with database.connect() as connection:
        documents, grounding_rows = _counts(connection)
        digest = _state_digest(connection)
    assert grounding_rows == 1

    for _ in range(3):
        assert engine.fresh_eyes_status(repository_id, config.semantic)["state"] == "current"
    for index in range(2):
        packet = engine.claim_agent_work(
            repository_id,
            repository,
            config,
            agent_id=f"replan-{index}",
            agent_model="fixture-model",
        )
        assert packet["status"] == "complete"

    with database.connect() as connection:
        assert _counts(connection) == (documents, 1)
        assert _state_digest(connection) == digest
        row = connection.execute(
            "SELECT provider, source, model, input_tokens, previous_document_id, snapshot_id "
            "FROM semantic_documents WHERE document_kind = 'fresh_grounding'"
        ).fetchone()
        assert (row["provider"], row["source"], row["model"]) == (
            "deterministic",
            "deterministic",
            "",
        )
        assert row["input_tokens"] == 0
        assert row["previous_document_id"] == _latest_review_id(connection)


def test_a_report_written_under_the_previous_contract_stays_readable(repository, database):
    """A contract bump changes the stored identity; an earlier report must not disappear."""

    engine, repository_id, config = _reviewed(repository, database)
    result = engine.fresh_eyes_status(repository_id, config.semantic)
    review_id = result["recommendations"][0]["grounding"] and _review_document_id(
        database, repository_id
    )

    with database.transaction() as connection:
        row = connection.execute(
            "SELECT id, value_json FROM semantic_documents WHERE document_kind = 'fresh_grounding'"
        ).fetchone()
        value = json.loads(row["value_json"])
        value["contract_version"] = "fresh-eyes-grounding-v1"
        for item in value["recommendations"]:
            item.pop("evidence_state", None)
            if item["status"] == "references_resolved":
                item["status"] = "confirmed"
        connection.execute(
            "UPDATE semantic_documents SET value_json = ?, input_hash = ? WHERE id = ?",
            (
                json.dumps(value),
                _legacy_hash(review_id),
                row["id"],
            ),
        )

    with database.connect() as connection:
        restored = read_review_grounding(
            connection,
            repository_id=repository_id,
            snapshot_id=result["snapshot_id"],
            review_id=review_id,
        )

    assert restored is not None
    assert restored["contract_version"] == "fresh-eyes-grounding-v1"
    statuses = {item["status"] for item in restored["recommendations"]}
    assert "confirmed" not in statuses
    assert all("evidence_state" in item for item in restored["recommendations"])
    assert all(
        item["evidence_state"]["claim_support"] == "unchecked"
        for item in restored["recommendations"]
    )


def _review_document_id(database, repository_id: int) -> int:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT id FROM semantic_documents WHERE repository_id = ? AND document_kind = "
            "'fresh_review' ORDER BY id DESC LIMIT 1",
            (repository_id,),
        ).fetchone()
    return int(row["id"])


def _legacy_hash(review_id: int) -> str:
    from anaxigraph.semantic_fresh_eyes_contract import semantic_digest

    return semantic_digest(
        {"contract": "fresh-eyes-grounding-v1", "review_document_id": int(review_id)}
    )
