"""Semantic duplication, pattern, and possible-unused-code reassessment inputs."""

from __future__ import annotations

from typing import Any

from anaxigraph.understandability import actionable_task, assessment_tasks


def semantic_effect_specs(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for change in evidence.get("module_changes") or []:
        result.extend(_understandability_specs(change))
        after = change.get("after") or {}
        semantic = after.get("semantic") or {}
        path = str(change.get("path") or "")
        consolidation = semantic.get("consolidation_assessment")
        if isinstance(consolidation, dict) and consolidation.get("recommendation") in {
            "merge",
            "split",
        }:
            result.append(_consolidation_spec(path, consolidation))
        for candidate in semantic.get("dead_code_candidates") or []:
            if isinstance(candidate, dict):
                result.append(_dead_code_spec(path, candidate))
    return result


def _understandability_specs(change: dict[str, Any]) -> list[dict[str, Any]]:
    before = (change.get("before") or {}).get("semantic") or {}
    after = (change.get("after") or {}).get("semantic") or {}
    previous = {item["key"]: item for item in assessment_tasks(before)}
    result = []
    for task in assessment_tasks(after):
        old = previous.get(task["key"])
        comparable = _comparable_reader_task(old, task)
        if comparable and old["status"] != task["status"]:
            label = "improved" if task["status"] == "clear" else "worsened"
            result.append(_reader_effect(change["path"], task, label, old))
        elif comparable and task["status"] == "clear":
            result.append(_reader_effect(change["path"], task, "coherent_no_change", old))
        elif actionable_task(task):
            result.append(_reader_effect(change["path"], task, "opportunity"))
    return result


def _comparable_reader_task(before: dict[str, Any] | None, after: dict[str, Any]) -> bool:
    if not before or before["task"] != after["task"]:
        return False
    return (
        before["status"] != "unknown"
        and after["status"] != "unknown"
        and min(before["confidence"], after["confidence"]) >= 0.7
    )


def _reader_effect(
    path: str, task: dict[str, Any], classification: str, before: dict[str, Any] | None = None
) -> dict[str, Any]:
    retain = classification in {"improved", "coherent_no_change"}
    observation = f"AI assessment of '{task['task']}': {task['status']}."
    if before:
        observation += f" The previous assessment was {before['status']}."
    return {
        "category": "understandability",
        "classification": classification,
        "subject": f"{path}::{task['key']}",
        "observation": observation,
        "consequence": "Current evidence continues to support this task."
        if classification == "coherent_no_change"
        else task["expected_benefit"] or "This task may require less outside explanation.",
        "recommendation": "Retain the clearer code if task checks pass."
        if retain
        else task["smallest_change"],
        "confidence": min(task["confidence"], before["confidence"] if before else 1),
        "basis": "inferred maintenance-task assessments, not measured reader performance",
        "counter_evidence": task["counter_evidence"],
        "reasons_to_leave_alone": task["counter_evidence"]
        or ["Domain complexity and concise rationale can remain necessary."],
        "follow_up": task["verification"],
        "verification": (
            f"{task['verification']} Compare correctness on this task in fresh contexts using "
            "the repository and thin docs without AnaxiGraph explanations; repeat under the same resources."
        ),
        "evidence": [
            {"kind": "semantic_dossier", "reference": path, "detail": f"{side}: {item}"}
            for side, value in (("before", before or {}), ("after", task))
            for item in value.get("evidence") or []
        ],
    }


def reported_confidence(value: Any, *, scale: float = 1.0) -> float | None:
    """Return a confidence a source actually recorded, preserving zero and absence.

    A missing field and a reported zero mean different things to a reader. Callers
    must not substitute a midpoint for an unmeasured confidence, and must not pass a
    strength or opportunity score here: those answer a different question.
    """

    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value) / scale
    except (TypeError, ValueError):
        return None


def pattern_effect_spec(item: dict[str, Any]) -> dict[str, Any] | None:
    recommendation = str(item.get("recommendation") or "insufficient_evidence")
    if recommendation in {"no_action", "retain", "insufficient_evidence"}:
        return None
    target = item.get("target") or {}
    pattern = item.get("pattern") or {}
    details = item.get("details") or {}
    scores = item.get("scores") or {}
    name = pattern.get("name") or pattern.get("key")
    return {
        "category": "pattern_fit",
        "classification": "opportunity",
        "subject": str(target.get("path") or target.get("key") or "repository"),
        "observation": str(item.get("summary") or f"Reviewed {name} fit."),
        "consequence": str(
            item.get("rationale") or "A known pattern may make the responsibility clearer."
        ),
        "recommendation": (
            f"{recommendation.replace('_', ' ').capitalize()} {name} only through a bounded "
            "behavior-preserving step."
        ),
        "confidence": reported_confidence(scores.get("confidence"), scale=100),
        "basis": "independently reviewed pattern evaluation",
        "counter_evidence": reassessment_strings(details.get("counter_evidence"), 4),
        "reasons_to_leave_alone": reassessment_strings(details.get("counter_evidence"), 4)
        or ["A pattern adds cost when the problem signal is weak or already contained."],
        "follow_up": (
            "Inspect local precedents and verify the pattern solves a measured problem before "
            "introducing it."
        ),
        "verification": (
            "Run the pattern's focused invariants and compare findings and coupling after the "
            "next scan."
        ),
        "evidence": _pattern_evidence(pattern, details),
    }


def _consolidation_spec(path: str, value: dict[str, Any]) -> dict[str, Any]:
    recommendation = str(value.get("recommendation"))
    counter = reassessment_strings(value.get("counter_evidence"), 4)
    return {
        "category": "duplication",
        "classification": "opportunity",
        "subject": path,
        "observation": _consolidation_observation(value, recommendation),
        "consequence": (
            "Related responsibilities may be duplicated or divided at an awkward boundary."
        ),
        "recommendation": (
            f"Test a bounded {recommendation}; do not change both modules until contracts and "
            "behavior agree."
        ),
        "confidence": reported_confidence(value.get("confidence"), scale=100),
        "basis": (
            "current semantic consolidation assessment; it records a strength score, "
            "not a confidence"
        ),
        "counter_evidence": counter,
        "reasons_to_leave_alone": counter
        or ["Distinct invariants can justify similar-looking code."],
        "follow_up": (
            "Compare responsibilities, callers, public contracts, and repeated co-change before "
            "editing."
        ),
        "verification": (
            "Run focused tests for every candidate module and confirm no behavior was duplicated "
            "or lost."
        ),
        "evidence": [
            {"kind": "semantic_dossier", "reference": path, "detail": item}
            for item in reassessment_strings(value.get("evidence"), 5)
        ],
    }


def _consolidation_observation(value: dict[str, Any], recommendation: str) -> str:
    """Keep the consolidation strength score visible without presenting it as confidence."""

    stated = str(
        value.get("rationale") or f"The dossier sees a possible {recommendation} candidate."
    )
    score = value.get("score")
    if score is None:
        return stated
    return f"{stated} Consolidation strength score {int(score)} of 100."


def _dead_code_spec(path: str, value: dict[str, Any]) -> dict[str, Any]:
    subject = str(value.get("path_or_symbol") or path)
    counter = reassessment_strings(value.get("counter_evidence"), 4)
    return {
        "category": "possible_unused_code",
        "classification": "candidate",
        "subject": subject,
        "observation": str(
            value.get("reason")
            or value.get("rationale")
            or "The module dossier found no clear current use."
        ),
        "consequence": (
            "Removing it could simplify the system, but static absence is not proof of runtime "
            "absence."
        ),
        "recommendation": (
            "Treat this only as a deletion candidate until source, configuration, registration, "
            "and tests all agree."
        ),
        "confidence": reported_confidence(value.get("confidence")),
        "basis": "confidence recorded for this unused-code candidate",
        "counter_evidence": counter,
        "reasons_to_leave_alone": counter
        or ["Reflection, plugins, templates, and deployment configuration can hide use."],
        "follow_up": (
            f"Search runtime registration and focused tests for {subject} before deleting anything."
        ),
        "verification": (
            "Remove only in a separate bounded change, run focused and integration tests, then "
            "scan for unresolved references."
        ),
        "evidence": [{"kind": "semantic_dossier", "reference": path, "detail": subject}],
    }


def _pattern_evidence(pattern: dict[str, Any], details: dict[str, Any]) -> list[dict[str, Any]]:
    reference = str(pattern.get("key") or "")
    return [
        {"kind": "pattern", "reference": reference, "detail": value}
        for value in reassessment_strings(details.get("evidence"), 5)
    ]


def reassessment_strings(values: Any, limit: int) -> list[str]:
    """Bound a free-text list once for every reassessment projection."""

    if not isinstance(values, (list, tuple)):
        return []
    return [str(value)[:1_000] for value in values if str(value).strip()][:limit]
