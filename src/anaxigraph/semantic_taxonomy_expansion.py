"""Expand representative taxonomy memberships back to original modules."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_taxonomy_partition import compact_member


def expand_taxonomy(
    value: dict[str, Any], expansion: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    return {
        "summary": str(value.get("summary") or "")[:4_000],
        "areas": _expanded_areas(value.get("areas"), expansion),
        "facets": _expanded_facets(value.get("facets"), expansion),
        "confidence": float(value.get("confidence") or 0),
        "evidence": _expand_strings(value.get("evidence"), expansion),
    }


def _expanded_areas(value: Any, expansion: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    areas = []
    for area in value or []:
        subsystems = [
            {
                **_expanded_node(subsystem, expansion),
                "members": _expanded_members(subsystem.get("members"), expansion),
            }
            for subsystem in area.get("subsystems") or []
        ]
        areas.append({**_expanded_node(area, expansion), "subsystems": subsystems})
    return areas


def _expanded_members(
    value: Any, expansion: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    members = []
    for representative_member in value or []:
        originals = expansion.get(str(representative_member.get("path") or ""))
        if originals is None:
            members.append(compact_member(representative_member))
            continue
        members.extend(_expanded_member(representative_member, original) for original in originals)
    return members


def _expanded_member(representative: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    rationale = " ".join(
        item
        for item in (
            str(representative.get("rationale") or ""),
            str(original.get("rationale") or ""),
        )
        if item
    )[:4_000]
    return {
        "path": original["path"],
        "confidence": min(
            float(representative.get("confidence") or 0),
            float(original.get("confidence") or 0),
        ),
        "rationale": rationale,
        "evidence": unique_strings(
            [*(original.get("evidence") or []), *(representative.get("evidence") or [])],
            limit=100,
        ),
        "alternatives": unique_strings(
            [
                *(original.get("alternatives") or []),
                *(representative.get("alternatives") or []),
            ],
            limit=100,
        ),
    }


def _expanded_facets(
    value: Any, expansion: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    facets = []
    for facet in value or []:
        facets.append(
            {
                "name": str(facet.get("name") or "")[:250],
                "description": str(facet.get("description") or "")[:2_000],
                "members": _expanded_facet_members(facet.get("members"), expansion),
                "evidence": _expand_strings(facet.get("evidence"), expansion),
            }
        )
    return facets


def _expanded_facet_members(value: Any, expansion: dict[str, list[dict[str, Any]]]) -> list[str]:
    members = []
    for path in value or []:
        key = str(path)
        if key in expansion:
            members.extend(item["path"] for item in expansion[key])
        else:
            members.append(key)
    return unique_strings(members, limit=10_000)


def _expanded_node(
    value: dict[str, Any], expansion: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    return {
        "key": str(value.get("key") or value.get("name") or "group")[:120],
        "name": str(value.get("name") or value.get("key") or "Group")[:250],
        "description": str(value.get("description") or "")[:2_000],
        "responsibility": str(value.get("responsibility") or "")[:2_000],
        "confidence": float(value.get("confidence") or 0),
        "rationale": str(value.get("rationale") or "")[:4_000],
        "evidence": _expand_strings(value.get("evidence"), expansion),
        "counter_evidence": _expand_strings(value.get("counter_evidence"), expansion),
    }


def membership_count(value: dict[str, Any]) -> int:
    return sum(
        len(subsystem.get("members") or [])
        for area in value.get("areas") or []
        for subsystem in area.get("subsystems") or []
    )


def _expand_strings(
    values: Any,
    expansion: dict[str, list[dict[str, Any]]],
) -> list[str]:
    result = []
    for value in values or []:
        original = expansion.get(str(value))
        if original:
            result.extend(item["path"] for item in original[:5])
        else:
            result.append(str(value))
    return unique_strings(result, limit=100)


def unique_strings(values: list[Any], *, limit: int) -> list[str]:
    return list(dict.fromkeys(str(value)[:2_000] for value in values if str(value)))[:limit]
