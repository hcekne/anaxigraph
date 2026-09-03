"""High-level status and explicit start operation for the fixed architecture review."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    FRESH_EYES_REVIEW_VERSION,
    fresh_eyes_plan_options,
)
from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
from anaxigraph.semantic_fresh_eyes_generations import (
    FRESH_EYES_STAGES,
    capability_brief,
    document_record,
    document_value,
    generation_payload,
    input_manifests,
    list_generations,
    payload_telemetry,
    previous_generation,
    provenance,
    review_caveats,
    select_generation,
    stage_diversity,
)
from anaxigraph.semantic_fresh_eyes_plan import (
    FRESH_EYES_PLAN_KEY,
    FRESH_EYES_SCOPE,
    FreshEyesPlanner,
)
from anaxigraph.semantic_fresh_eyes_telemetry import stage_telemetry
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_ports import (
    AnaxiGraphConfig,
    SemanticConfig,
    SemanticPlanningPort,
    SemanticReportingPort,
)
from anaxigraph.snapshot_provenance import dirty_snapshot_caveat, snapshot_provenance

_PLAN_ROW_SQL = (
    "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? AND scope_key = ?"
)


class FreshEyesReviewService:
    def __init__(
        self,
        database: SemanticIndex,
        planner: FreshEyesPlanner,
        planning: SemanticPlanningPort,
        reporting: SemanticReportingPort,
    ) -> None:
        self._database = database
        self._planner = planner
        self._planning = planning
        self._reporting = reporting

    def start(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        proposal_count: int = 2,
        retry_failed: bool = False,
        restart: bool = False,
    ) -> dict[str, Any]:
        semantic = config.semantic
        if not semantic.enabled:
            raise ValueError("Build AI understanding before starting a fresh-eyes review")
        if semantic.provider != "agent":
            raise ValueError(
                "Fresh-eyes review uses the connected coding agent's tokens; set semantic.provider: agent"
            )
        snapshot = self._database.latest_snapshot(repository_id)
        if snapshot is None:
            raise ValueError("Repository has not been scanned")
        snapshot_id = int(snapshot["id"])
        with self._database.transaction() as connection:
            generation = _requested_generation(
                connection, repository_id, snapshot_id, restart=restart
            )
            created = self._planner.request(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                proposal_count=proposal_count,
                generation=generation,
            )
        plan = self._planning.plan(
            repository_id,
            repository,
            config,
            retry_failed=retry_failed,
        )
        return {
            "status": "restarted"
            if restart and created
            else "started"
            if created
            else "already_started",
            "plan_stage": plan.stage,
            "enqueued": plan.enqueued,
            "review": self.status(repository_id, semantic),
        }

    def status(
        self,
        repository_id: int,
        semantic: SemanticConfig | None = None,
        *,
        generation: int | None = None,
    ) -> dict[str, Any]:
        """Read the current review, or one recorded generation when ``generation`` is given."""

        snapshot = self._database.latest_snapshot(repository_id)
        if snapshot is None:
            return _missing_review(repository_id)
        snapshot_id = int(snapshot["id"])
        semantic_status = self._reporting.status(repository_id, semantic)
        with self._database.connect() as connection:
            generations = list_generations(connection, repository_id, snapshot_id)
            row = connection.execute(
                _PLAN_ROW_SQL, (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY)
            ).fetchone()
            plan = dict(row) if row is not None else None
            if generation is not None and not _selects_current(plan, generation):
                return generation_payload(
                    connection,
                    repository_id,
                    select_generation(generations, generation),
                    generations,
                    semantic_status,
                )
            if plan is None:
                return _with_snapshot_provenance(
                    _not_started_payload(repository_id, snapshot_id, semantic_status, generations),
                    snapshot,
                )
            return _with_snapshot_provenance(
                _current_review(
                    connection, repository_id, snapshot_id, plan, semantic_status, generations
                ),
                snapshot,
            )


def _with_snapshot_provenance(
    payload: dict[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Name the checkout this review was read from, and warn when it was not committed."""

    provenance_block = snapshot_provenance(snapshot)
    payload["snapshot"] = provenance_block
    caveat = dirty_snapshot_caveat(provenance_block)
    if caveat:
        payload["caveats"] = [caveat, *payload.get("caveats", [])]
    return payload


def _selects_current(plan: dict[str, Any] | None, generation: int) -> bool:
    return plan is not None and fresh_eyes_plan_options(plan)[1] == int(generation)


def _current_review(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    plan: dict[str, Any],
    semantic_status: dict[str, Any],
    generations: list[dict[str, Any]],
) -> dict[str, Any]:
    proposal_count, _generation = fresh_eyes_plan_options(plan)
    stage_rows = _stage_rows(connection, snapshot_id)
    stages = _stage_payloads(connection, repository_id, stage_rows, proposal_count)
    manifests = input_manifests(
        connection,
        repository_id,
        [
            (key, (stage_rows.get(key) or {}).get("context_input_hash"))
            for key, _ in FRESH_EYES_STAGES
        ],
    )
    review = document_value(connection, plan.get("context_document_id"))
    return _review_payload(
        repository_id, snapshot_id, plan, stages, review, manifests, semantic_status, generations
    )


def _not_started_payload(
    repository_id: int,
    snapshot_id: int,
    semantic_status: dict[str, Any],
    generations: list[dict[str, Any]],
) -> dict[str, Any]:
    previous = previous_generation(generations)
    stale = bool(previous and int(previous["snapshot_id"]) != snapshot_id)
    next_action = (
        "Finish AI understanding first, then start the fresh-eyes review."
        if not semantic_status.get("semantically_ready")
        else "Start a fresh-eyes review with two independent proposals."
    )
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "identity": f"{FRESH_EYES_REVIEW_VERSION}:{repository_id}:{snapshot_id}:none",
        "state": "stale" if stale else "not_started",
        "ready": False,
        "capability_brief": capability_brief(semantic_status),
        "fingerprints": {"capability": None, "reference": None, "comparison": None},
        "stages": [],
        "proposals": [],
        "adjudication": None,
        "comparison": None,
        "strategy": None,
        "recommendations": [],
        "diversity": proposal_diversity([]),
        "input_manifests": [],
        "previous_review": previous,
        "generations": generations,
        "telemetry": payload_telemetry([]),
        "caveats": ["No fresh-eyes review has been requested for the current saved scan."],
        "next_action": next_action,
    }


def _review_payload(
    repository_id: int,
    snapshot_id: int,
    plan: dict[str, Any],
    stages: list[dict[str, Any]],
    review: dict[str, Any] | None,
    manifests: list[dict[str, Any]],
    semantic_status: dict[str, Any],
    generations: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key = {item["key"]: item for item in stages}
    proposals = [
        item for key, item in by_key.items() if key.startswith("proposal:") and item["value"]
    ]
    current = plan["status"] == "current" and review is not None
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "review_generation": fresh_eyes_plan_options(plan)[1],
        "identity": _review_identity(repository_id, snapshot_id, plan),
        "state": "current" if current else _active_state(stages, semantic_status),
        "ready": current,
        "capability_brief": capability_brief(semantic_status),
        "fingerprints": _plan_fingerprints(plan),
        "invalidation_reason": _invalidation_reason(plan),
        "stages": [
            {key: value for key, value in item.items() if key != "value"} for item in stages
        ],
        "proposals": proposals,
        "adjudication": (by_key.get("adjudication") or {}).get("value"),
        "comparison": (by_key.get("comparison") or {}).get("value"),
        "strategy": review,
        "recommendations": list((review or {}).get("recommendations") or []),
        "diversity": stage_diversity(proposals),
        "input_manifests": manifests,
        "previous_review": previous_generation(generations),
        "generations": generations,
        "telemetry": payload_telemetry(stages),
        "caveats": review_caveats(proposals, current),
        "next_action": _next_action(current, stages, semantic_status),
    }


def _plan_fingerprints(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "capability": plan.get("intrinsic_input_hash"),
        "reference": plan.get("context_input_hash"),
        "comparison": plan.get("relationship_hash"),
    }


def _invalidation_reason(plan: dict[str, Any]) -> str | None:
    reason = str(plan.get("reason") or "")
    return reason if reason.startswith("Capability fingerprint") else None


def _stage_rows(connection: Any, snapshot_id: int) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ? "
        "AND scope_key != ?",
        (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
    ).fetchall()
    return {str(row["scope_key"]): dict(row) for row in rows}


def _requested_generation(
    connection: Any, repository_id: int, snapshot_id: int, *, restart: bool
) -> int:
    plan = connection.execute(
        _PLAN_ROW_SQL, (snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY)
    ).fetchone()
    if plan is not None and restart and str(plan["status"]) != "current":
        raise ValueError("Finish or retry the current fresh-eyes review before requesting a rerun")
    prior = (
        plan
        or connection.execute(
            "SELECT * FROM semantic_scope_states WHERE repository_id = ? AND snapshot_id != ? "
            "AND scope_type = ? AND scope_key = ? AND status = 'current' "
            "ORDER BY snapshot_id DESC LIMIT 1",
            (repository_id, snapshot_id, FRESH_EYES_SCOPE, FRESH_EYES_PLAN_KEY),
        ).fetchone()
    )
    if prior is None:
        if restart:
            raise ValueError("Start the first fresh-eyes review before requesting a rerun")
        return 1
    _proposal_count, generation = fresh_eyes_plan_options(dict(prior))
    if restart and plan is not None:
        connection.execute(
            "DELETE FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = ?",
            (snapshot_id, FRESH_EYES_SCOPE),
        )
    return generation + 1 if restart else generation


def _stage_payloads(
    connection: Any,
    repository_id: int,
    rows: dict[str, dict[str, Any]],
    proposal_count: int,
) -> list[dict[str, Any]]:
    planned = [
        (key, label)
        for key, label in FRESH_EYES_STAGES
        if not key.startswith("proposal:") or ord(key[-1]) - ord("a") < proposal_count
    ]
    telemetry = stage_telemetry(
        connection,
        repository_id,
        [
            (
                key,
                (rows.get(key) or {}).get("context_input_hash"),
                (rows.get(key) or {}).get("context_document_id"),
            )
            for key, _label in planned
        ],
    )
    result = []
    for key, label in planned:
        row = rows.get(key) or {}
        document = document_record(connection, row.get("context_document_id"))
        result.append(
            {
                "key": key,
                "label": label,
                "state": row.get("status") or "waiting",
                "reason": row.get("reason") or "Waiting for the preceding stage",
                "document_id": document.get("id") if document else None,
                "provenance": provenance(document),
                "telemetry": telemetry.get(key),
                "value": document.get("value") if document else None,
            }
        )
    return result


def _active_state(stages: list[dict[str, Any]], semantic_status: dict[str, Any]) -> str:
    if not semantic_status.get("semantically_ready"):
        return "waiting_for_understanding"
    if any(str(item["state"]).startswith("failed") for item in stages):
        return "failed"
    return "in_progress"


def _next_action(
    current: bool, stages: list[dict[str, Any]], semantic_status: dict[str, Any]
) -> str:
    if current:
        return "Review the ranked suggestions, then use Guide for any change you choose to make."
    if not semantic_status.get("semantically_ready"):
        return "Complete the AI-created repository understanding; review work will then resume."
    failed = next((item for item in stages if str(item["state"]).startswith("failed")), None)
    if failed:
        return f"Retry the failed {failed['label']} task through the semantic executor."
    return "Run the connected semantic executor until the fixed review recipe completes."


def _review_identity(repository_id: int, snapshot_id: int, plan: dict[str, Any]) -> str:
    fingerprint = str(plan.get("context_fingerprint") or "pending")[:16]
    return f"{FRESH_EYES_REVIEW_VERSION}:{repository_id}:{snapshot_id}:{fingerprint}"


def _missing_review(repository_id: int) -> dict[str, Any]:
    return {
        "contract_version": FRESH_EYES_REVIEW_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "repository_id": repository_id,
        "snapshot_id": None,
        "identity": f"{FRESH_EYES_REVIEW_VERSION}:{repository_id}:missing",
        "state": "not_indexed",
        "ready": False,
        "stages": [],
        "recommendations": [],
        "generations": [],
        "caveats": ["Scan the repository before requesting a fresh-eyes review."],
        "next_action": "Run a structural scan.",
    }
