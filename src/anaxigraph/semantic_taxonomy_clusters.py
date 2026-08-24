"""Reconcile partition taxonomies through bounded representative clusters."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from anaxigraph.semantic_taxonomy_partition import compact_member, compact_node


def cluster_inventory(
    chunks: list[dict[str, Any]],
    modules: list[dict[str, Any]],
    *,
    maximum: int,
) -> dict[str, Any]:
    clusters: dict[str, dict[str, Any]] = {}
    module_by_path = {str(item.get("path") or ""): item for item in modules}
    assigned: set[str] = set()
    for chunk_index, chunk in enumerate(chunks, start=1):
        taxonomy = chunk["taxonomy"]
        for area_index, area in enumerate(taxonomy.get("areas") or [], start=1):
            for subsystem_index, subsystem in enumerate(area.get("subsystems") or [], start=1):
                members = {
                    str(member.get("path") or ""): compact_member(member)
                    for member in subsystem.get("members") or []
                    if str(member.get("path") or "") in module_by_path
                }
                if not members:
                    continue
                identity = (
                    f"{_slug(area.get('key') or area.get('name'))}/"
                    f"{_slug(subsystem.get('key') or subsystem.get('name'))}"
                )
                cluster = clusters.setdefault(
                    identity,
                    {
                        "area": compact_node(area),
                        "subsystem": compact_node(subsystem),
                        "members": {},
                        "origins": [],
                    },
                )
                cluster["origins"].append(
                    f"partition {chunk_index}, area {area_index}, subsystem {subsystem_index}"
                )
                for path, member in members.items():
                    existing = cluster["members"].get(path)
                    if existing is None or member["confidence"] > existing["confidence"]:
                        cluster["members"][path] = member
                    assigned.add(path)
    missing = sorted(set(module_by_path) - assigned)
    if missing:
        clusters["needs-classification/unassigned"] = {
            "area": _fallback_node("needs-classification", "Needs classification"),
            "subsystem": _fallback_node("unassigned", "Unassigned modules"),
            "members": {
                path: {
                    "path": path,
                    "confidence": 0.0,
                    "rationale": "A partition proposal omitted this module.",
                    "evidence": [],
                    "alternatives": [],
                }
                for path in missing
            },
            "origins": ["deterministic partition completeness repair"],
        }
    ordered = sorted(
        clusters.values(),
        key=lambda item: (-len(item["members"]), item["subsystem"]["name"]),
    )
    if len(ordered) > maximum:
        overflow = {
            "area": _fallback_node("other-responsibilities", "Other responsibilities"),
            "subsystem": _fallback_node("other-clusters", "Other reviewed clusters"),
            "members": {},
            "origins": [],
        }
        for cluster in ordered[maximum - 1 :]:
            overflow["members"].update(cluster["members"])
            overflow["origins"].extend(cluster["origins"])
        ordered = ordered[: maximum - 1] + [overflow]
    return _materialize_clusters(ordered, module_by_path)


def _materialize_clusters(
    clusters: list[dict[str, Any]], module_by_path: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    expansion: dict[str, list[dict[str, Any]]] = {}
    path_to_representative: dict[str, str] = {}
    representatives = []
    summaries = []
    areas: dict[str, dict[str, Any]] = {}
    confidences = []
    for index, cluster in enumerate(clusters, start=1):
        representative = f"@anaxigraph/cluster-{index}"
        members = list(cluster["members"].values())
        expansion[representative] = members
        for member in members:
            path_to_representative[member["path"]] = representative
        confidence = (
            sum(float(item.get("confidence") or 0) for item in members) / len(members)
            if members
            else 0.0
        )
        confidences.append(confidence)
        sample = [item["path"] for item in members[:5]]
        area = cluster["area"]
        subsystem = cluster["subsystem"]
        representatives.append(
            {
                "path": representative,
                "artifact_type": "semantic_cluster",
                "language": "mixed",
                "lines_of_code": sum(
                    int(module_by_path.get(item["path"], {}).get("lines_of_code") or 0)
                    for item in members
                ),
                "dossier": {
                    "summary": subsystem["description"] or subsystem["responsibility"],
                    "responsibilities": [subsystem["responsibility"]],
                    "public_contracts": [],
                    "architecture_role": subsystem["name"],
                    "domain_concepts": [],
                    "collaborators": [],
                    "overlaps": [],
                    "extension_points": [],
                    "placement_guidance": "",
                    "confidence": confidence,
                    "member_count": len(members),
                    "sample_members": sample,
                },
            }
        )
        summaries.append(
            {
                "representative": representative,
                "area": area["name"],
                "subsystem": subsystem["name"],
                "responsibility": subsystem["responsibility"],
                "members": len(members),
                "sample_members": sample,
                "origins": cluster["origins"][:10],
            }
        )
        area_identity = _slug(area["key"] or area["name"])
        area_value = areas.setdefault(
            area_identity,
            {**area, "key": area_identity, "subsystems": []},
        )
        subsystem_key = f"{area_identity}-{_slug(subsystem['key'] or subsystem['name'])}"
        area_value["subsystems"].append(
            {
                **subsystem,
                "key": subsystem_key,
                "members": [
                    {
                        "path": representative,
                        "confidence": confidence,
                        "rationale": "Represents a locally reviewed module cluster.",
                        "evidence": sample,
                        "alternatives": [],
                    }
                ],
            }
        )
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return {
        "modules": representatives,
        "expansion": expansion,
        "path_to_representative": path_to_representative,
        "summaries": summaries,
        "taxonomy": {
            "summary": "Partition-reviewed representative taxonomy.",
            "areas": list(areas.values()),
            "facets": [],
            "confidence": confidence,
            "evidence": [item["path"] for item in representatives[:10]],
        },
    }


def group_summaries(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for chunk in chunks:
        for area in chunk["taxonomy"].get("areas") or []:
            for subsystem in area.get("subsystems") or []:
                result.append(
                    {
                        "area_key": area.get("key"),
                        "area": area.get("name"),
                        "subsystem_key": subsystem.get("key"),
                        "subsystem": subsystem.get("name"),
                        "responsibility": subsystem.get("responsibility"),
                    }
                )
    return result


def representative_relationships(
    relationships: list[dict[str, Any]],
    mapping: dict[str, str],
    max_chars: int,
) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str, str]] = Counter()
    for edge in relationships:
        source = mapping.get(str(edge.get("source") or ""))
        target = mapping.get(str(edge.get("target") or ""))
        if source and target:
            counts[
                (
                    source,
                    target,
                    str(edge.get("type") or ""),
                    str(edge.get("resolution") or ""),
                )
            ] += 1
    result = [
        {
            "source": key[0],
            "target": key[1],
            "type": key[2],
            "resolution": key[3],
            "count": count,
        }
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return result[: max(10, max_chars // 250)]


def representative_previous(value: Any, mapping: dict[str, str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    confidences: dict[tuple[str, str], list[float]] = defaultdict(list)
    for membership in value.get("memberships") or []:
        representative = mapping.get(str(membership.get("path") or ""))
        node_key = str(membership.get("node_key") or "")
        if representative and node_key:
            votes[representative][node_key] += 1
            confidences[(representative, node_key)].append(float(membership.get("confidence") or 0))
    memberships = []
    for representative, choices in sorted(votes.items()):
        node_key, _ = choices.most_common(1)[0]
        values = confidences[(representative, node_key)]
        memberships.append(
            {
                "path": representative,
                "node_key": node_key,
                "confidence": sum(values) / len(values),
            }
        )
    return {**value, "memberships": memberships}


def representative_locks(locks: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    result = {}
    for path, target in sorted(locks.items()):
        representative = mapping.get(str(path))
        if representative:
            result.setdefault(representative, str(target))
    return result


def expand_taxonomy(
    value: dict[str, Any], expansion: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    areas = []
    for area in value.get("areas") or []:
        subsystems = []
        for subsystem in area.get("subsystems") or []:
            members = []
            for representative_member in subsystem.get("members") or []:
                representative = str(representative_member.get("path") or "")
                originals = expansion.get(representative)
                if originals is None:
                    members.append(compact_member(representative_member))
                    continue
                for original in originals:
                    members.append(
                        {
                            "path": original["path"],
                            "confidence": min(
                                float(representative_member.get("confidence") or 0),
                                float(original.get("confidence") or 0),
                            ),
                            "rationale": " ".join(
                                item
                                for item in (
                                    str(representative_member.get("rationale") or ""),
                                    str(original.get("rationale") or ""),
                                )
                                if item
                            )[:4_000],
                            "evidence": unique_strings(
                                [
                                    *(original.get("evidence") or []),
                                    *(representative_member.get("evidence") or []),
                                ],
                                limit=100,
                            ),
                            "alternatives": unique_strings(
                                [
                                    *(original.get("alternatives") or []),
                                    *(representative_member.get("alternatives") or []),
                                ],
                                limit=100,
                            ),
                        }
                    )
            subsystems.append(
                {
                    **_expanded_node(subsystem, expansion),
                    "members": members,
                }
            )
        areas.append({**_expanded_node(area, expansion), "subsystems": subsystems})
    facets = []
    for facet in value.get("facets") or []:
        members = []
        for path in facet.get("members") or []:
            members.extend(item["path"] for item in expansion.get(str(path), []))
            if str(path) not in expansion:
                members.append(str(path))
        facets.append(
            {
                "name": str(facet.get("name") or "")[:250],
                "description": str(facet.get("description") or "")[:2_000],
                "members": unique_strings(members, limit=10_000),
                "evidence": _expand_strings(facet.get("evidence"), expansion),
            }
        )
    return {
        "summary": str(value.get("summary") or "")[:4_000],
        "areas": areas,
        "facets": facets,
        "confidence": float(value.get("confidence") or 0),
        "evidence": _expand_strings(value.get("evidence"), expansion),
    }


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


def _fallback_node(key: str, name: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "description": "Retained during bounded whole-repository reconciliation.",
        "responsibility": "Keep every reviewed module visible in the semantic map.",
        "confidence": 0.0,
        "rationale": "Created by deterministic taxonomy partition reconciliation.",
        "evidence": [],
        "counter_evidence": [],
    }


def unique_strings(values: list[Any], *, limit: int) -> list[str]:
    return list(dict.fromkeys(str(value)[:2_000] for value in values if str(value)))[:limit]


def _slug(value: Any) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return result[:100] or "group"
