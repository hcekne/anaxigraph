"""Connect one structural scan to the smallest required semantic refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.architecture_reassessment import semantic_refresh_projection
from anaxigraph.reassessment_evidence import reassessment_evidence
from anaxigraph.understanding import SemanticEngine

SEMANTIC_SCAN_REFRESH_VERSION = "semantic-scan-refresh-v1"
_PATH_LIMIT = 100


def semantic_refresh_after_scan(
    database: Any,
    *,
    repository_id: int,
    repository: str | Path,
    snapshot_id: int,
    baseline_snapshot_id: int | None,
    config: Any,
    prepare: bool | None = None,
) -> dict[str, Any]:
    """Prepare hash-invalidated work and return a bounded handoff for an agent."""

    enabled, should_prepare, planning, semantic = _semantic_state(
        SemanticEngine(database), repository_id, repository, config, prepare
    )

    evidence = _comparison_evidence(
        database,
        repository_id,
        baseline_snapshot_id=baseline_snapshot_id,
        target_snapshot_id=snapshot_id,
    )
    projection = _bounded_projection(semantic_refresh_projection(evidence, semantic))
    refresh = {
        "contract_version": SEMANTIC_SCAN_REFRESH_VERSION,
        "policy": config.semantic.refresh,
        "preparation": _preparation(enabled, should_prepare, prepare, planning),
        **projection,
    }
    refresh["next_action"] = _next_action(refresh, semantic)
    return {"semantic": semantic, "refresh": refresh}


def _semantic_state(
    engine: SemanticEngine,
    repository_id: int,
    repository: str | Path,
    config: Any,
    requested: bool | None,
) -> tuple[bool, bool, dict[str, Any], dict[str, Any]]:
    enabled = bool(config.semantic.enabled)
    prepare = enabled and (
        requested is True or (requested is None and config.semantic.refresh == "on_scan")
    )
    planning = (
        engine.bootstrap(repository_id, repository, config, plan_only=True) if prepare else {}
    )
    semantic = planning.get("semantic") or engine.status(repository_id, config.semantic)
    return enabled, prepare, planning, semantic


def _comparison_evidence(
    database: Any,
    repository_id: int,
    *,
    baseline_snapshot_id: int | None,
    target_snapshot_id: int,
) -> dict[str, Any]:
    if baseline_snapshot_id is None or baseline_snapshot_id == target_snapshot_id:
        return {"module_changes": [], "semantic_scopes": {}}
    try:
        return reassessment_evidence(
            database,
            repository_id,
            baseline_snapshot_id=baseline_snapshot_id,
            target_snapshot_id=target_snapshot_id,
        )
    except ValueError as exc:
        fallback = reassessment_evidence(
            database,
            repository_id,
            target_snapshot_id=target_snapshot_id,
        )
        fallback["comparison_caveat"] = str(exc)
        return fallback


def _preparation(
    enabled: bool,
    prepared: bool,
    requested: bool | None,
    planning: dict[str, Any],
) -> dict[str, Any]:
    if not enabled:
        status = "disabled"
        reason = "AI mapping is disabled for this repository."
    elif prepared:
        status = "prepared"
        reason = (
            "The scan explicitly requested semantic preparation."
            if requested is True
            else "The repository's on-scan policy prepared only invalidated semantic work."
        )
    else:
        status = "not_prepared"
        reason = (
            "This scan explicitly skipped semantic preparation."
            if requested is False
            else "The repository uses manual or watcher-owned semantic refresh."
        )
    return {
        "status": status,
        "reason": reason,
        "enqueued": int(planning.get("planned") or 0),
        "stages": list(planning.get("stages") or []),
        "work_plan": dict(planning.get("work_plan") or {}),
    }


def _bounded_projection(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    counts: dict[str, dict[str, int]] = {}
    for key in (
        "changed_modules",
        "semantic_reread_modules",
        "text_only_modules",
        "removed_modules",
        "affected_modules",
        "affected_groups",
    ):
        items = list(result.get(key) or [])
        result[key] = items[:_PATH_LIMIT]
        counts[key] = {
            "total": len(items),
            "returned": min(len(items), _PATH_LIMIT),
            "omitted": max(0, len(items) - _PATH_LIMIT),
        }
    states = list(result.get("scope_states") or [])
    result["scope_states"] = states[:_PATH_LIMIT]
    counts["scope_states"] = {
        "total": len(states),
        "returned": min(len(states), _PATH_LIMIT),
        "omitted": max(0, len(states) - _PATH_LIMIT),
    }
    result["bounded_counts"] = counts
    return result


def _next_action(refresh: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    if not refresh["enabled"]:
        return {
            "kind": "none",
            "message": "The structural map is current; AI mapping is not enabled.",
        }
    if refresh["preparation"]["status"] == "not_prepared":
        return {
            "kind": "prepare_changed_semantics",
            "tool": "ANAXIGRAPH_SCAN",
            "arguments": {"refresh_semantics": True},
            "message": (
                "Prepare only the file and neighboring AI descriptions invalidated by their "
                "current hashes."
            ),
        }
    if refresh["semantically_ready"]:
        return {
            "kind": "reassess",
            "tool": "ANAXIGRAPH_GUIDE",
            "arguments": {"intent": "reassess"},
            "message": "The affected AI map is current; reassess the completed change.",
        }
    recommended = dict(semantic.get("recommended_action") or {})
    return {
        **recommended,
        "kind": recommended.get("kind") or "finish_semantic_refresh",
        "then": {"tool": "ANAXIGRAPH_GUIDE", "arguments": {"intent": "reassess"}},
    }
