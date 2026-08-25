"""Project semantic coverage, readiness, provenance, and budget status."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_status_queries import SemanticStatusRows

_TERMINAL_FAILURES = (
    "failed_intrinsic",
    "failed_context",
    "failed_synthesis",
    "failed_taxonomy",
    "failed_pattern",
)


@dataclass(frozen=True, slots=True)
class SemanticCoverage:
    excluded: int
    total: int
    eligible: int
    current: int
    failed: int
    pending: int
    pending_scopes: int
    failed_scopes: int
    taxonomy_enabled: bool
    taxonomy_ready: bool
    baseline_complete: bool
    semantically_ready: bool


def semantic_status_payload(
    snapshot_id: int,
    semantic: SemanticConfig | None,
    rows: SemanticStatusRows,
) -> dict[str, Any]:
    coverage = _coverage(rows, semantic)
    return {
        **_identity_payload(snapshot_id, semantic, coverage),
        **_coverage_payload(rows, coverage),
        "usage": _usage_payload(rows),
        "budget": _budget_payload(rows, semantic, coverage),
        "repository_dossier": _repository_document(rows.repository_state),
        "taxonomy": _taxonomy_payload(rows.taxonomy, semantic, coverage),
        "patterns": _pattern_payload(rows, semantic),
        "recommended_action": _recommended_action(rows, semantic, coverage),
    }


def _recommended_action(
    rows: SemanticStatusRows,
    semantic: SemanticConfig | None,
    coverage: SemanticCoverage,
) -> dict[str, Any]:
    remaining = coverage.pending + coverage.pending_scopes
    if not semantic or not semantic.enabled:
        return {
            "kind": "enable_semantics",
            "message": "Enable semantic analysis in the authoritative repository policy.",
        }
    if coverage.semantically_ready:
        return {"kind": "none", "message": "The semantic map is current."}
    if rows.jobs.get("running_live", 0):
        return {
            "kind": "monitor",
            "command": "anaxigraph semantic-status <repository>",
            "message": "A live executor owns semantic work; monitor its durable progress.",
        }
    if remaining >= 50:
        return {
            "kind": "durable_host_executor",
            "command": "anaxigraph understand <repository> --executor codex --background",
            "status_command": "anaxigraph semantic-status <repository>",
            "message": "Use a detached host executor for this repository-sized queue.",
        }
    return {
        "kind": "bounded_mcp_fallback",
        "message": (
            "Use the durable host executor, or process this bounded queue with "
            "ANAXIGRAPH_SEMANTIC_WORK and verify status afterward."
        ),
    }


def _coverage(rows: SemanticStatusRows, semantic: SemanticConfig | None) -> SemanticCoverage:
    excluded = rows.counts.get("excluded", 0)
    total = sum(rows.counts.values())
    eligible = max(0, total - excluded)
    current = rows.counts.get("current", 0)
    failed = sum(rows.counts.get(key, 0) for key in _TERMINAL_FAILURES)
    pending = _pending(rows.counts)
    pending_scopes, failed_scopes = _non_module_metrics(rows.scope_counts)
    repository_ready = bool(rows.repository_state and rows.repository_state["status"] == "current")
    taxonomy_enabled = bool(semantic and semantic.enabled and semantic.taxonomy.enabled)
    taxonomy_ready = bool(rows.taxonomy and rows.taxonomy["status"] == "current")
    baseline_complete = total > 0 and pending == 0 and pending_scopes == 0
    ready = _is_ready(
        eligible,
        current,
        failed,
        failed_scopes,
        repository_ready,
        taxonomy_enabled,
        taxonomy_ready,
    )
    return SemanticCoverage(
        excluded,
        total,
        eligible,
        current,
        failed,
        pending,
        pending_scopes,
        failed_scopes,
        taxonomy_enabled,
        taxonomy_ready,
        baseline_complete,
        ready,
    )


def _non_module_metrics(
    scope_counts: dict[str, dict[str, int]],
) -> tuple[int, int]:
    counts = [values for key, values in scope_counts.items() if key != "module"]
    pending = sum(_pending(values) for values in counts)
    failed = sum(
        count for values in counts for key, count in values.items() if key in _TERMINAL_FAILURES
    )
    return pending, failed


def _is_ready(
    eligible: int,
    current: int,
    failed: int,
    failed_scopes: int,
    repository_ready: bool,
    taxonomy_enabled: bool,
    taxonomy_ready: bool,
) -> bool:
    taxonomy_complete = taxonomy_ready or not taxonomy_enabled
    return all(
        (
            eligible > 0,
            current == eligible,
            failed == 0,
            failed_scopes == 0,
            repository_ready,
            taxonomy_complete,
        )
    )


def _pending(counts: dict[str, int]) -> int:
    return sum(
        count
        for key, count in counts.items()
        if key.startswith("pending_") or key == "intrinsic_current"
    )


def _identity_payload(
    snapshot_id: int,
    semantic: SemanticConfig | None,
    coverage: SemanticCoverage,
) -> dict[str, Any]:
    return {
        "enabled": bool(semantic and semantic.enabled),
        "provider": semantic.provider if semantic else None,
        "model": semantic.model if semantic else None,
        "execution_mode": (
            "coding_agent" if semantic and semantic.provider == "agent" else "worker"
        ),
        "refresh": semantic.refresh if semantic else None,
        "snapshot_id": snapshot_id,
        "state": (
            "ready"
            if coverage.semantically_ready
            else "complete_with_failures"
            if coverage.baseline_complete
            else "pending"
            if coverage.total
            else "not_started"
        ),
        "semantically_ready": coverage.semantically_ready,
        "baseline_complete": coverage.baseline_complete,
    }


def _coverage_payload(rows: SemanticStatusRows, coverage: SemanticCoverage) -> dict[str, Any]:
    return {
        "total_modules": coverage.total,
        "eligible_modules": coverage.eligible,
        "current": coverage.current,
        "intrinsic_current": rows.counts.get("intrinsic_current", 0),
        "pending": coverage.pending,
        "failed": coverage.failed,
        "failed_scopes": coverage.failed_scopes,
        "excluded": coverage.excluded,
        "coverage": coverage.current / coverage.eligible if coverage.eligible else None,
        "counts": rows.counts,
        "scope_counts": rows.scope_counts,
        "pending_scopes": coverage.pending_scopes,
        "jobs": rows.jobs,
        "last_reconciled_at": rows.last_checked,
    }


def _usage_payload(rows: SemanticStatusRows) -> dict[str, Any]:
    return {
        "input_tokens": int(rows.usage["input_tokens"]),
        "output_tokens": int(rows.usage["output_tokens"]),
        "cost_usd": round(float(rows.usage["cost"]), 6),
    }


def _budget_payload(
    rows: SemanticStatusRows,
    semantic: SemanticConfig | None,
    coverage: SemanticCoverage,
) -> dict[str, Any]:
    limit = semantic.daily_budget_usd if semantic else None
    projected = rows.daily_spend + rows.reserved_spend + rows.next_estimated_cost
    has_pending = coverage.pending > 0 or coverage.pending_scopes > 0
    return {
        "daily_limit_usd": limit,
        "spent_today_usd": round(rows.daily_spend, 6),
        "reserved_running_usd": round(rows.reserved_spend, 6),
        "remaining_today_usd": (
            round(max(0.0, limit - rows.daily_spend - rows.reserved_spend), 6)
            if limit is not None
            else None
        ),
        "next_job_estimated_usd": round(rows.next_estimated_cost, 6),
        "paused": bool(limit is not None and projected > limit and has_pending),
    }


def _repository_document(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state or not state["value_json"]:
        return None
    return {
        "status": state["status"],
        "value": json.loads(state["value_json"]),
        "confidence": state["confidence"],
        "provider": state["provider"],
        "model": state["model"],
        "executor_id": state["executor_id"],
        "executor_model": state["executor_model"],
        "prompt_version": state["prompt_version"],
        "created_at": state["created_at"],
    }


def _taxonomy_document(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "confidence": row["confidence"],
        "provider": row["provider"],
        "model": row["model"],
        "executor_id": row["executor_id"],
        "executor_model": row["executor_model"],
        "prompt_version": row["prompt_version"],
        "review_passes": row["review_passes"],
        "stored_reviews": row["stored_reviews"],
        "validation": json.loads(row["validation_json"] or "{}"),
        "facets": json.loads(row["facets_json"] or "[]"),
        "changes": json.loads(row["change_json"] or "[]"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _taxonomy_payload(
    row: dict[str, Any] | None,
    semantic: SemanticConfig | None,
    coverage: SemanticCoverage,
) -> dict[str, Any]:
    return {
        "enabled": coverage.taxonomy_enabled,
        "ready": coverage.taxonomy_ready,
        "required_review_passes": (
            semantic.taxonomy.review_passes if semantic and coverage.taxonomy_enabled else 0
        ),
        "current": _taxonomy_document(row),
    }


def _pattern_payload(
    rows: SemanticStatusRows,
    semantic: SemanticConfig | None,
) -> dict[str, Any]:
    counts = rows.scope_counts.get("pattern", {})
    plan_counts = rows.scope_counts.get("pattern_plan", {})
    selected = sum(counts.values())
    pending = _pending(counts)
    failed = counts.get("failed_pattern", 0)
    planned = bool(plan_counts.get("current"))
    return {
        "enabled": bool(semantic and semantic.enabled),
        "planned": planned,
        "ready": planned and pending == 0 and failed == 0,
        "selected": selected,
        "finalized": counts.get("current", 0),
        "pending": pending,
        "failed": failed,
        "counts": counts,
    }
