"""Reconstruct every recorded fresh-eyes review generation (bundle) for one repository.

Generations survive only indirectly, so they are derived from two sources. A completed ``fresh_*``
job keeps its compacted ``input_manifest``, which names ``review_generation`` directly; a legacy job
whose retained metadata is empty falls back to its snapshot's plan token ``<proposals>:<generation>``
and so to generation 1. Surviving ``semantic_scope_states`` rows cover what jobs cannot: an
implementation-only rescan reuses an earlier snapshot's proposal and adjudication documents without
creating a job, so that snapshot's stages are recovered from its state rows and attributed through
the reused input hash.

Bundles are keyed by ``(generation, snapshot_id)`` because one generation can therefore own stages on
several snapshots, and stay summary-only: identities, counts, provenance, stage telemetry, never
document bodies. The document readers shared with the review status payload live here so that
``semantic_fresh_eyes_review`` depends on this module and never the other way round.
"""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.semantic_fresh_eyes_contract import fresh_eyes_plan_options
from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
from anaxigraph.semantic_fresh_eyes_plan import FRESH_EYES_PLAN_KEY, FRESH_EYES_SCOPE
from anaxigraph.semantic_fresh_eyes_telemetry import stage_telemetry, telemetry_totals

FRESH_EYES_STAGES = (
    ("proposal:a", "Independent proposal A"),
    ("proposal:b", "Independent proposal B"),
    ("proposal:c", "Independent proposal C"),
    ("adjudication", "Blind adjudication"),
    ("comparison", "As-built comparison"),
    ("review", "Mission filter and ranked strategy"),
)
_STAGE_LABELS = dict(FRESH_EYES_STAGES)
_STAGE_ORDER = {key: index for index, (key, _label) in enumerate(FRESH_EYES_STAGES)}

_JOB_STAGE_SQL = """
SELECT j.id AS job_id, j.snapshot_id, j.scope_key, j.job_kind, j.input_hash, j.status,
       j.metadata_json, d.id AS document_id
FROM semantic_jobs j
LEFT JOIN semantic_documents d ON d.repository_id = j.repository_id
    AND d.scope_type = j.scope_type AND d.scope_key = j.scope_key
    AND d.document_kind = j.job_kind AND d.input_hash = j.input_hash
WHERE j.repository_id = ? AND j.scope_type = ?
ORDER BY j.id
"""
_STATE_STAGE_SQL = """
SELECT snapshot_id, scope_key, context_input_hash, context_document_id
FROM semantic_scope_states
WHERE repository_id = ? AND scope_type = ? AND scope_key != ?
"""
_PLAN_SQL = """
SELECT snapshot_id, interface_hash, status FROM semantic_scope_states
WHERE repository_id = ? AND scope_type = ? AND scope_key = ?
"""
_BUNDLE_DOCUMENT_SQL = """
SELECT id, scope_key, document_kind, input_hash, provider, model, executor_id, executor_model,
       created_at, confidence,
       json_array_length(value_json, '$.recommendations') AS recommendation_count,
       json_array_length(value_json, '$.rejected_ideas') AS rejected_idea_count
FROM semantic_documents WHERE id = ?
"""
_MANIFEST_SQL = """
SELECT scope_key, job_kind, status, input_hash, metadata_json FROM semantic_jobs
WHERE repository_id = ? AND scope_type = ? AND scope_key = ? AND input_hash = ?
ORDER BY id DESC LIMIT 1
"""


def list_generations(
    connection: Any, repository_id: int, snapshot_id: int | None = None
) -> list[dict[str, Any]]:
    """List every recorded review bundle for a repository, oldest generation first."""

    plans = _plan_rows(connection, repository_id)
    grouped: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
    for entry in _stage_entries(connection, repository_id, plans):
        bundle = grouped.setdefault((entry["generation"], entry["snapshot_id"]), {})
        bundle[entry["scope_key"]] = entry
    active = _active_bundle_key(plans, snapshot_id)
    return [
        _bundle(connection, repository_id, key, stages, active=key == active)
        for key, stages in sorted(grouped.items())
    ]


def previous_generation(generations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Point at the newest completed generation that is not the current one."""

    for bundle in reversed(generations):
        if bundle["state"] == "current" or not bundle["review_document_id"]:
            continue
        return {
            "generation": bundle["generation"],
            "snapshot_id": bundle["snapshot_id"],
            "document_id": bundle["review_document_id"],
            "created_at": bundle["last_recorded_at"],
        }
    return None


def _plan_rows(connection: Any, repository_id: int) -> dict[int, dict[str, Any]]:
    rows = connection.execute(
        _PLAN_SQL, (repository_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY)
    ).fetchall()
    return {
        int(row["snapshot_id"]): {
            "generation": fresh_eyes_plan_options(dict(row))[1],
            "status": str(row["status"]),
        }
        for row in rows
    }


def _active_bundle_key(
    plans: dict[int, dict[str, Any]], snapshot_id: int | None
) -> tuple[int, int] | None:
    plan = plans.get(int(snapshot_id)) if snapshot_id else None
    return (plan["generation"], int(snapshot_id)) if plan and snapshot_id else None


def _stage_entries(
    connection: Any, repository_id: int, plans: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    entries: dict[tuple[int, int, str], dict[str, Any]] = {}
    by_hash: dict[tuple[str, str], int] = {}
    for row in connection.execute(_JOB_STAGE_SQL, (repository_id, FRESH_EYES_SCOPE)).fetchall():
        scope_key = str(row["scope_key"])
        if scope_key not in _STAGE_ORDER:
            continue
        generation = _job_generation(row, plans)
        snapshot_id = int(row["snapshot_id"])
        by_hash[(scope_key, str(row["input_hash"]))] = generation
        entries[(generation, snapshot_id, scope_key)] = {
            "generation": generation,
            "snapshot_id": snapshot_id,
            "scope_key": scope_key,
            "input_hash": str(row["input_hash"]),
            "document_id": row["document_id"],
            "job_id": int(row["job_id"]),
            "job_status": str(row["status"]),
        }
    _add_reused_stages(connection, repository_id, plans, by_hash, entries)
    return list(entries.values())


def _add_reused_stages(
    connection: Any,
    repository_id: int,
    plans: dict[int, dict[str, Any]],
    by_hash: dict[tuple[str, str], int],
    entries: dict[tuple[int, int, str], dict[str, Any]],
) -> None:
    """Recover stages whose documents were reused by a later snapshot without a new job."""

    rows = connection.execute(
        _STATE_STAGE_SQL, (repository_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY)
    ).fetchall()
    for row in rows:
        scope_key = str(row["scope_key"])
        input_hash = str(row["context_input_hash"] or "")
        if scope_key not in _STAGE_ORDER or not row["context_document_id"]:
            continue
        snapshot_id = int(row["snapshot_id"])
        generation = by_hash.get(
            (scope_key, input_hash), (plans.get(snapshot_id) or {}).get("generation", 1)
        )
        entries.setdefault(
            (generation, snapshot_id, scope_key),
            {
                "generation": generation,
                "snapshot_id": snapshot_id,
                "scope_key": scope_key,
                "input_hash": input_hash,
                "document_id": int(row["context_document_id"]),
                "job_id": None,
                "job_status": "reused",
            },
        )


def _job_generation(row: Any, plans: dict[int, dict[str, Any]]) -> int:
    metadata = json.loads(row["metadata_json"] or "{}")
    recorded = (metadata.get("input_manifest") or {}).get("review_generation")
    if isinstance(recorded, int) and not isinstance(recorded, bool) and recorded >= 1:
        return recorded
    return int((plans.get(int(row["snapshot_id"])) or {}).get("generation", 1))


def _bundle(
    connection: Any,
    repository_id: int,
    key: tuple[int, int],
    stages: dict[str, dict[str, Any]],
    *,
    active: bool,
) -> dict[str, Any]:
    generation, snapshot_id = key
    ordered = sorted(stages.values(), key=lambda item: _STAGE_ORDER[item["scope_key"]])
    documents = {
        item["scope_key"]: _bundle_document(connection, item["document_id"]) for item in ordered
    }
    records = stage_telemetry(
        connection,
        repository_id,
        [(item["scope_key"], item["input_hash"], item["document_id"]) for item in ordered],
    )
    rows = [records[item["scope_key"]] for item in ordered if item["scope_key"] in records]
    review = documents.get("review")
    return {
        "generation": generation,
        "snapshot_id": snapshot_id,
        "state": _bundle_state(ordered, review, active=active),
        "ready": bool(active and review),
        "stages": [_stage_summary(item, documents.get(item["scope_key"])) for item in ordered],
        **_bundle_totals(ordered, documents, review),
        "telemetry": {"stages": rows, **telemetry_totals(rows)},
    }


def _bundle_totals(
    ordered: list[dict[str, Any]],
    documents: dict[str, dict[str, Any] | None],
    review: dict[str, Any] | None,
) -> dict[str, Any]:
    present = [item for item in documents.values() if item]
    proposals = [
        documents[item["scope_key"]]
        for item in ordered
        if item["scope_key"].startswith("proposal:") and documents.get(item["scope_key"])
    ]
    recorded = sorted(str(item["created_at"]) for item in present)
    return {
        "document_ids": [int(item["id"]) for item in present],
        "review_document_id": int(review["id"]) if review else None,
        "executor_models": sorted(
            {str(item["executor_model"]) for item in present if item["executor_model"]}
        ),
        "diversity": proposal_diversity([dict(item) for item in proposals]),
        "recommendation_count": int((review or {}).get("recommendation_count") or 0),
        "rejected_idea_count": int((review or {}).get("rejected_idea_count") or 0),
        "first_recorded_at": recorded[0] if recorded else None,
        "last_recorded_at": recorded[-1] if recorded else None,
    }


def _stage_summary(entry: dict[str, Any], document: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "key": entry["scope_key"],
        "label": _STAGE_LABELS[entry["scope_key"]],
        "input_hash": entry["input_hash"],
        "document_id": int(document["id"]) if document else None,
        "job_id": entry["job_id"],
        "job_status": entry["job_status"],
    }


def _bundle_state(
    ordered: list[dict[str, Any]], review: dict[str, Any] | None, *, active: bool
) -> str:
    if review is not None:
        return "current" if active else "superseded"
    if any(str(item["job_status"]) == "failed" for item in ordered):
        return "failed"
    return "incomplete"


def _bundle_document(connection: Any, document_id: Any) -> dict[str, Any] | None:
    if not document_id:
        return None
    row = connection.execute(_BUNDLE_DOCUMENT_SQL, (document_id,)).fetchone()
    return dict(row) if row else None


def document_record(connection: Any, document_id: Any) -> dict[str, Any] | None:
    """Read one semantic document with its parsed value."""

    if not document_id:
        return None
    row = connection.execute(
        "SELECT * FROM semantic_documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["value"] = json.loads(result.pop("value_json") or "{}")
    return result


def document_value(connection: Any, document_id: Any) -> dict[str, Any] | None:
    document = document_record(connection, document_id)
    return document["value"] if document else None


def provenance(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Report which provider, model, and executor produced one stage document."""

    if not document:
        return None
    return {
        "provider": document.get("provider"),
        "model": document.get("model"),
        "executor_id": document.get("executor_id"),
        "executor_model": document.get("executor_model"),
        "executor_effort": document.get("executor_effort"),
        "created_at": document.get("created_at"),
    }


def input_manifests(
    connection: Any, repository_id: int, stages: list[tuple[str, Any]]
) -> list[dict[str, Any]]:
    """Read the retained input manifest of each ``(scope_key, input_hash)`` stage identity."""

    result = []
    for scope_key, input_hash in stages:
        if not input_hash:
            continue
        row = connection.execute(
            _MANIFEST_SQL, (repository_id, FRESH_EYES_SCOPE, scope_key, input_hash)
        ).fetchone()
        if row and (record := _manifest_record(row)) is not None:
            result.append(record)
    return result


def _manifest_record(row: Any) -> dict[str, Any] | None:
    metadata = json.loads(row["metadata_json"] or "{}")
    manifest = metadata.get("input_manifest")
    if not manifest:
        return None
    return {
        "scope": row["scope_key"],
        "job_kind": row["job_kind"],
        "status": row["status"],
        "input_hash": row["input_hash"],
        "manifest": manifest,
        "information_boundary": metadata.get("information_boundary"),
    }


def payload_telemetry(stages: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect the stage telemetry already attached to a status payload's stages."""

    rows = [item["telemetry"] for item in stages if item.get("telemetry")]
    return {"stages": rows, **telemetry_totals(rows)}


def capability_brief(status: dict[str, Any]) -> dict[str, Any] | None:
    charter = (status.get("architecture_charter") or {}).get("value") or {}
    return charter.get("capability_brief")


def stage_diversity(stages: list[dict[str, Any]]) -> dict[str, Any]:
    return proposal_diversity([item.get("provenance") or {} for item in stages])


def review_caveats(proposals: list[dict[str, Any]], current: bool) -> list[str]:
    caveats = [
        "AnaxiGraph proves the supplied clean-sheet packet, not the absence of unrelated model context.",
        "Agreement between proposals is evidence of agreement, not proof of correctness.",
    ]
    if proposals and not stage_diversity(proposals)["cross_provider"]:
        caveats.append("The proposals do not represent cross-provider agreement.")
    if not current:
        caveats.append("The review is incomplete; do not treat partial stages as a refactor plan.")
    return caveats
