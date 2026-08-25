"""Goal-specific architecture decisions assembled from current indexed evidence."""

from __future__ import annotations

from typing import Any

from anaxigraph.agent_decision_safety import consolidation_advice, dead_code_advice, verification
from anaxigraph.pattern_intelligence import PatternIntelligenceService

ARCHITECTURE_DECISION_VERSION = "architecture-decision-v1"

_REUSE_RECOMMENDATIONS = {"retain", "no_action", "improve_conformance"}
_OPPORTUNITY_RECOMMENDATIONS = {"introduce", "improve_conformance", "replace"}


def architecture_decision(
    database: Any,
    *,
    repository_id: int,
    repository_identity: str,
    goal: str,
    snapshot_id: int,
    primary_files: list[dict[str, Any]],
    interfaces: list[dict[str, Any]],
    tests: list[str],
    findings: list[dict[str, Any]],
    verification_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patterns = _pattern_items(database, repository_id, snapshot_id, primary_files)
    return build_architecture_decision(
        snapshot_id=snapshot_id,
        primary_files=primary_files,
        interfaces=interfaces,
        tests=tests,
        findings=findings,
        pattern_items=patterns,
        repository_identity=repository_identity,
        goal=goal,
        verification_baseline=verification_baseline,
    )


def build_architecture_decision(
    *,
    snapshot_id: int,
    primary_files: list[dict[str, Any]],
    interfaces: list[dict[str, Any]],
    tests: list[str],
    findings: list[dict[str, Any]],
    pattern_items: list[dict[str, Any]],
    repository_identity: str = "",
    goal: str = "",
    verification_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preferred = _preferred_file(primary_files)
    reviewed_patterns = _reviewed_patterns(pattern_items)
    semantic_current = sum(_semantic_current(item) for item in primary_files)
    return {
        "contract_version": ARCHITECTURE_DECISION_VERSION,
        "snapshot_id": snapshot_id,
        "status": _decision_status(primary_files, semantic_current, reviewed_patterns),
        "placement": _placement(preferred, interfaces, reviewed_patterns),
        "change_constraints": _change_constraints(primary_files),
        "patterns": {
            "status": "reviewed" if reviewed_patterns else "no_current_reviews",
            "total": len(reviewed_patterns),
            "items": reviewed_patterns,
        },
        "consolidation": consolidation_advice(primary_files, reviewed_patterns),
        "dead_code": dead_code_advice(primary_files, findings),
        "verification": verification(
            snapshot_id,
            primary_files,
            tests,
            findings,
            reviewed_patterns,
            repository_identity=repository_identity,
            goal=goal,
            previous_baseline=verification_baseline,
        ),
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
    return {
        "preferred_path": path,
        "guidance": _text(semantic.get("placement_guidance"), 1_500),
        "architecture_role": _text(semantic.get("architecture_role"), 800),
        "extension_points": _strings(semantic.get("extension_points"), 6),
        "public_contracts": _strings(semantic.get("public_contracts"), 6),
        "interfaces": [_compact_interface(item) for item in interfaces[:12]],
        "local_precedents": precedents[:8],
    }


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
            items.append(constraint)
    return {
        "status": "semantic" if items else "not_available",
        "items": items,
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
        "rationale": _text(item.get("rationale"), 800),
        "local_precedents": _strings(details.get("local_precedents"), 4),
        "risks": _strings(details.get("risks"), 3),
        "invariants": _strings(details.get("invariants"), 3),
        "review": _review_summary(item.get("review")),
        "provenance": _pattern_provenance(item.get("provenance")),
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


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item, 700) for item in value[:limit] if str(item or "").strip()]


def _dedupe(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(_text(value, 700) for value in values if str(value or "").strip()))


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]
