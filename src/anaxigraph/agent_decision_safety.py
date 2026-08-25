"""Balanced consolidation, dead-code, and post-change evidence for agent decisions."""

from __future__ import annotations

from typing import Any

from anaxigraph.agent_decision_verification import (
    compare_verification_baselines,
    verification_baseline,
)

_CONSOLIDATION_PATTERNS = {
    "cohesive-module",
    "dependency-hub",
    "feature-envy",
    "god-module",
    "package-by-feature",
    "shotgun-surgery",
}


def consolidation_advice(
    primary_files: list[dict[str, Any]], patterns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = [_consolidation_item(item, patterns) for item in primary_files]
    return [item for item in result if item is not None][:6]


def _consolidation_item(
    item: dict[str, Any], patterns: list[dict[str, Any]]
) -> dict[str, Any] | None:
    assessment = (item.get("semantic") or {}).get("consolidation_assessment")
    if not isinstance(assessment, dict):
        return None
    recommendation = str(assessment.get("recommendation") or "insufficient_evidence")
    score = int(assessment.get("score") or 0)
    evidence = _strings(assessment.get("evidence"), 4)
    counter = _strings(assessment.get("counter_evidence"), 4)
    return {
        "path": str(item.get("path") or ""),
        "status": _consolidation_status(recommendation, score, evidence, counter),
        "recommendation": recommendation,
        "score": score,
        "rationale": _text(assessment.get("rationale"), 1_000),
        "candidates": _strings(assessment.get("candidates"), 5),
        "evidence": evidence,
        "counter_evidence": counter,
        "context": _consolidation_context(item),
        "reviewed_patterns": [
            value["key"]
            for value in patterns
            if value["target"] == item.get("path") and value["key"] in _CONSOLIDATION_PATTERNS
        ],
    }


def _consolidation_context(item: dict[str, Any]) -> dict[str, Any]:
    semantic = item.get("semantic") or {}
    return {
        "responsibilities": _strings(semantic.get("responsibilities"), 5),
        "public_contracts": _strings(semantic.get("public_contracts"), 5),
        "graph_neighborhood": {
            "fan_in": int(item.get("fan_in") or 0),
            "fan_out": int(item.get("fan_out") or 0),
        },
        "architecture_placement": {
            "group": item.get("declared_group") or item.get("inferred_group"),
            "role": _text(semantic.get("architecture_role"), 500),
        },
        "change_coupling": {
            "status": "unavailable",
            "reason": "No current temporal co-change projection is available.",
        },
    }


def _consolidation_status(
    recommendation: str, score: int, evidence: list[str], counter: list[str]
) -> str:
    if recommendation == "keep":
        return "keep_separate"
    if recommendation in {"merge", "split"} and score >= 65 and evidence and counter:
        return "candidate"
    return "review"


def dead_code_advice(
    primary_files: list[dict[str, Any]], findings: list[dict[str, Any]]
) -> dict[str, Any]:
    deterministic = {
        path: finding
        for finding in findings
        if finding.get("finding_type") == "possible_dead_code"
        for path in finding.get("affected_artifacts") or []
    }
    result, represented = _semantic_dead_code_items(primary_files, deterministic)
    result.extend(
        _deterministic_dead_code(path, finding)
        for path, finding in deterministic.items()
        if path not in represented
    )
    return {
        "safe_removal_count": 0,
        "candidate_count": len(result),
        "items": result[:8],
        "policy": "Removal remains suppressed until static reachability and dynamic-use checks agree.",
    }


def _semantic_dead_code_items(
    primary_files: list[dict[str, Any]], deterministic: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], set[str]]:
    result = []
    represented = set()
    for module in primary_files:
        path = str(module.get("path") or "")
        for candidate in (module.get("semantic") or {}).get("dead_code_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            finding = deterministic.get(path)
            corroborated = _finding_corroborates(path, candidate, finding)
            if corroborated:
                represented.add(path)
            result.append(_semantic_dead_code(path, candidate, finding if corroborated else None))
    return result, represented


def _finding_corroborates(
    module: str, candidate: dict[str, Any], finding: dict[str, Any] | None
) -> bool:
    locator = str(candidate.get("path_or_symbol") or "").removeprefix("module:")
    return finding is not None and locator == module


def verification(
    snapshot_id: int,
    primary_files: list[dict[str, Any]],
    tests: list[str],
    findings: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    *,
    repository_identity: str = "",
    goal: str = "",
    previous_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_baseline = verification_baseline(
        repository_identity=repository_identity,
        goal=goal,
        snapshot_id=snapshot_id,
        modules=primary_files,
        findings=findings,
        patterns=patterns,
    )
    result = {
        "focused_test_paths": tests[:20],
        "semantic_test_guidance": _semantic_test_guidance(primary_files),
        "rescan_argv": ["anaxigraph", "update", ".", "--json"],
        "post_change_baseline": current_baseline,
        "compare": [
            "resolved and ambiguous dependency edges",
            "active finding keys and blast radius",
            "reviewed pattern scores and critique verdicts",
            "module placement and semantic responsibility",
            "focused test outcomes",
        ],
    }
    if previous_baseline is not None:
        result["post_change_comparison"] = compare_verification_baselines(
            previous_baseline, current_baseline
        )
    return result


def _semantic_test_guidance(primary_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(item.get("path") or ""),
            "guidance": _strings((item.get("semantic") or {}).get("testing_guidance"), 5),
        }
        for item in primary_files[:8]
        if (item.get("semantic") or {}).get("testing_guidance")
    ]


def _semantic_dead_code(
    module: str, candidate: dict[str, Any], finding: dict[str, Any] | None
) -> dict[str, Any]:
    corroborated = finding is not None
    reasons = (
        [] if corroborated else ["No trusted deterministic reachability finding corroborates it."]
    )
    reasons.append(
        "Dynamic registration, reflection, configuration, and generated wiring remain caveats."
    )
    return {
        "module": module,
        "path_or_symbol": _text(candidate.get("path_or_symbol"), 500),
        "status": "corroborated_candidate" if corroborated else "suppressed",
        "safe_to_remove": False,
        "confidence": float(candidate.get("confidence") or 0),
        "rationale": _text(candidate.get("rationale"), 800),
        "evidence": _strings(candidate.get("reachability_evidence"), 4),
        "counter_evidence": _strings(candidate.get("counter_evidence"), 4),
        "suppression_reasons": reasons,
        "verification": _text(candidate.get("verification"), 800),
    }


def _deterministic_dead_code(path: str, finding: dict[str, Any]) -> dict[str, Any]:
    language = finding.get("plain_language") or {}
    return {
        "module": path,
        "path_or_symbol": path,
        "status": "deterministic_candidate",
        "safe_to_remove": False,
        "confidence": float(finding.get("confidence") or 0),
        "rationale": _text(
            language.get("why_it_matters") or finding.get("explanation") or finding.get("summary"),
            800,
        ),
        "evidence": _strings(language.get("facts") or finding.get("evidence"), 4),
        "counter_evidence": [],
        "suppression_reasons": [
            "Dynamic registration, reflection, configuration, and generated wiring remain caveats."
        ],
        "verification": _text(
            language.get("how_to_check") or finding.get("recommended_action"), 800
        ),
    }


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item, 700) for item in value[:limit] if str(item or "").strip()]


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]
