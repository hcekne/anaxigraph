"""Plan architecture through the existing semantic jobs and immutable document lifecycle."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.architecture_plan_contract import DEFAULT_DIRECTION, PLAN_VERSION
from anaxigraph.portable_paths import record_hash
from anaxigraph.semantic_fresh_eyes_evidence import current_charter, current_system_evidence
from anaxigraph.semantic_fresh_eyes_jobs import document_or_job, upsert_state

SCOPE = "architecture_plan"


def request_plan(
    connection: Any, repository_id: int, snapshot_id: int, direction: str | None = ""
) -> None:
    existing = connection.execute(
        "SELECT interface_hash FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? AND scope_key = 'plan'",
        (snapshot_id, SCOPE),
    ).fetchone()
    controls = json.loads(existing[0] or "{}") if existing else {}
    if existing is None:
        prior = connection.execute(
            "SELECT interface_hash FROM semantic_scope_states WHERE repository_id = ? AND scope_type = ? AND scope_key = 'plan' ORDER BY snapshot_id DESC LIMIT 1",
            (repository_id, SCOPE),
        ).fetchone()
        controls = json.loads(prior[0] or "{}") if prior else {}
    if direction is not None:
        if direction.strip() != controls.get("direction", ""):
            for key in ("selected_option", "selection_source", "selection_rationale"):
                controls.pop(key, None)
        controls["direction"] = direction.strip()
    upsert_state(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_type=SCOPE,
        scope_key="plan",
        status="requested",
        reason="Architecture planning requested",
        interface_hash=json.dumps(controls, sort_keys=True),
    )


def plan_requested(
    connection: Any, *, repository_id: int, snapshot_id: int, semantic: Any, retry_failed: bool
) -> int:
    state = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? AND scope_key = 'plan'",
        (snapshot_id, SCOPE),
    ).fetchone()
    if state is None:
        return 0
    charter = current_charter(connection, snapshot_id)
    if charter is None:
        return 0
    controls = json.loads(state["interface_hash"] or "{}")
    current, manifest = current_system_evidence(connection, repository_id, snapshot_id, charter)
    reviews = _review_documents(connection, snapshot_id)
    packet = {
        "direction": controls.get("direction") or DEFAULT_DIRECTION,
        "direction_source": "user" if controls.get("direction") else "suggested_default",
        "current_system": current,
        "fresh_eyes": reviews,
        "evidence_manifest": manifest,
        "contract_version": PLAN_VERSION,
    }
    input_hash = record_hash(
        {"contract": PLAN_VERSION, "prompt": semantic.prompt_version, "packet": packet}
    )
    _document, created = document_or_job(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        scope_key="plan",
        job_kind="architecture_plan",
        reason="Compare architecture options and choose a target",
        priority=20,
        input_hash=input_hash,
        scope=SCOPE,
        metadata={"planning_packet": packet},
        semantic=semantic,
        retry_failed=retry_failed,
    )
    return created


def plan_request(job: Any) -> dict[str, Any]:
    return {
        "analysis_kind": "architecture_plan",
        "schema_version": PLAN_VERSION,
        "contract": (
            "Build an actionable architecture plan from the supplied map, available pattern reviews, "
            "and Fresh Eyes conclusions. Direction is optional; use the supplied default when blank. "
            "Offer preserving the current design and incremental evolution among the options. "
            "Use strategy preserve and evolve for those required options. Keep two or three options concise. "
            "Choose the best justified target yourself; do not ask for approval or invent requirements. "
            "Explain alternatives, conflicts and assumptions. Each option needs a target diagram and "
            "ordered reversible migration milestones with owners, affected contracts and focused tests. "
            "Reuse stable responsibility keys across current and target graphs. Cite supplied evidence. "
            "Unknown deployment facts stay unknown. More infrastructure is justified only by evidenced "
            "requirements. A selected target is a proposal, not an observed implementation."
        ),
        **job["metadata"]["planning_packet"],
    }


def _review_documents(connection: Any, snapshot_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT sd.value_json,sd.document_kind,sd.input_hash FROM semantic_scope_states ss "
        "JOIN semantic_documents sd ON sd.id = ss.context_document_id "
        "WHERE ss.snapshot_id = ? AND ss.scope_type = 'fresh_eyes' AND ss.status = 'current' "
        "AND sd.document_kind IN ('fresh_adjudication','fresh_comparison','fresh_review')",
        (snapshot_id,),
    )
    return [
        {
            "kind": row["document_kind"],
            "fingerprint": row["input_hash"],
            "value": json.loads(row["value_json"]),
        }
        for row in rows
    ]
