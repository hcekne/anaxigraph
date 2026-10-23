"""Read retained scoped alternatives without interpreting them as current-code advice."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.semantic_fresh_eyes_functional import (
    FUNCTIONAL_PROTOCOL,
    functional_controls,
    functional_plan_options,
    is_functional_plan,
    scope_key,
    semantic_digest,
)
from anaxigraph.semantic_fresh_eyes_records import provenance


def functional_status(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    plan: Any,
    *,
    scope_id: str = "",
    details: bool = True,
    states: Any = None,
) -> dict[str, Any]:
    states = _states(connection, snapshot_id) if states is None else states
    hierarchy = _read(connection, states.get("functional:brief"))
    brief = hierarchy["value"] if hierarchy else None
    scopes = brief["scopes"] if brief else []
    if scope_id and scopes and scope_id not in {item["id"] for item in scopes}:
        raise ValueError("The selected functional scope is not part of this brief revision")
    selected = scope_id or next((item["id"] for item in scopes if item["level"] == "product"), "")
    reviews = [_scope_review(connection, states, item, selected, details) for item in scopes]
    expected = functional_plan_options(plan)[0]
    complete = sum(item["state"] == "current" for item in reviews)
    final = _read(connection, states.get("functional:review"))
    ready = _ready(plan, brief, final, complete)
    result = _identity(repository_id, snapshot_id, plan, ready, states)
    result.update(
        functional_brief={**brief, "revision": semantic_digest(brief)} if brief else None,
        scope_reviews=reviews,
        selected_scope_id=selected,
        counts=_counts(scopes, reviews, complete, expected),
        review_goal=_recorded_goal(connection, hierarchy),
    )
    result.update(_results(connection, states, final, ready, details, plan))
    return result


def _ready(plan: Any, brief: Any, final: Any, complete: int) -> bool:
    return bool(
        plan["status"] == "current" and brief and final and complete == len(brief["scopes"])
    )


def _identity(repository_id, snapshot_id, plan, ready, states):
    generation = functional_plan_options(plan)[1]
    return {
        "contract_version": "functional-review-v2",
        "protocol_version": FUNCTIONAL_PROTOCOL,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "review_generation": generation,
        "identity": f"{FUNCTIONAL_PROTOCOL}:{repository_id}:{snapshot_id}:generation-{generation}",
        "state": "current" if ready else _pending_state(states),
        "ready": ready,
    }


def _counts(scopes, reviews, complete, expected):
    return {
        "total_scopes": len(scopes),
        "completed_scopes": complete,
        "expected_alternatives": len(scopes) * expected,
        "retained_alternatives": sum(item["alternative_count"] for item in reviews),
    }


def _results(connection, states, final, ready, details, plan):
    return {
        "stages": _stages(connection, states, plan),
        "proposals": [],
        "recommendations": [],
        "comparison": None,
        "adjudication": None,
        "strategy": final["value"] if final and details else None,
        "isolation": {
            "status": "unverified",
            "reason": "External executor context is not attested",
        },
        "caveats": [
            "Alternative designs are proposals, not observed code or verified improvements."
        ],
        "next_action": "Compare alternatives in Architecture Planning."
        if ready
        else "Continue the functional review; saved scopes and alternatives are reused.",
    }


def requested_functional_status(connection, repository_id, snapshot_id, plan, **options):
    if not is_functional_plan(plan):
        return None
    return functional_status(connection, repository_id, snapshot_id, plan, **options)


def functional_generation(
    connection: Any,
    repository_id: int,
    bundle: Any,
    generations: Any,
    *,
    scope_id: str = "",
    details: bool = True,
) -> dict[str, Any]:
    states = {
        item["key"]: {
            "context_document_id": item["document_id"],
            "status": "current" if item["document_id"] else item["job_status"],
            "reason": "Saved functional review from an earlier generation",
        }
        for item in bundle["stages"]
    }
    proposals = [key for key in states if ":proposal:" in key]
    count = len({key.rsplit(":", 1)[1] for key in proposals}) or 3
    plan = {
        "interface_hash": f"functional-v2|{count}:{bundle['generation']}",
        "status": "superseded",
        "context_fingerprint": str(bundle["review_document_id"]),
    }
    result = functional_status(
        connection,
        repository_id,
        bundle["snapshot_id"],
        plan,
        states=states,
        scope_id=scope_id,
        details=details,
    )
    result.update(state=bundle["state"], ready=False, generations=generations)
    apply_bundle_status(result, bundle)
    result["caveats"].append("Recorded historical functional alternatives; no new work is queued.")
    return result


def apply_bundle_status(result: Any, bundle: Any) -> None:
    result["telemetry"] = bundle["telemetry"] if bundle else {"stage_count": 0}
    result["diversity"] = bundle["diversity"] if bundle else {}
    if bundle is None:
        return
    telemetry = {item["key"]: item for item in bundle["telemetry"]["stages"]}
    stages = {item["key"]: item for item in result["stages"]}
    result["stages"] = [
        {**stages[item["key"]], "telemetry": telemetry.get(item["key"])}
        for item in bundle["stages"]
        if item["key"] in stages
    ]


def _scope_review(
    connection: Any, states: Any, scope: Any, selected: str, details: bool
) -> dict[str, Any]:
    prefix = scope_key(scope["id"], "proposal") + ":"
    proposals = [
        _read(connection, row) for key, row in sorted(states.items()) if key.startswith(prefix)
    ]
    alternatives = [
        _alternative(item, details and scope["id"] == selected) for item in proposals if item
    ]
    comparison = _read(connection, states.get(scope_key(scope["id"], "comparison")))
    return {
        "scope_id": scope["id"],
        "scope": scope,
        "state": "current" if comparison else "in_progress",
        "alternative_count": len(alternatives),
        "alternatives": alternatives,
        "comparison": comparison["value"]
        if comparison and details and scope["id"] == selected
        else None,
        "details_available": bool(comparison or alternatives),
    }


def _alternative(document: Any, details: bool) -> dict[str, Any]:
    value = document["value"]
    fields = {
        key: value[key]
        for key in (
            "scope_id",
            "brief_revision",
            "pros",
            "cons",
            "confidence",
            "isolation",
            "parent_constraints",
            "compatible_parent_alternative_ids",
        )
    }
    fields["design"] = value["design"] if details else {"summary": value["design"]["summary"]}
    return {
        "id": f"alternative:{document['input_hash']}",
        "provenance": provenance(document),
        **fields,
    }


def _states(connection: Any, snapshot_id: int) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT scope_key,status,reason,context_document_id FROM semantic_scope_states "
        "WHERE snapshot_id=? AND scope_type='fresh_eyes' AND scope_key LIKE 'functional:%'",
        (snapshot_id,),
    ).fetchall()
    return {row["scope_key"]: dict(row) for row in rows}


def _read(connection: Any, state: Any) -> dict[str, Any] | None:
    if not state or state.get("status") != "current" or not state.get("context_document_id"):
        return None
    row = connection.execute(
        "SELECT * FROM semantic_document_values WHERE id=?", (state["context_document_id"],)
    ).fetchone()
    return {**dict(row), "value": json.loads(row["value_json"])} if row else None


def _recorded_goal(connection: Any, hierarchy: Any) -> str:
    if hierarchy is None:
        return ""
    row = connection.execute(
        "SELECT metadata_json FROM semantic_jobs WHERE repository_id=? AND scope_type='fresh_eyes' "
        "AND scope_key='functional:brief' AND input_hash=? ORDER BY id DESC LIMIT 1",
        (hierarchy["repository_id"], hierarchy["input_hash"]),
    ).fetchone()
    return (
        str(json.loads(row["metadata_json"]).get("input_manifest", {}).get("functional_goal", ""))
        if row
        else ""
    )


def _pending_state(states: Any) -> str:
    if any(str(item["status"]).startswith("failed") for item in states.values()):
        return "failed"
    return "in_progress" if states else "waiting_for_understanding"


def _stages(connection: Any, states: Any, plan: Any) -> list[dict[str, Any]]:
    labels = {
        "functional:brief": "Prepare functional hierarchy",
        "functional:review": "Review functional alternatives",
    }
    return [
        {
            "key": key,
            "label": labels.get(
                key,
                "Compare alternatives"
                if key.endswith(":comparison")
                else f"Functional alternative {key[-1].upper()} for {key.split(':')[1]}",
            ),
            "state": item["status"],
            "reason": item["reason"],
            "document_id": item["context_document_id"],
            "required_executor": _required_executor(plan, key),
            "provenance": provenance(_read(connection, item)),
        }
        for key, item in sorted(states.items())
    ]


def _required_executor(plan: Any, key: str) -> str | None:
    if ":proposal:" not in key:
        return None
    parts = functional_controls(str(plan.get("interface_hash") or "")).split(":", 3)
    families = parts[2].split(",") if len(parts) > 2 else []
    index = ord(key[-1]) - ord("a")
    family = families[index] if 0 <= index < len(families) else "any"
    return None if family == "any" else family
