"""Assess concrete maintenance tasks using evidence available in the repository."""

from __future__ import annotations

import re
from typing import Any

AGENT_REVIEW_POLICY = (
    "Judge a concrete maintenance task, not compliance with human-oriented design rules. "
    "Agent performance depends on supplied context: distinguish missing context from a code "
    "defect, and name missing evidence before proposing code changes. Keep purpose, caller "
    "obligations, and critical details together. When existing code is supplied, compare retaining "
    "it, improving context, and the smallest code change. Justify each added field, layer, or "
    "tool with an actual consumer or evidenced failure; avoid speculative abstractions and catalog completion. "
    "Existing result fields are not quotas for findings. Agent benefit remains a hypothesis "
    "until correct task outcomes are measured in fresh sessions with comparable context and resources."
)

UNDERSTANDABILITY_VERSION = "code-understandability-v1"
UNDERSTANDABILITY_POLICY = {
    "version": UNDERSTANDABILITY_VERSION,
    "objective": (
        "Help a competent newcomer locate behavior, understand its contracts, and make a correct "
        "change using the repository itself, without AnaxiGraph explanations. Prefer explicit "
        "domain language, cohesive responsibilities, discoverable entry points, and executable "
        "constraints while preserving behavior and operational requirements."
    ),
    "assessment": (
        "Assess up to three representative maintenance tasks. Use stable task keys and preserve "
        "the task wording when reassessing the same task. Identify where necessary knowledge is "
        "expressed and cite specific supplied paths or symbols. For an obstructed task, record "
        "the obstacle, smallest useful change, expected reader benefit, migration cost, contrary "
        "evidence, and a concrete correctness check. Clear tasks need evidence too. Missing or "
        "selected evidence means unknown; an empty task list means unassessed."
    ),
    "scope": (
        "In an intrinsic pass, assess only knowledge visible in the supplied file; leave changes "
        "requiring other files for the context pass. Keep domain complexity distinct from "
        "avoidable difficulty. Descriptions from earlier passes are interpretations, not proof "
        "that a newcomer can discover the same knowledge. Never invent source witnesses."
    ),
    "tradeoffs": (
        "Name the maintenance task each recommendation makes easier and the additional concepts "
        "or indirection it introduces. Smaller files, fewer lines, fewer documents, and more "
        "abstractions do not establish improvement. Retain cohesive code and justified complexity."
    ),
    "documentation": (
        "Keep concise domain glossaries linked to owning types or modules, decision rationale, "
        "operating constraints, and navigation to entry points and tests. Assess whether fragile "
        "calling conventions or hidden invariants can be expressed in names, interfaces, types, "
        "or behavioral tests. Documentation volume alone never justifies deletion or refactoring."
    ),
    "verification": (
        "These assessments are inferred hypotheses. Verify improvements with representative "
        "maintenance tasks in fresh contexts using source, tests, glossary, decisions, and thin "
        "navigation docs without generated architecture explanations. Prioritize correctness; "
        "compare effort only under comparable resources and repeated trials."
    ),
}


def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_TEXT = {"type": "string", "maxLength": 1_000}
_STRINGS = {"type": "array", "items": _TEXT, "maxItems": 6}
_TASK = _object(
    key={"type": "string", "minLength": 1, "maxLength": 100},
    task={**_TEXT, "minLength": 1},
    status={"type": "string", "enum": ["clear", "obstructed", "unknown"]},
    knowledge_sources={
        "type": "array",
        "items": {
            "type": "string",
            "enum": [
                "names",
                "boundaries",
                "interfaces",
                "types",
                "tests",
                "glossary",
                "decisions",
                "navigation",
                "distributed_behavior",
                "external_explanation",
            ],
        },
        "maxItems": 10,
    },
    evidence=_STRINGS,
    obstacle=_TEXT,
    smallest_change=_TEXT,
    expected_benefit=_TEXT,
    migration_cost={"type": "string", "enum": ["low", "medium", "high", "unknown"]},
    counter_evidence=_STRINGS,
    verification=_TEXT,
    confidence={"type": "number", "minimum": 0, "maximum": 1},
    caller_obligations={
        "type": "array",
        "items": _TEXT,
        "maxItems": 6,
        "description": (
            "What every caller must already know or guarantee because this interface does not "
            "enforce it: an ordering rule, a precondition, a resource the caller must release, "
            "or a detail the caller must repeat. Obligations a caller cannot discover from the "
            "interface are the cost this task pays; an empty list means none were found, which "
            "is not the same as none existing."
        ),
    },
)
# Optional: assessments saved before this field remain valid and are not re-requested.
_TASK["required"] = [name for name in _TASK["required"] if name != "caller_obligations"]
UNDERSTANDABILITY_SCHEMA = _object(
    contract_version={"type": "string", "enum": [UNDERSTANDABILITY_VERSION]},
    tasks={"type": "array", "items": _TASK, "maxItems": 3},
)


def assessment_tasks(semantic: dict[str, Any]) -> list[dict[str, Any]]:
    """Withhold stale or older assessments without treating absence as clarity."""
    assessment = semantic.get("understandability") or {}
    if semantic.get("status") != "current":
        return []
    if assessment.get("contract_version") != UNDERSTANDABILITY_VERSION:
        return []
    return list(assessment.get("tasks") or [])[:3]


def actionable_task(task: dict[str, Any]) -> bool:
    return (
        task.get("status") == "obstructed"
        and float(task.get("confidence") or 0) >= 0.7
        and task.get("migration_cost") in {"low", "medium"}
        and all(
            task.get(key)
            for key in (
                "evidence",
                "obstacle",
                "smallest_change",
                "expected_benefit",
                "counter_evidence",
                "verification",
            )
        )
    )


def understandability_advice(files: list[dict[str, Any]], goal: str = "") -> dict[str, Any]:
    items = [
        {
            **task,
            "path": item["path"],
            "actionable": actionable_task(task),
            "callers_to_check": list(item.get("incoming_paths") or [])[:12],
            "dependencies_to_check": list(item.get("outgoing_paths") or [])[:12],
        }
        for item in files
        for task in assessment_tasks(item.get("semantic") or {})
    ]
    terms = set(re.findall(r"[a-z][a-z0-9_]{3,}", goal.lower()))
    items.sort(key=lambda item: _task_order(item, terms))
    return {
        "policy_version": UNDERSTANDABILITY_VERSION,
        "status": "assessed" if any(item["status"] != "unknown" for item in items) else "unknown",
        "items": items[:6],
        "omitted": max(0, len(items) - 6),
        "basis": "Inferred maintenance-task assessments; reader performance has not been measured.",
    }


def _task_order(task: dict[str, Any], terms: set[str]) -> tuple:
    words = set(re.findall(r"[a-z][a-z0-9_]{3,}", task["task"].lower()))
    return (
        not task["actionable"],
        -len(terms & words),
        {"low": 0, "medium": 1, "high": 2, "unknown": 3}[task["migration_cost"]],
        -float(task["confidence"]),
        task["path"],
        task["key"],
    )


def compact_understandability(value: dict[str, Any] | None) -> dict[str, Any]:
    """Retain one task with its supporting and contrary evidence in a small response."""
    value = value or {}
    tasks = value.get("items", value.get("tasks")) or []
    compact = []
    for task in tasks[:1]:
        compact.append(
            {
                key: item[:160]
                if isinstance(item, str)
                else [str(entry)[:160] for entry in item[:2]]
                if isinstance(item, list)
                else item
                for key, item in task.items()
            }
        )
    field = "items" if "items" in value else "tasks"
    return {
        **{key: item for key, item in value.items() if key not in {"items", "tasks"}},
        field: compact,
        "omitted": len(tasks) - len(compact) + int(value.get("omitted") or 0),
    }
