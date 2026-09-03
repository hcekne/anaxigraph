from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_grounding import read_review_grounding
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


def test_confirmed_needs_test_and_already_satisfied_statuses(repository, database):
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
    assert grounded[1]["status"] == "confirmed"
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
        "checks": [],
    }
    assert grounded[4]["status"] == "already_satisfied"
    assert "already_satisfies" in grounded[4]["reason"]
    summary = result["grounding_summary"]
    assert summary["counts"] == {
        "confirmed": 1,
        "needs_test": 2,
        "already_satisfied": 1,
        "stale": 0,
    }
    assert (
        summary["reviewed_snapshot_id"] == summary["current_snapshot_id"] == result["snapshot_id"]
    )
    assert "regular-expression identifier extraction" in summary["method"]
    assert (
        "Grounding checks identifiers only; it does not prove a recommendation is correct."
        in result["caveats"]
    )


def test_a_recommendation_proposing_an_existing_route_is_already_satisfied(repository, database):
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
    assert grounded["status"] == "already_satisfied"
    assert grounded["reason"] == "The proposed route /api/semantic/prepare already exists."
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
    assert [item["status"] for item in before["recommendations"]] == ["confirmed", "needs_test"]

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
        "confirmed": 0,
        "needs_test": 1,
        "already_satisfied": 0,
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
