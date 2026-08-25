"""Compact architecture decisions for bounded coding-agent responses."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anaxigraph.agent_change_effects import compact_structural_effects
from anaxigraph.agent_decision_handoff_language import compact_explanation
from anaxigraph.agent_decomposition import compact_decomposition
from anaxigraph.agent_task_path import compact_task_path


def compact_architecture_decision(decision: dict[str, Any]) -> dict[str, Any]:
    patterns = _compact_pattern_counts(decision.get("patterns"))
    decomposition = compact_decomposition(decision.get("decomposition"))
    result = {
        "contract_version": decision.get("contract_version"),
        "snapshot_id": decision.get("snapshot_id"),
        "status": decision.get("status"),
        "plain_language": compact_explanation(decision.get("plain_language"), "conclusion"),
        "task_path": compact_task_path(decision.get("task_path")),
        "placement": _compact_placement(decision.get("placement")),
    }
    if history := _compact_history_evidence(decision):
        result["history_evidence"] = history
    _add_nonempty_counts(result, decision, patterns, decomposition)
    if verification := _compact_verification(decision.get("verification")):
        result["verification"] = verification
    return result


def fit_verification_to_budget(
    decision: dict[str, Any], *, current_size: Callable[[], int], limit: int
) -> dict[str, int]:
    """Remove a baseline only when the configured response limit cannot hold it."""

    if current_size() <= limit:
        return {}
    verification = decision.get("verification") or {}
    if verification.pop("post_change_baseline", None) is None:
        return {}
    verification["post_change_baseline_status"] = {
        "status": "omitted_for_payload_limit",
        "reason": (
            "The configured scope response limit is too small for the before-change record. "
            "Request scope again with a larger agent.payload_limit_bytes value before editing "
            "when you need post-change comparison."
        ),
    }
    omitted = {"verification_baseline": 1}
    if current_size() > limit and (comparison := verification.get("post_change_comparison")):
        verification["post_change_comparison"] = {
            key: comparison.get(key)
            for key in (
                "contract_version",
                "status",
                "baseline_snapshot_id",
                "current_snapshot_id",
            )
        }
        omitted["verification_details"] = 1
    return omitted


def _compact_history_evidence(decision: dict[str, Any]) -> dict[str, Any]:
    coupling = (decision.get("history_evidence") or {}).get("change_coupling") or {}
    if not coupling:
        return {}
    fields = ("selected_path", "partner_path", "shared_commits", "relationship_kind")
    return {
        "change_coupling": {
            "status": coupling.get("status"),
            "window_commits": coupling.get("window_commits"),
            "items": [
                {key: item.get(key) for key in fields} for item in (coupling.get("items") or [])[:3]
            ],
        }
    }


def _compact_verification(value: Any) -> dict[str, Any]:
    verification = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    if baseline := verification.get("post_change_baseline"):
        result["post_change_baseline"] = baseline
    comparison = verification.get("post_change_comparison") or {}
    if not comparison:
        return result
    effects = (comparison.get("changes") or {}).get("structural_effects")
    compact_effects = compact_structural_effects(effects)
    effect_changes = any(
        compact_effects[name] for name in compact_effects if name != "omitted_count"
    )
    keys = (
        "contract_version",
        "status",
        "summary",
        "baseline_snapshot_id",
        "current_snapshot_id",
        "interpretation",
    )
    compact = {key: comparison.get(key) for key in keys}
    if effect_changes or compact_effects["omitted_count"]:
        compact["changes"] = {"structural_effects": compact_effects}
    result["post_change_comparison"] = compact
    return result


def _add_nonempty_counts(
    result: dict[str, Any],
    decision: dict[str, Any],
    patterns: dict[str, Any],
    decomposition: dict[str, Any],
) -> None:
    values = {
        "consolidation_count": len(decision.get("consolidation") or []),
        "change_constraint_count": len(
            (decision.get("change_constraints") or {}).get("items") or []
        ),
        "dead_code_candidate_count": (decision.get("dead_code") or {}).get("candidate_count", 0),
    }
    result.update({key: value for key, value in values.items() if value})
    if patterns.get("total"):
        result["patterns"] = patterns
    if decomposition.get("items"):
        result["decomposition"] = decomposition


def _compact_placement(value: Any) -> dict[str, Any]:
    placement = value if isinstance(value, dict) else {}
    return {
        "preferred_path": placement.get("preferred_path"),
        "plain_language": compact_explanation(placement.get("plain_language"), "conclusion"),
    }


def _compact_pattern_counts(value: Any) -> dict[str, Any]:
    patterns = value if isinstance(value, dict) else {}
    return {"status": patterns.get("status"), "total": patterns.get("total", 0)}
