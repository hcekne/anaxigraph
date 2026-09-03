"""Build the fresh-eyes review payloads every transport returns."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    FRESH_EYES_REVIEW_VERSION,
    fresh_eyes_plan_options,
)
from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
from anaxigraph.semantic_fresh_eyes_executors import waiting_executor_action
from anaxigraph.semantic_fresh_eyes_generations import (
    capability_brief,
    payload_telemetry,
    previous_generation,
    review_caveats,
    stage_diversity,
)


def not_started_payload(
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


def review_payload(
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
        "declared_context": declared_context_echo(manifests),
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


def declared_context_echo(manifests: list[dict[str, Any]]) -> dict[str, Any]:
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


def missing_review(repository_id: int) -> dict[str, Any]:
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
