"""Bound hosted taxonomy payloads into evidence-preserving partitions."""

from __future__ import annotations

import json
import math
from typing import Any

from anaxigraph.config import SemanticConfig

_MEMBER_TOKEN_ESTIMATE = 180


def request_base(request: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "candidate_taxonomy",
        "modules",
        "partial_taxonomies",
        "partition_reviews",
        "previous_taxonomy",
        "provisional_groups",
        "relationships",
    }
    return {key: value for key, value in request.items() if key not in excluded}


def needs_partition(request: dict[str, Any], semantic: SemanticConfig, memberships: int) -> bool:
    input_too_large = len(json.dumps(request, ensure_ascii=False, default=str)) > (
        semantic.max_source_chars
    )
    output_too_large = memberships * _MEMBER_TOKEN_ESTIMATE > semantic.max_output_tokens
    return input_too_large or output_too_large


def partition_limit(semantic: SemanticConfig) -> int:
    return max(2, semantic.max_output_tokens // _MEMBER_TOKEN_ESTIMATE)


def cluster_limit(request: dict[str, Any], semantic: SemanticConfig) -> int:
    configured = int((request.get("constraints") or {}).get("max_subsystems") or 30)
    return max(2, min(configured, partition_limit(semantic)))


def module_batches(
    modules: list[dict[str, Any]],
    max_chars: int,
    base: dict[str, Any],
    max_items: int,
) -> list[list[dict[str, Any]]]:
    overhead = len(json.dumps(base, ensure_ascii=False, default=str)) + 1_500
    budget = max(2_000, max_chars - overhead)
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for module in modules:
        module_size = len(json.dumps(module, ensure_ascii=False, default=str)) + 1
        if current and (size + module_size > budget or len(current) >= max_items):
            batches.append(current)
            current = []
            size = 0
        current.append(module)
        size += module_size
    if current:
        batches.append(current)
    return batches


def chunk_constraints(settings: dict[str, Any], total: int) -> dict[str, Any]:
    result = dict(settings)
    areas = int(result.get("max_areas") or 6)
    subsystems = int(result.get("max_subsystems") or 30)
    result["max_subsystems"] = max(1, math.ceil(subsystems / max(1, total)) + 1)
    result["max_areas"] = max(
        1, min(areas, result["max_subsystems"], math.ceil(areas / max(1, total)) + 1)
    )
    return result


def bounded_relationships(
    relationships: list[dict[str, Any]], paths: set[str], max_chars: int
) -> list[dict[str, Any]]:
    relevant = [
        edge for edge in relationships if edge.get("source") in paths or edge.get("target") in paths
    ]
    relevant.sort(
        key=lambda edge: (
            not (edge.get("source") in paths and edge.get("target") in paths),
            str(edge.get("source") or ""),
            str(edge.get("target") or ""),
            str(edge.get("type") or ""),
        )
    )
    limit = max(10, max_chars // 300)
    return relevant[:limit]


def filter_previous(value: Any, paths: set[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        **value,
        "memberships": [item for item in value.get("memberships", []) if item.get("path") in paths],
    }


def filter_taxonomy(value: dict[str, Any], paths: set[str]) -> dict[str, Any]:
    return {
        "summary": str(value.get("summary") or "")[:1_000],
        "areas": _filtered_areas(value.get("areas"), paths),
        "facets": _filtered_facets(value.get("facets"), paths),
        "confidence": float(value.get("confidence") or 0),
        "evidence": short_strings(value.get("evidence"), 20, 300),
    }


def _filtered_areas(value: Any, paths: set[str]) -> list[dict[str, Any]]:
    areas = []
    for area in value or []:
        subsystems = _filtered_subsystems(area.get("subsystems"), paths)
        if subsystems:
            areas.append({**compact_node(area), "subsystems": subsystems})
    return areas


def _filtered_subsystems(value: Any, paths: set[str]) -> list[dict[str, Any]]:
    subsystems = []
    for subsystem in value or []:
        members = [
            compact_member(member)
            for member in subsystem.get("members") or []
            if member.get("path") in paths
        ]
        if members:
            subsystems.append({**compact_node(subsystem), "members": members})
    return subsystems


def _filtered_facets(value: Any, paths: set[str]) -> list[dict[str, Any]]:
    facets = []
    for item in value or []:
        members = [path for path in item.get("members") or [] if path in paths]
        if not members:
            continue
        facets.append(
            {
                "name": str(item.get("name") or "")[:250],
                "description": str(item.get("description") or "")[:500],
                "members": members,
                "evidence": short_strings(item.get("evidence"), 10, 300),
            }
        )
    return facets


def compact_node(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(value.get("key") or value.get("name") or "group")[:120],
        "name": str(value.get("name") or value.get("key") or "Group")[:250],
        "description": str(value.get("description") or "")[:500],
        "responsibility": str(value.get("responsibility") or "")[:500],
        "confidence": float(value.get("confidence") or 0),
        "rationale": str(value.get("rationale") or "")[:500],
        "evidence": short_strings(value.get("evidence"), 10, 300),
        "counter_evidence": short_strings(value.get("counter_evidence"), 10, 300),
    }


def compact_member(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(value.get("path") or ""),
        "confidence": float(value.get("confidence") or 0),
        "rationale": str(value.get("rationale") or "")[:500],
        "evidence": short_strings(value.get("evidence"), 10, 300),
        "alternatives": short_strings(value.get("alternatives"), 10, 250),
    }


def short_strings(value: Any, limit: int, characters: int) -> list[str]:
    return [str(item)[:characters] for item in (value or [])[:limit]]
