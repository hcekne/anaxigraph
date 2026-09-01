"""Actor-neutral guidance projected from the existing architecture evidence packet."""

from __future__ import annotations

import hashlib
import json
from typing import Any

ARCHITECTURE_GUIDANCE_VERSION = "architecture-guidance-v1"
GUIDANCE_INTENTS = frozenset({"build", "refactor"})


def guidance_projection(
    context: dict[str, Any],
    *,
    intent: str,
    focus: str,
    charter: dict[str, Any],
) -> dict[str, Any]:
    """Compose one stable recommendation for dashboard, CLI, REST, and MCP."""

    selected_intent = _intent(intent)
    recommendation = _recommendation(context, selected_intent)
    understanding = _understanding(context, selected_intent, focus, charter)
    impact = _impact(context)
    evidence = _evidence_links(context, charter)
    confidence = _confidence(context, charter)
    core = {
        "contract_version": ARCHITECTURE_GUIDANCE_VERSION,
        "intent": selected_intent,
        "focus": focus,
        "understanding": understanding,
        "recommendation": {**recommendation, "confidence": confidence},
        "impact_summary": impact,
        "evidence_links": evidence,
        "unknowns": _unknowns(context, charter),
        "caveats": _caveats(context, charter),
        "confidence": confidence,
    }
    return {"identity": _identity(context, core), **core}


def compact_guidance_projection(payload: dict[str, Any]) -> None:
    """Keep the decision usable when the configured response budget is unusually small."""

    understanding = payload.get("understanding") or {}
    payload["understanding"] = {
        key: understanding.get(key)
        for key in ("summary", "charter")
        if understanding.get(key) not in (None, "", [])
    }
    recommendation = payload.get("recommendation") or {}
    payload["recommendation"] = {
        key: recommendation.get(key)
        for key in (
            "action",
            "summary",
            "starting_point",
            "migration_cost",
            "confidence",
        )
        if recommendation.get(key) not in (None, "", [])
    }
    impact = payload.get("impact_summary") or {}
    payload["impact_summary"] = {
        **{key: impact.get(key) for key in ("target", "bounded")},
        "direct_caller_count": len(impact.get("direct_callers") or []),
        "dependency_count": len(impact.get("dependencies") or []),
        "focused_test_count": len(impact.get("focused_tests") or []),
    }
    payload["evidence_links"] = list(payload.get("evidence_links") or [])[:3]
    payload["unknowns"] = list(payload.get("unknowns") or [])[:1]
    payload["caveats"] = list(payload.get("caveats") or [])[:1]


def _intent(value: str) -> str:
    selected = str(value or "build").strip().lower()
    if selected not in GUIDANCE_INTENTS:
        allowed = ", ".join(sorted(GUIDANCE_INTENTS))
        raise ValueError(f"Guidance intent must be one of: {allowed}")
    return selected


def _understanding(
    context: dict[str, Any], intent: str, focus: str, charter: dict[str, Any]
) -> dict[str, Any]:
    goal = str(context.get("goal") or "")
    primary = context.get("primary_files") or []
    purpose = _statement(charter.get("purpose"))
    verb = "add or change" if intent == "build" else "improve"
    summary = (
        f"You want to {verb} '{goal}'. AnaxiGraph found {len(primary)} likely starting "
        f"{'file' if len(primary) == 1 else 'files'} in the current saved map."
    )
    return {
        "goal": goal,
        "intent": intent,
        "focus": focus,
        "summary": summary,
        "system_purpose": purpose,
        "charter": {
            key: charter.get(key) for key in ("identity", "state", "complete", "snapshot_id")
        },
    }


def _recommendation(context: dict[str, Any], intent: str) -> dict[str, Any]:
    decision = context.get("architecture_decision") or {}
    placement = decision.get("placement") or {}
    start = str(placement.get("preferred_path") or "")
    action, evidence = _action(decision, context, intent, start)
    why = _why(decision, evidence)
    return {
        "action": action,
        "summary": _recommendation_summary(action, start),
        "starting_point": start or None,
        "why": why,
        "tradeoffs": _tradeoffs(decision),
        "reasons_not_to_change": _reasons_not_to_change(decision, action),
        "migration_cost": _migration_cost(context, action),
    }


def _action(
    decision: dict[str, Any], context: dict[str, Any], intent: str, start: str
) -> tuple[str, str]:
    patterns = (decision.get("patterns") or {}).get("items") or []
    if intent == "build":
        return _build_action(patterns, start)
    return _refactor_action(decision, context, patterns)


def _build_action(patterns: list[dict[str, Any]], start: str) -> tuple[str, str]:
    reusable = _first_matching(patterns, "role", {"reuse"})
    if reusable:
        return "reuse", _conclusion(reusable)
    return ("extend", "") if start else ("create", "")


def _refactor_action(
    decision: dict[str, Any], context: dict[str, Any], patterns: list[dict[str, Any]]
) -> tuple[str, str]:
    finding = _first_matching(
        context.get("known_findings") or [], "finding_type", {"architecture_violation"}
    )
    if finding:
        return "move", str((finding.get("plain_language") or {}).get("what") or "")
    decomposition = (decision.get("decomposition") or {}).get("items") or []
    candidate = _first_matching(decomposition, "status", {"candidate"})
    if candidate:
        return "split", _conclusion(candidate)
    consolidation = decision.get("consolidation") or []
    candidate = _first_matching(consolidation, "status", {"candidate"})
    if candidate:
        action = "split" if candidate.get("recommendation") == "split" else "consolidate"
        return action, _conclusion(candidate)
    dead = (decision.get("dead_code") or {}).get("items") or []
    candidate = _first_matching(
        dead, "status", {"corroborated_candidate", "deterministic_candidate"}
    )
    if candidate:
        return "delete", _conclusion(candidate)
    opportunity = _first_matching(patterns, "role", {"opportunity"})
    if opportunity:
        return "refactor", _conclusion(opportunity)
    return "retain", "Current evidence does not support a specific structural change."


def _first_matching(
    items: list[dict[str, Any]], key: str, values: set[str]
) -> dict[str, Any] | None:
    return next((item for item in items if item.get(key) in values), None)


def _conclusion(item: dict[str, Any]) -> str:
    return str((item.get("plain_language") or {}).get("conclusion") or "")


def _recommendation_summary(action: str, start: str) -> str:
    target = start or "the selected responsibility"
    templates = {
        "reuse": f"Reuse the existing design around {target} before creating another path.",
        "extend": f"Extend {target} through its recorded boundary.",
        "create": "Create the smallest new component only after confirming no current owner fits.",
        "move": f"Test moving the misplaced responsibility around {target} into its intended area.",
        "split": f"Test a bounded responsibility split beginning at {target}.",
        "consolidate": f"Test consolidating overlapping responsibility around {target}.",
        "delete": f"Treat code around {target} as a deletion candidate, not approved dead code.",
        "refactor": f"Test the reviewed pattern improvement around {target}.",
        "retain": f"Keep {target} as it is until stronger evidence supports a change.",
    }
    return templates[action]


def _why(decision: dict[str, Any], action_evidence: str) -> list[str]:
    placement = (decision.get("placement") or {}).get("plain_language") or {}
    route = (decision.get("task_path") or {}).get("plain_language") or {}
    return _strings(
        [action_evidence, placement.get("why"), route.get("conclusion")],
        limit=4,
    )


def _tradeoffs(decision: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for item in (decision.get("patterns") or {}).get("items") or []:
        values.extend(item.get("risks") or [])
    for item in (decision.get("change_constraints") or {}).get("items") or []:
        values.extend(item.get("risks") or [])
    return _strings(values, limit=5)


def _reasons_not_to_change(decision: dict[str, Any], action: str) -> list[str]:
    values: list[Any] = []
    for item in (decision.get("patterns") or {}).get("items") or []:
        values.extend(
            (item.get("plain_language") or {}).get("reasons_not_to_change_the_code") or []
        )
    for item in decision.get("consolidation") or []:
        values.extend(item.get("counter_evidence") or [])
    if action == "retain":
        values.insert(0, "No current evidence supports a coherent structural change.")
    return _strings(values, limit=5)


def _impact(context: dict[str, Any]) -> dict[str, Any]:
    module = ((context.get("architecture_decision") or {}).get("task_path") or {}).get(
        "module"
    ) or {}
    return {
        "target": module.get("path"),
        "direct_callers": list(module.get("callers_to_check") or [])[:12],
        "dependencies": list(module.get("dependencies_to_check") or [])[:12],
        "transitive_candidates": [
            item.get("path") for item in (context.get("related_files") or [])[:12]
        ],
        "focused_tests": list(context.get("tests") or [])[:12],
        "protected_paths": [
            item.get("path") for item in (context.get("protected_files") or [])[:12]
        ],
        "bounded": True,
    }


def _evidence_links(context: dict[str, Any], charter: dict[str, Any]) -> list[dict[str, Any]]:
    values = [
        {"kind": "snapshot", "reference": str(context.get("snapshot_id") or "")},
        {"kind": "charter", "reference": str(charter.get("identity") or "")},
    ]
    values.extend(
        {"kind": "module", "reference": str(item.get("path") or "")}
        for item in (context.get("primary_files") or [])[:8]
    )
    values.extend(
        {"kind": "finding", "reference": str(item.get("id") or "")}
        for item in (context.get("known_findings") or [])[:4]
    )
    return [item for item in values if item["reference"]]


def _confidence(context: dict[str, Any], charter: dict[str, Any]) -> dict[str, Any]:
    status = str((context.get("architecture_decision") or {}).get("status") or "")
    score = {
        "semantic_and_reviewed": 0.9,
        "semantic_current": 0.8,
        "semantic_partial": 0.6,
        "deterministic_only": 0.4,
    }.get(status, 0.35)
    if charter.get("state") != "current":
        score = min(score, 0.6)
    return {
        "score": score,
        "label": "high" if score >= 0.8 else "medium" if score >= 0.55 else "limited",
        "basis": status or "insufficient evidence",
    }


def _unknowns(context: dict[str, Any], charter: dict[str, Any]) -> list[str]:
    values = [
        item.get("question") if isinstance(item, dict) else item
        for item in charter.get("unknowns") or []
    ]
    if (context.get("architecture_decision") or {}).get("status") == "deterministic_only":
        values.append("The selected files do not have current AI descriptions.")
    return _strings(values, limit=5)


def _caveats(context: dict[str, Any], charter: dict[str, Any]) -> list[str]:
    values = list(charter.get("caveats") or [])
    if (context.get("map_status") or {}).get("state") != "current":
        values.append("The saved code map does not match the current checkout.")
    values.append("Runtime-only wiring may be absent from the extracted code links.")
    return _strings(values, limit=5)


def _migration_cost(context: dict[str, Any], action: str) -> str:
    if action in {"retain", "reuse"}:
        return "low"
    if context.get("risk") == "high" or len(context.get("related_files") or []) > 8:
        return "high"
    return "medium" if len(context.get("related_files") or []) > 3 else "low"


def _identity(context: dict[str, Any], core: dict[str, Any]) -> str:
    source = {
        "repository_id": context.get("repository_id"),
        "snapshot_id": context.get("snapshot_id"),
        "goal": context.get("goal"),
        "core": core,
        "decision": context.get("architecture_decision"),
    }
    digest = hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:20]
    return f"{ARCHITECTURE_GUIDANCE_VERSION}:{context.get('repository_id')}:{digest}"


def _statement(value: Any) -> str:
    return (
        str(value.get("presented_statement") or value.get("statement") or "")
        if isinstance(value, dict)
        else str(value or "")
    )


def _strings(values: list[Any], *, limit: int) -> list[str]:
    return list(
        dict.fromkeys(str(value).strip()[:1_000] for value in values if str(value or "").strip())
    )[:limit]
