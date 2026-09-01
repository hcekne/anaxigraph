"""Semantic duplication, pattern, and possible-unused-code reassessment inputs."""

from __future__ import annotations

from typing import Any


def semantic_effect_specs(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for change in evidence.get("module_changes") or []:
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
                result.append(_dead_code_spec(path, candidate, semantic))
    return result


def pattern_effect_spec(item: dict[str, Any]) -> dict[str, Any] | None:
    recommendation = str(item.get("recommendation") or "insufficient_evidence")
    if recommendation in {"no_action", "retain", "insufficient_evidence"}:
        return None
    target = item.get("target") or {}
    pattern = item.get("pattern") or {}
    details = item.get("details") or {}
    score = float((item.get("scores") or {}).get("opportunity") or 0)
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
        "confidence": min(0.95, max(0.2, score / 100)),
        "basis": "independently reviewed pattern evaluation",
        "counter_evidence": _strings(details.get("counter_evidence"), 4),
        "reasons_to_leave_alone": _strings(details.get("counter_evidence"), 4)
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
    counter = _strings(value.get("counter_evidence"), 4)
    return {
        "category": "duplication",
        "classification": "opportunity",
        "subject": path,
        "observation": str(
            value.get("rationale") or f"The dossier sees a possible {recommendation} candidate."
        ),
        "consequence": (
            "Related responsibilities may be duplicated or divided at an awkward boundary."
        ),
        "recommendation": (
            f"Test a bounded {recommendation}; do not change both modules until contracts and "
            "behavior agree."
        ),
        "confidence": min(0.9, max(0.2, float(value.get("score") or 50) / 100)),
        "basis": "current semantic consolidation assessment",
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
            for item in _strings(value.get("evidence"), 5)
        ],
    }


def _dead_code_spec(path: str, value: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    subject = str(value.get("path_or_symbol") or path)
    counter = _strings(value.get("counter_evidence"), 4)
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
        "confidence": float(semantic.get("confidence") or 0.5),
        "basis": "current semantic dossier",
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
        for value in _strings(details.get("evidence"), 5)
    ]


def _strings(values: Any, limit: int) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value)[:1_000] for value in values if str(value).strip()][:limit]
