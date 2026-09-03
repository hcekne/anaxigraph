"""High-level status and explicit start operation for the fixed architecture review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Any

from anaxigraph.semantic_fresh_eyes_consensus import compare_generations
from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    FRESH_EYES_REVIEW_VERSION,
    fresh_eyes_plan_executors,
    fresh_eyes_plan_options,
    fresh_eyes_required_executor,
)
from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
from anaxigraph.semantic_fresh_eyes_executors import unpin_review_executors, waiting_executor_action
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
from anaxigraph.semantic_fresh_eyes_grounding import with_grounding
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
        proposal_executors: Sequence[str] = (),
        retry_failed: bool = False,
        restart: bool = False,
        plan: bool = True,
    ) -> dict[str, Any]:
        """Record the request; plan now, or defer planning to the next executor claim.

        ``proposal_executors`` pins one executor family per slot on the plan token, so a pin
        applies to a new review or a restarted generation, never to one already planned.
        """

        semantic = _review_semantic(config)
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
                proposal_executors=tuple(proposal_executors),
            )
        stage, enqueued = self._plan_outcome(
            repository_id, repository, config, plan=plan, retry_failed=retry_failed
        )
        return {
            "status": "restarted"
            if restart and created
            else "started"
            if created
            else "already_started",
            "plan_stage": stage,
            "enqueued": enqueued,
            "review": self.status(repository_id, semantic),
        }

    def _plan_outcome(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        plan: bool,
        retry_failed: bool,
    ) -> tuple[str, int]:
        """Plan the queue now, or report a deferred stage for the next claim to consume.

        A deferred request is picked up by ``plan_active`` during the next
        ``claim_agent_work`` call that finds the queue otherwise empty, so a busy
        queue keeps the request ``requested`` until it drains.
        """

        if not plan:
            return "deferred", 0
        planned = self._planning.plan(
            repository_id,
            repository,
            config,
            retry_failed=retry_failed,
        )
        return planned.stage, planned.enqueued

    def unpin(self, repository_id: int, semantic: SemanticConfig | None = None) -> dict[str, Any]:
        """Let any executor finish a review whose pinned executor never arrived."""

        released = unpin_review_executors(self._database, repository_id)
        return {
            "status": "unpinned" if released else "not_pinned",
            "unpinned": released,
            "review": self.status(repository_id, semantic),
        }

    def status(
        self,
        repository_id: int,
        semantic: SemanticConfig | None = None,
        *,
        generation: int | None = None,
        compare_with: int | None = None,
    ) -> dict[str, Any]:
        """Read the current review, one recorded generation, or two generations side by side."""

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
            read = partial(
                _generation_view,
                connection,
                repository_id,
                snapshot_id,
                dict(row) if row is not None else None,
                semantic_status,
                generations,
                snapshot,
            )
            payload = read(generation)
            if compare_with is None:
                return payload
            return {**payload, "alignment": compare_generations(payload, read(compare_with))}


def _generation_view(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    plan: dict[str, Any] | None,
    semantic_status: dict[str, Any],
    generations: list[dict[str, Any]],
    snapshot: Mapping[str, Any],
    generation: int | None,
) -> dict[str, Any]:
    """Build the payload of the requested recorded generation, or of the current review.

    Only payloads read from the current snapshot carry its provenance; a recorded generation
    may come from an earlier snapshot and must not be labelled with today's checkout.
    """

    if generation is not None and not _selects_current(plan, generation):
        recorded = generation_payload(
            connection,
            repository_id,
            select_generation(generations, generation),
            generations,
            semantic_status,
        )
        return with_grounding(connection, recorded, review_id=_review_document(recorded))
    if plan is None:
        return _with_snapshot_provenance(
            _not_started_payload(repository_id, snapshot_id, semantic_status, generations),
            snapshot,
        )
    return _with_snapshot_provenance(
        _current_review(connection, repository_id, snapshot_id, plan, semantic_status, generations),
        snapshot,
    )


def _review_semantic(config: AnaxiGraphConfig) -> SemanticConfig:
    """Refuse a review the connected coding agent cannot fund."""

    semantic = config.semantic
    if not semantic.enabled:
        raise ValueError("Build AI understanding before starting a fresh-eyes review")
    if semantic.provider != "agent":
        raise ValueError(
            "Fresh-eyes review uses the connected coding agent's tokens; set semantic.provider: agent"
        )
    return semantic


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


def _review_document(payload: dict[str, Any]) -> Any:
    stage = next((item for item in payload["stages"] if item["key"] == "review"), None)
    return (stage or {}).get("document_id")


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
    executors = fresh_eyes_plan_executors(plan)
    stages = _stage_payloads(connection, repository_id, stage_rows, proposal_count, executors)
    manifests = input_manifests(
        connection,
        repository_id,
        [
            (key, (stage_rows.get(key) or {}).get("context_input_hash"))
            for key, _ in FRESH_EYES_STAGES
        ],
    )
    review_id = plan.get("context_document_id")
    review = document_value(connection, review_id)
    payload = _review_payload(
        repository_id, snapshot_id, plan, stages, review, manifests, semantic_status, generations
    )
    return with_grounding(connection, payload, review_id=review_id)


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
        "declared_context": _declared_context_echo(manifests),
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
    executors: Sequence[str] = (),
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
                "required_executor": fresh_eyes_required_executor(executors, key),
                "state": row.get("status") or "waiting",
                "reason": row.get("reason") or "Waiting for the preceding stage",
                "document_id": document.get("id") if document else None,
                "provenance": provenance(document),
                "telemetry": telemetry.get(key),
                "value": document.get("value") if document else None,
            }
        )
    return result


def _declared_context_echo(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    """Report the declared facts the comparison stage actually saw, not today's corrections."""

    for record in manifests:
        if record["job_kind"] != "fresh_comparison":
            continue
        declared = (record["manifest"].get("current_system") or {}).get("declared_context") or {}
        return {
            "included": int(declared.get("included") or 0),
            "fingerprint": declared.get("fingerprint"),
            "keys": list(declared.get("keys") or []),
        }
    return {"included": 0, "fingerprint": None, "keys": []}


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
    return (
        waiting_executor_action(stages)
        or "Run the connected semantic executor until the fixed review recipe completes."
    )


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
