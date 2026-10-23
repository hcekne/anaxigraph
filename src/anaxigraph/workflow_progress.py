"""Small current-review progress without reading proposals or retained input manifests."""

from __future__ import annotations

from typing import Any

from anaxigraph.review_inputs import comparison_pattern_inputs
from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
from anaxigraph.semantic_fresh_eyes_functional import functional_plan_options, is_functional_plan
from anaxigraph.semantic_fresh_eyes_plan import (
    fresh_eyes_plan_executors,
    fresh_eyes_plan_options,
)


def fresh_review_progress(
    connection: Any, repository_id: int, snapshot_id: int, semantic: dict[str, Any]
) -> dict[str, Any]:
    rows = connection.execute(
        """SELECT ss.*, d.id AS document_id, d.provider, d.model, d.executor_id,
           d.executor_model, d.created_at,
           CASE WHEN ss.scope_key = 'review' THEN json_array_length(d.value_json, '$.recommendations') END AS recommendations
           FROM semantic_scope_states ss LEFT JOIN semantic_document_values d
             ON d.id = ss.context_document_id
           WHERE ss.snapshot_id = ? AND ss.scope_type = 'fresh_eyes'""",
        (snapshot_id,),
    ).fetchall()
    states = {row["scope_key"]: dict(row) for row in rows}
    plan = states.get("plan")
    if plan and is_functional_plan(plan):
        return _functional_progress(connection, repository_id, snapshot_id, states, plan)
    stages = _stages(states, plan)
    proposals = [
        item for item in stages if item["key"].startswith("proposal:") and item["document_id"]
    ]
    ready = bool(
        plan and plan["status"] == "current" and states.get("review", {}).get("document_id")
    )
    count = int(states.get("review", {}).get("recommendations") or 0)
    prior = connection.execute(
        "SELECT MAX(snapshot_id) FROM semantic_scope_states WHERE repository_id = ? AND snapshot_id < ? AND scope_type = 'fresh_eyes'",
        (repository_id, snapshot_id),
    ).fetchone()[0]
    state = (
        ("current" if ready else "in_progress") if plan else ("stale" if prior else "not_started")
    )
    return {
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "state": state,
        "ready": ready,
        "capability_brief": bool(semantic.get("architecture_charter")),
        "stages": stages,
        "proposals": proposals,
        "recommendation_count": count,
        "diversity": proposal_diversity([item["provenance"] for item in proposals]),
        "previous_snapshot_id": prior,
        "details_available": "/api/fresh-eyes",
        "pattern_inputs": comparison_pattern_inputs(connection, snapshot_id),
    }


def _functional_progress(connection, repository_id, snapshot_id, states, plan):
    stages = [
        {
            "key": key,
            "state": row["status"],
            "reason": row["reason"],
            "document_id": row["document_id"],
            "required_executor": _functional_executor(plan, key),
            "provenance": {
                field: row.get(field)
                for field in ("provider", "model", "executor_id", "executor_model", "created_at")
            },
        }
        for key, row in sorted(states.items())
        if key.startswith("functional:")
    ]
    proposals = [stage for stage in stages if ":proposal:" in stage["key"]]
    scope_count = connection.execute(
        "SELECT json_array_length(value_json,'$.scopes') FROM semantic_document_values WHERE id=?",
        (states.get("functional:brief", {}).get("document_id"),),
    ).fetchone()
    ready = plan["status"] == "current" and bool(
        states.get("functional:review", {}).get("document_id")
    )
    return {
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "contract_version": "functional-review-v2",
        "ready": ready,
        "state": "current" if ready else "in_progress",
        "capability_brief": bool(scope_count),
        "stages": stages,
        "proposals": proposals,
        "recommendation_count": 0,
        "details_available": "/api/fresh-eyes",
        "counts": {
            "total_scopes": int(scope_count[0] or 0) if scope_count else 0,
            "alternatives_per_scope": functional_plan_options(plan)[0],
        },
        "diversity": proposal_diversity([stage["provenance"] for stage in proposals]),
    }


def _stages(states: dict[str, Any], plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if plan is None:
        return []
    count, _generation = fresh_eyes_plan_options(plan)
    executors = fresh_eyes_plan_executors(plan)
    keys = [f"proposal:{slot}" for slot in "abc"[:count]] + ["adjudication", "comparison", "review"]
    result = []
    for index, key in enumerate(keys):
        row = states.get(key, {})
        result.append(
            {
                "key": key,
                "state": row.get("status", "waiting"),
                "reason": row.get("reason"),
                "document_id": row.get("document_id"),
                "required_executor": executors[index]
                if key.startswith("proposal:") and index < len(executors)
                else None,
                "provenance": {
                    field: row.get(field)
                    for field in (
                        "provider",
                        "model",
                        "executor_id",
                        "executor_model",
                        "created_at",
                    )
                },
            }
        )
    return result


def _functional_executor(plan, key):
    if ":proposal:" not in key:
        return None
    executors = fresh_eyes_plan_executors(plan)
    index = ord(key.rsplit(":", 1)[1]) - ord("a")
    provider = executors[index] if 0 <= index < len(executors) else None
    return None if provider == "any" else provider


def compact_workflow_semantic(semantic: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in semantic.items()
        if key not in {"charter_corrections", "architecture_charter", "telemetry", "taxonomy"}
    }
    charter = semantic.get("architecture_charter")
    result["architecture_charter"] = (
        {
            key: charter.get(key)
            for key in ("status", "source_snapshot_id", "document_id", "created_at")
        }
        if charter
        else None
    )
    taxonomy = semantic.get("taxonomy") or {}
    current = taxonomy.get("current")
    result["taxonomy"] = {
        **taxonomy,
        "current": {
            key: current.get(key) for key in ("id", "status", "stored_reviews", "validation")
        }
        if current
        else None,
    }
    result["telemetry"] = {
        "semantic": {
            "current_snapshot": ((semantic.get("telemetry") or {}).get("semantic") or {}).get(
                "current_snapshot", {}
            )
        }
    }
    return result


def completed_steps(status: Any, coverage: Any, fresh: Any) -> set[str]:
    scopes = coverage.get("scopes", {})
    modules, groups = scopes.get("module", {}), scopes.get("group", {})
    total = modules.get("total", 0) - modules.get("excluded", 0)
    taxonomy = status.get("taxonomy", {})
    current = taxonomy.get("current") or {}
    patterns = status.get("patterns", {})
    pattern = scopes.get("pattern", {})
    checks = {
        "annotation": bool(modules) and modules.get("current", 0) == total,
        "contracts": bool(coverage.get("graph", {}).get("contracts_ready")),
        "architecture_plan": scopes.get("architecture_plan", {}).get("current", 0) > 0,
        "intrinsic": bool(modules) and modules.get("intrinsic", 0) == total,
        "context": bool(modules) and modules.get("current", 0) == total,
        "taxonomy_proposal": bool(current) or not taxonomy.get("enabled"),
        "taxonomy_review": taxonomy.get("ready") or not taxonomy.get("enabled"),
        "groups": bool(groups) and groups.get("current", 0) == groups.get("total", 0),
        "charter": (status.get("architecture_charter") or {}).get("status") == "current",
        "pattern_plan": patterns.get("planned"),
        "pattern_assessment": patterns.get("planned")
        and max(pattern.get("current", 0), pattern.get("intrinsic", 0)) == patterns.get("selected"),
        "pattern_review": patterns.get("planned")
        and pattern.get("current", 0) == patterns.get("selected"),
        "brief": bool(fresh.get("functional_brief") or fresh.get("capability_brief")),
        "grounding": fresh.get("ready"),
    }
    checks.update(_fresh_steps(fresh))
    catalogue = patterns.get("catalogue")
    if catalogue:
        checks["pattern_assessment"] = (
            catalogue.get("expected", 0) > 0 and catalogue.get("rated") == catalogue["expected"]
        )
        checks["pattern_review"] = bool(catalogue.get("complete"))
    return {step for step, ready in checks.items() if ready}


def _fresh_steps(fresh):
    checks = {}
    stages = fresh.get("stages", [])
    functional = fresh.get("contract_version") == "functional-review-v2"
    for step, key in (
        ("proposals", "proposal:"),
        ("adjudication", "adjudication"),
        ("comparison", "comparison"),
        ("mission_filter", "review"),
    ):
        matching = [stage for stage in stages if _stage_matches(stage["key"], key, functional)]
        checks[step] = bool(matching) and all(stage["state"] == "current" for stage in matching)
    if functional:
        expected = fresh.get("counts", {}).get("total_scopes", 0)
        alternatives = fresh.get("counts", {}).get("alternatives_per_scope", 3)
        expected_alternatives = fresh.get("counts", {}).get(
            "expected_alternatives", expected * alternatives
        )
        proposals = [stage for stage in stages if ":proposal:" in stage["key"]]
        checks["proposals"] = (
            expected > 0
            and len(proposals) == expected_alternatives
            and all(stage["state"] == "current" for stage in proposals)
        )
        completed = sum(
            stage["key"].endswith(":comparison") and stage["state"] == "current" for stage in stages
        )
        checks["comparison"] = expected > 0 and completed == expected
    return checks


def _stage_matches(stage, key, functional):
    if not functional:
        return stage.startswith(key)
    if key == "proposal:":
        return ":proposal:" in stage
    return stage == {"adjudication": "functional:brief", "review": "functional:review"}.get(
        key
    ) or (key == "comparison" and stage.endswith(":comparison"))
