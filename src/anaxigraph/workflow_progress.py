"""Small current-review progress without reading proposals or retained input manifests."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
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
           FROM semantic_scope_states ss LEFT JOIN semantic_documents d
             ON d.id = ss.context_document_id
           WHERE ss.snapshot_id = ? AND ss.scope_type = 'fresh_eyes'""",
        (snapshot_id,),
    ).fetchall()
    states = {row["scope_key"]: dict(row) for row in rows}
    plan = states.get("plan")
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
