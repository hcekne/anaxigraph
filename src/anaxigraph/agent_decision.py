"""Goal-specific architecture decisions assembled from current indexed evidence."""

from __future__ import annotations

from typing import Any

from anaxigraph.agent_decision_handoff_language import (
    _bounded_strings as _strings,
)
from anaxigraph.agent_decision_handoff_language import (
    constraint_item_explanation,
    constraints_explanation,
    decision_explanation,
    placement_explanation,
)
from anaxigraph.agent_decision_safety import consolidation_advice, dead_code_advice, verification
from anaxigraph.agent_decomposition import decomposition_advice
from anaxigraph.agent_task_path import task_path
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.trend_service import scoped_change_coupling

ARCHITECTURE_DECISION_VERSION = "architecture-decision-v1"

_REUSE_RECOMMENDATIONS = {"retain", "no_action", "improve_conformance"}
_OPPORTUNITY_RECOMMENDATIONS = {"introduce", "improve_conformance", "replace"}


def architecture_decision(
    database: Any,
    *,
    repository_id: int,
    goal: str,
    snapshot_id: int,
    primary_files: list[dict[str, Any]],
    interfaces: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    hierarchy: list[dict[str, Any]],
    tests: list[str],
    findings: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    patterns = _pattern_items(database, repository_id, snapshot_id, primary_files)
    coupling = scoped_change_coupling(
        database,
        repository_id,
        snapshot_id,
        [str(item.get("path") or "") for item in primary_files],
    )
    return build_architecture_decision(
        snapshot_id=snapshot_id,
        primary_files=primary_files,
        interfaces=interfaces,
        symbols=symbols,
        hierarchy=hierarchy,
        tests=tests,
        findings=findings,
        rules=rules,
        pattern_items=patterns,
        goal=goal,
        change_coupling=coupling,
    )


def build_architecture_decision(
    *,
    snapshot_id: int,
    primary_files: list[dict[str, Any]],
    interfaces: list[dict[str, Any]],
    tests: list[str],
    findings: list[dict[str, Any]],
    pattern_items: list[dict[str, Any]],
    rules: list[dict[str, Any]] | None = None,
    goal: str = "",
    symbols: list[dict[str, Any]] | None = None,
    hierarchy: list[dict[str, Any]] | None = None,
    change_coupling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preferred = _preferred_file(primary_files)
    reviewed_patterns = _reviewed_patterns(pattern_items)
    semantic_current = sum(_semantic_current(item) for item in primary_files)
    state = _decision_state(primary_files, semantic_current, reviewed_patterns)
    route = task_path(goal, preferred, primary_files, symbols or [], tests, hierarchy or [])
    return {
        "contract_version": ARCHITECTURE_DECISION_VERSION,
        "snapshot_id": snapshot_id,
        **state,
        "task_path": route,
        "placement": _placement(preferred, interfaces, reviewed_patterns),
        "change_constraints": _change_constraints(primary_files),
        "patterns": _pattern_packet(reviewed_patterns),
        **_structural_advice(
            primary_files,
            reviewed_patterns,
            change_coupling,
            symbols or [],
            tests,
            findings,
            rules or [],
        ),
        "dead_code": dead_code_advice(primary_files, findings),
        "verification": verification(primary_files, tests),
    }


def _decision_state(
    primary_files: list[dict[str, Any]],
    semantic_current: int,
    reviewed_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    status = _decision_status(primary_files, semantic_current, reviewed_patterns)
    return {
        "status": status,
        "plain_language": _decision_language(
            status, primary_files, semantic_current, reviewed_patterns
        ),
    }


def _structural_advice(
    primary_files: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    change_coupling: dict[str, Any] | None,
    symbols: list[dict[str, Any]],
    tests: list[str],
    findings: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "history_evidence": {"change_coupling": change_coupling or _missing_change_coupling()},
        "consolidation": consolidation_advice(
            primary_files,
            patterns,
            change_coupling=change_coupling,
        ),
        "decomposition": decomposition_advice(
            primary_files,
            symbols,
            tests,
            findings,
            patterns,
            rules,
        ),
    }


def _missing_change_coupling() -> dict[str, str]:
    return {
        "status": "unavailable",
        "reason": "No current change-history comparison was supplied for this decision.",
    }


def _decision_language(
    status: str,
    primary_files: list[dict[str, Any]],
    semantic_current: int,
    reviewed_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    return decision_explanation(
        status,
        selected_modules=len(primary_files),
        semantic_modules=semantic_current,
        reviewed_patterns=len(reviewed_patterns),
    )


def _pattern_packet(reviewed_patterns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "reviewed" if reviewed_patterns else "no_current_reviews",
        "total": len(reviewed_patterns),
        "reading_guide": _pattern_reading_guide(),
        "items": reviewed_patterns,
    }


def _pattern_items(
    database: Any,
    repository_id: int,
    snapshot_id: int,
    primary_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    service = PatternIntelligenceService(database)
    targets = [f"module:{item['path']}" for item in primary_files[:8]]
    return service.query_targets(repository_id, snapshot_id, targets)


def _preferred_file(primary_files: list[dict[str, Any]]) -> dict[str, Any]:
    for item in primary_files:
        semantic = item.get("semantic") or {}
        if _semantic_current(item) and (
            semantic.get("placement_guidance") or semantic.get("extension_points")
        ):
            return item
    return primary_files[0] if primary_files else {}


def _placement(
    preferred: dict[str, Any],
    interfaces: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    semantic = preferred.get("semantic") or {}
    path = str(preferred.get("path") or "")
    precedents = _dedupe(
        [*(semantic.get("similar_modules") or [])]
        + [
            value
            for item in patterns
            if item["target"] == path
            for value in item.get("local_precedents") or []
        ]
    )
    result = {
        "preferred_path": path,
        "guidance": _text(semantic.get("placement_guidance"), 1_500),
        "architecture_role": _text(semantic.get("architecture_role"), 800),
        "extension_points": _strings(semantic.get("extension_points"), 6),
        "public_contracts": _strings(semantic.get("public_contracts"), 6),
        "interfaces": [_compact_interface(item) for item in interfaces[:12]],
        "local_precedents": precedents[:8],
    }
    result["plain_language"] = placement_explanation(result)
    return result


def _reviewed_patterns(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [reviewed for item in items if (reviewed := _reviewed_pattern(item))]
    return sorted(result, key=_pattern_order)[:8]


def _change_constraints(primary_files: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for item in primary_files[:8]:
        semantic = item.get("semantic") or {}
        constraint = {
            "path": str(item.get("path") or ""),
            "public_contracts": _strings(semantic.get("public_contracts"), 6),
            "invariants": _strings(semantic.get("invariants"), 6),
            "risks": _strings(semantic.get("risks"), 6),
        }
        if any(constraint[key] for key in ("public_contracts", "invariants", "risks")):
            constraint["plain_language"] = constraint_item_explanation(constraint)
            items.append(constraint)
    return {
        "status": "semantic" if items else "not_available",
        "items": items,
        "plain_language": constraints_explanation(items),
    }


def _reviewed_pattern(item: dict[str, Any]) -> dict[str, Any] | None:
    scores = _mapping(item.get("scores"))
    recommendation = str(item.get("recommendation") or "")
    presence = str(item.get("presence") or "")
    role = _pattern_role(presence, recommendation, scores)
    if not role:
        return None
    details = _mapping(item.get("details"))
    return {
        "role": role,
        "target": _nested_text(item, "target", "path"),
        "key": _nested_text(item, "pattern", "key"),
        "name": _nested_text(item, "pattern", "name"),
        "presence": presence,
        "recommendation": recommendation,
        "scores": _decision_scores(scores),
        "plain_language": _pattern_language(item.get("plain_language")),
        "rationale": _text(item.get("rationale"), 800),
        "local_precedents": _strings(details.get("local_precedents"), 4),
        "risks": _strings(details.get("risks"), 3),
        "invariants": _strings(details.get("invariants"), 3),
        "review": _review_summary(item.get("review")),
        "provenance": _pattern_provenance(item.get("provenance")),
    }


def _pattern_reading_guide() -> dict[str, Any]:
    return {
        "purpose": (
            "These are independently reviewed pattern evaluations for the coding goal. Reuse means "
            "the code already provides a useful local example; opportunity means a change may help."
        ),
        "ratings": {
            "suitability": "How well the pattern fits this code and repository.",
            "conformance": "How much of the pattern the code already follows.",
            "opportunity": "How much value a change may add after accounting for what exists.",
            "confidence": "How strongly the available evidence supports the evaluation.",
        },
        "numbers": (
            "Ratings run from 0 to 100. They are separate evidence summaries, not code-quality "
            "grades, and no one number is permission to refactor."
        ),
    }


def _pattern_language(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    if not source:
        return {
            "version": "missing",
            "conclusion": "This older pattern result has no complete plain-language explanation.",
            "what_to_do": "Query the current pattern service before acting on this result.",
        }
    return {
        "version": str(source.get("version") or ""),
        "conclusion": _text(source.get("conclusion"), 240),
        "what_anaxigraph_saw": _strings(source.get("what_anaxigraph_saw"), 2, 200),
        "why_it_may_matter": _text(source.get("why_it_may_matter"), 240),
        "what_to_do": _text(source.get("what_to_do"), 240),
        "reasons_not_to_change_the_code": _strings(
            source.get("reasons_not_to_change_the_code"), 1, 220
        ),
        "how_to_check": _strings(source.get("how_to_check"), 2, 220),
        "independent_review": _text(source.get("independent_review"), 240),
    }


def _pattern_role(presence: str, recommendation: str, scores: dict[str, Any]) -> str:
    if (
        presence in {"present", "partial"}
        and recommendation in _REUSE_RECOMMENDATIONS
        and int(scores.get("conformance") or 0) >= 50
    ):
        return "reuse"
    if recommendation in _OPPORTUNITY_RECOMMENDATIONS and int(scores.get("opportunity") or 0) >= 40:
        return "opportunity"
    return ""


def _pattern_order(item: dict[str, Any]) -> tuple[Any, ...]:
    score = "conformance" if item["role"] == "reuse" else "opportunity"
    return (item["role"] != "reuse", -item["scores"][score], item["target"], item["key"])


def _decision_status(
    files: list[dict[str, Any]], semantic_current: int, patterns: list[dict[str, Any]]
) -> str:
    if files and semantic_current == len(files) and patterns:
        return "semantic_and_reviewed"
    if files and semantic_current == len(files):
        return "semantic_current"
    if semantic_current:
        return "semantic_partial"
    return "deterministic_only"


def _semantic_current(item: dict[str, Any]) -> bool:
    return str((item.get("semantic") or {}).get("status") or "") in {
        "current",
        "intrinsic_current",
    }


def _compact_interface(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _text(item.get(key), 500)
        for key in ("path", "symbol_type", "name", "signature", "summary")
        if item.get(key)
    }


def _decision_scores(scores: dict[str, Any]) -> dict[str, int]:
    return {
        key: int(scores.get(key) or 0)
        for key in ("suitability", "conformance", "opportunity", "confidence")
    }


def _review_summary(value: Any) -> dict[str, Any]:
    review = _mapping(value)
    return {
        "verdict": str(review.get("verdict") or ""),
        "confidence": int(review.get("confidence") or 0),
    }


def _pattern_provenance(value: Any) -> dict[str, str]:
    provenance = _mapping(value)
    return {
        key: str(provenance.get(key) or "")
        for key in ("provider", "model", "executor_model", "prompt_version")
    }


def _nested_text(item: dict[str, Any], parent: str, key: str) -> str:
    return str(_mapping(item.get(parent)).get(key) or "")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dedupe(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(_text(value, 700) for value in values if str(value or "").strip()))


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]
