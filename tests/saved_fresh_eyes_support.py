"""Saved-v1 fixtures exercise readers without resurrecting the retired producer."""

import json
from datetime import UTC, datetime

from fresh_eyes_fixtures import agent_fresh_eyes

from anaxigraph.semantic_fresh_eyes_contract import semantic_digest as legacy_digest
from anaxigraph.semantic_fresh_eyes_functional import semantic_digest
from anaxigraph.semantic_fresh_eyes_jobs import upsert_stage, upsert_state


def seed_legacy_review(database, repository_id, snapshot_id, overrides=None, *, grounding=None):
    overrides = overrides or {}
    with database.transaction() as connection:
        documents = {}
        for key, kind in (
            ("proposal:a", "fresh_proposal"),
            ("proposal:b", "fresh_proposal"),
            ("adjudication", "fresh_adjudication"),
            ("comparison", "fresh_comparison"),
            ("review", "fresh_review"),
        ):
            value = overrides.get(kind) or agent_fresh_eyes(
                {"proposals": [{"proposal": "a"}, {"proposal": "b"}]}, kind
            )
            digest = semantic_digest({"legacy_stage": key, "value": value})
            cursor = connection.execute(
                "INSERT INTO semantic_documents(repository_id,snapshot_id,scope_type,scope_key,"
                "document_kind,input_hash,intent_fingerprint,value_json,source,provider,model,"
                "prompt_version,schema_version,confidence,created_at) VALUES(?,?,'fresh_eyes',"
                "?,?,?,?,?, 'agent','agent','fixture','legacy-v1',?,0.8,?)",
                (
                    repository_id,
                    snapshot_id,
                    key,
                    kind,
                    digest,
                    digest,
                    json.dumps(value),
                    value["contract_version"],
                    datetime.now(UTC).isoformat(),
                ),
            )
            documents[key] = int(cursor.lastrowid)
            upsert_stage(
                connection,
                "fresh_eyes",
                repository_id,
                snapshot_id,
                key,
                digest,
                {"id": cursor.lastrowid},
            )
        upsert_state(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            scope_type="fresh_eyes",
            scope_key="plan",
            status="current",
            reason="Saved legacy review",
            interface_hash="2:1",
            context_document_id=documents["review"],
        )
        if grounding is not False:
            _seed_grounding(connection, repository_id, snapshot_id, documents["review"], grounding)
    return documents


def _seed_grounding(connection, repository_id, snapshot_id, review_id, grounding):
    value = grounding or {
        "contract_version": "fresh-eyes-grounding-v2",
        "snapshot_id": snapshot_id,
        "method": "Historical identifier snapshot; behavior was not verified.",
        "recommendations": [
            {
                "rank": 1,
                "status": "references_resolved",
                "reason": "The cited path existed when reviewed.",
                "checks": [{"kind": "path", "value": "pkg/core.py", "result": "exists"}],
                "evidence_state": {
                    "reference_resolution": "resolved",
                    "claim_support": "unchecked",
                    "behavior_verification": "unchecked",
                },
            }
        ],
        "summary": {
            "reviewed_snapshot_id": snapshot_id,
            "current_snapshot_id": snapshot_id,
            "counts": {"references_resolved": 1, "needs_test": 0, "stale": 0},
        },
        "caveats": ["This is the original historical result."],
    }
    digest = legacy_digest({"contract": value["contract_version"], "review_document_id": review_id})
    connection.execute(
        "INSERT INTO semantic_documents(repository_id,snapshot_id,scope_type,scope_key,"
        "previous_document_id,document_kind,input_hash,intent_fingerprint,value_json,source,"
        "provider,model,prompt_version,schema_version,confidence,created_at) "
        "VALUES(?,?,'fresh_eyes','grounding',?,'fresh_grounding',?,?,?,'deterministic',"
        "'deterministic','','legacy-v1',?,1.0,?)",
        (
            repository_id,
            snapshot_id,
            review_id,
            digest,
            digest,
            json.dumps(value),
            value["contract_version"],
            datetime.now(UTC).isoformat(),
        ),
    )
