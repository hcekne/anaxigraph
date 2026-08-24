"""Shared payload compaction for bounded semantic requests."""

from __future__ import annotations

from typing import Any


def compact_dossier(value: dict[str, Any]) -> dict[str, Any]:
    """Keep cross-module reasoning useful without repeatedly nesting full prose."""

    return {
        "summary": str(value.get("summary") or "")[:2_000],
        "responsibilities": _compact_strings(value, "responsibilities"),
        "public_contracts": _compact_strings(value, "public_contracts"),
        "invariants": _compact_strings(value, "invariants"),
        "architecture_role": str(value.get("architecture_role") or "")[:1_000],
        "domain_concepts": _compact_strings(value, "domain_concepts"),
        "collaborators": _compact_strings(value, "collaborators"),
        "overlaps": _compact_strings(value, "overlaps"),
        "extension_points": _compact_strings(value, "extension_points"),
        "similar_modules": _compact_strings(value, "similar_modules"),
        "pattern_opportunities": _compact_patterns(value),
        "consolidation_assessment": _compact_consolidation(value),
        "dead_code_candidates": _compact_dead_code(value),
        "placement_guidance": str(value.get("placement_guidance") or "")[:2_000],
        "risks": _compact_strings(value, "risks"),
        "confidence": value.get("confidence"),
    }


def _compact_strings(value: dict[str, Any], key: str, limit: int = 12) -> list[str]:
    return [str(item)[:1_000] for item in (value.get(key) or [])[:limit]]


def _compact_patterns(value: dict[str, Any]) -> list[Any]:
    result = []
    for item in (value.get("pattern_opportunities") or [])[:8]:
        if isinstance(item, dict):
            result.append(
                {
                    "name": str(item.get("name") or "")[:300],
                    "scope": str(item.get("scope") or "")[:200],
                    "score": item.get("score"),
                    "confidence": item.get("confidence"),
                    "rationale": str(item.get("rationale") or "")[:1_000],
                    "evidence": [str(entry)[:500] for entry in (item.get("evidence") or [])[:4]],
                    "counter_evidence": [
                        str(entry)[:500] for entry in (item.get("counter_evidence") or [])[:4]
                    ],
                    "migration_cost": item.get("migration_cost"),
                }
            )
        else:
            result.append(str(item)[:1_000])
    return result


def _compact_dead_code(value: dict[str, Any]) -> list[Any]:
    result = []
    for item in (value.get("dead_code_candidates") or [])[:8]:
        if isinstance(item, dict):
            result.append(
                {
                    "path_or_symbol": str(item.get("path_or_symbol") or "")[:500],
                    "confidence": item.get("confidence"),
                    "rationale": str(item.get("rationale") or "")[:1_000],
                    "verification": str(item.get("verification") or "")[:1_000],
                }
            )
        else:
            result.append(str(item)[:1_000])
    return result


def _compact_consolidation(value: dict[str, Any]) -> Any:
    consolidation = value.get("consolidation_assessment")
    if not isinstance(consolidation, dict):
        return consolidation
    return {
        "recommendation": consolidation.get("recommendation"),
        "score": consolidation.get("score"),
        "rationale": str(consolidation.get("rationale") or "")[:1_000],
        "candidates": [str(item)[:500] for item in (consolidation.get("candidates") or [])[:12]],
    }
