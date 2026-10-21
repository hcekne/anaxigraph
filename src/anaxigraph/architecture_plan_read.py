"""Read and steer a saved target without making human input a prerequisite."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from anaxigraph.agent_response import small_agent_response
from anaxigraph.architecture_plan_contract import DEFAULT_DIRECTION
from anaxigraph.portable_paths import record_hash


def architecture_plan_status(
    database: Any, repository_id: int, *, details: bool = True
) -> dict[str, Any]:
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        return {"state": "not_started", "ready": False, "default_direction": DEFAULT_DIRECTION}
    with database.connect() as connection:
        row = connection.execute(
            "SELECT sd.*, ss.interface_hash AS controls, ss.status AS scope_status FROM semantic_scope_states ss "
            "LEFT JOIN semantic_documents sd ON sd.id = ss.context_document_id "
            "WHERE ss.repository_id = ? AND ss.scope_type = 'architecture_plan' AND ss.scope_key = 'plan' "
            "ORDER BY (sd.value_json IS NOT NULL) DESC,(ss.snapshot_id = ?) DESC,ss.snapshot_id DESC LIMIT 1",
            (repository_id, snapshot["id"]),
        ).fetchone()
    if row is None or row["value_json"] is None:
        return {
            "state": row["scope_status"] if row else "not_started",
            "ready": False,
            "snapshot_id": snapshot["id"],
            "default_direction": DEFAULT_DIRECTION,
        }
    return _saved_plan(row, snapshot, details)


def _saved_plan(row: Any, snapshot: Any, details: bool) -> dict[str, Any]:
    value = json.loads(row["value_json"])
    controls = json.loads(row["controls"] or "{}")
    selected_key = controls.get("selected_option") or value["selected_option"]
    if selected_key not in {option["key"] for option in value["options"]}:
        selected_key = value["selected_option"]
        for field in ("selection_source", "selection_rationale"):
            controls.pop(field, None)
    target = next((option for option in value["options"] if option["key"] == selected_key), None)
    current = row["snapshot_id"] == snapshot["id"] and row["scope_status"] == "current"
    result = _plan_projection(value, controls, selected_key, target, current, row, snapshot)
    if details:
        result.update(
            value=value,
            diagrams=architecture_diagrams(value["current"], target["target"] if target else {}),
        )
    elif target:
        result["target"] = {key: target[key] for key in ("key", "title", "summary")}
        result["progress"] = {
            key: {field: item.get(field) for field in ("status", "reported_by", "reported_at")}
            for key, item in result["progress"].items()
        }
    return result


def _plan_projection(
    value: Any,
    controls: Any,
    selected_key: str,
    target: Any,
    current: bool,
    row: Any,
    snapshot: Any,
) -> dict[str, Any]:
    return {
        "state": "current" if current else "stale",
        "ready": current,
        "snapshot_id": snapshot["id"],
        "source_snapshot_id": row["snapshot_id"],
        "default_direction": DEFAULT_DIRECTION,
        "direction": value["direction"],
        "user_direction": controls.get("direction", ""),
        "summary": value["summary"],
        "selected_option": selected_key,
        "option_count": len(value["options"]),
        "milestone_count": len(target["milestones"]) if target else 0,
        "selection_source": controls.get("selection_source", "agent"),
        "selection_rationale": controls.get("selection_rationale") or value["selection_rationale"],
        "progress": _target_progress(controls, selected_key, target),
        "target": target,
        "provenance": {
            key: row[key]
            for key in ("provider", "model", "executor_id", "executor_model", "created_at")
        },
    }


def steer_plan(
    database: Any,
    repository_id: int,
    *,
    option: str = "",
    milestone: str = "",
    status: str = "",
    evidence: list[str] | None = None,
    actor: str = "user",
) -> dict[str, Any]:
    plan = architecture_plan_status(database, repository_id)
    if not plan.get("value"):
        raise ValueError("Run architecture planning before steering the target")
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT interface_hash FROM semantic_scope_states WHERE snapshot_id = ? AND scope_type = 'architecture_plan' AND scope_key = 'plan'",
            (plan["source_snapshot_id"],),
        ).fetchone()
        controls = json.loads(row[0] or "{}")
        if option:
            if option not in {item["key"] for item in plan["value"]["options"]}:
                raise ValueError("Select an option from the saved architecture plan")
            controls.update(
                selected_option=option,
                selection_source=actor,
                selection_rationale="Selected from the saved architecture options",
            )
            plan = {
                **plan,
                "selected_option": option,
                "target": next(item for item in plan["value"]["options"] if item["key"] == option),
            }
        if milestone:
            _milestone_progress(controls, plan, milestone, status, evidence or [], actor)
        connection.execute(
            "UPDATE semantic_scope_states SET interface_hash = ?,last_checked_at = ? WHERE snapshot_id = ? AND scope_type = 'architecture_plan' AND scope_key = 'plan'",
            (
                json.dumps(controls, sort_keys=True),
                datetime.now(UTC).isoformat(),
                plan["source_snapshot_id"],
            ),
        )
    return architecture_plan_status(database, repository_id)


def _milestone_progress(
    controls: Any, plan: Any, milestone: str, status: str, evidence: list[str], actor: str
) -> None:
    if milestone not in {item["key"] for item in plan["target"]["milestones"]}:
        raise ValueError("Milestone does not belong to the selected target")
    if status not in {"pending", "in_progress", "verified"}:
        raise ValueError("Milestone status must be pending, in_progress or verified")
    if status == "verified" and not any(item.strip() for item in evidence):
        raise ValueError("Verified milestones require reported verification evidence")
    selected = next(item for item in plan["target"]["milestones"] if item["key"] == milestone)
    controls.setdefault("progress", {}).setdefault(plan["selected_option"], {})[milestone] = {
        "status": status,
        "evidence": evidence,
        "reported_by": actor,
        "reported_at": datetime.now(UTC).isoformat(),
        "verified_against_snapshot_id": plan["snapshot_id"],
        "milestone_fingerprint": record_hash(selected),
    }


def _target_progress(controls: Any, selected_key: str, target: Any) -> dict[str, Any]:
    progress = controls.get("progress", {}).get(selected_key, {})
    milestones = {item["key"]: item for item in target["milestones"]} if target else {}
    return {
        key: (
            value
            if value.get("milestone_fingerprint") == record_hash(milestones[key])
            else {**value, "status": "needs_reverification"}
        )
        for key, value in progress.items()
        if key in milestones
    }


def architecture_diagrams(current: Any, target: Any) -> dict[str, Any]:
    before = {node["key"]: node for node in current.get("nodes", [])}
    after = {node["key"]: node for node in target.get("nodes", [])}
    changes = [
        {"key": key, "status": _node_change(key, before, after)}
        for key in sorted(before.keys() | after.keys())
    ]
    return {
        "current": current,
        "target": target,
        "changes": changes,
        "current_mermaid": mermaid_graph(current),
        "target_mermaid": mermaid_graph(target),
    }


def _node_change(key: str, before: Any, after: Any) -> str:
    if key not in before:
        return "added"
    if key not in after:
        return "retired"
    if set(before[key]["paths"]) != set(after[key]["paths"]):
        return "moved"
    return (
        "changed"
        if any(before[key][field] != after[key][field] for field in ("label", "responsibility"))
        else "retained"
    )


def mermaid_graph(graph: Any) -> str:
    nodes = graph.get("nodes", [])
    identifiers = {node["key"]: f"n{index}" for index, node in enumerate(nodes)}
    lines = ["flowchart LR"]
    for node in nodes:
        label = (
            str(node["label"])
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", " ")
        )
        lines.append(f'  {identifiers[node["key"]]}["{label}"]')
    for edge in graph.get("edges", []):
        lines.append(f"  {identifiers[edge['source']]} --> {identifiers[edge['target']]}")
    return "\n".join(lines) + "\n"


def planning_guidance(database: Any, repository_id: int) -> dict[str, Any]:
    plan = architecture_plan_status(database, repository_id)
    if not plan.get("value"):
        return {}
    target = plan["target"]
    next_step = next(
        (
            item
            for item in target["milestones"]
            if plan["progress"].get(item["key"], {}).get("status") != "verified"
        ),
        None,
    )
    result = {
        "state": plan["state"],
        "source_snapshot_id": plan["source_snapshot_id"],
        "target": target["title"][:180],
        "selection_source": plan["selection_source"],
        "next_milestone": (
            {key: next_step[key] for key in ("key", "title", "owners", "verification")}
            if next_step
            else None
        ),
        "details": {"tool": "ANAXIGRAPH_GUIDE", "arguments": {"intent": "plan", "details": True}},
    }
    return small_agent_response(result, limit=1200)
