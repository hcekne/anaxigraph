"""Reconcile partition taxonomies through bounded representative clusters."""

from __future__ import annotations

import math
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
    module_by_path = {str(item.get("path") or ""): item for item in modules}
    clusters, assigned = _collect_clusters(chunks, module_by_path)
    _repair_missing_cluster(clusters, sorted(set(module_by_path) - assigned))
    return _materialize_clusters(_bounded_clusters(clusters, maximum), module_by_path)


def _collect_clusters(
    chunks: list[dict[str, Any]], module_by_path: dict[str, dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    clusters: dict[str, dict[str, Any]] = {}
    assigned: set[str] = set()
    for chunk_index, chunk in enumerate(chunks, start=1):
        taxonomy = chunk["taxonomy"]
        for area_index, area in enumerate(taxonomy.get("areas") or [], start=1):
            for subsystem_index, subsystem in enumerate(area.get("subsystems") or [], start=1):
                _collect_subsystem(
                    clusters,
                    assigned,
                    module_by_path,
                    area,
                    subsystem,
                    origin=f"partition {chunk_index}, area {area_index}, "
                    f"subsystem {subsystem_index}",
                )
    return clusters, assigned


def _collect_subsystem(
    clusters: dict[str, dict[str, Any]],
    assigned: set[str],
    module_by_path: dict[str, dict[str, Any]],
    area: dict[str, Any],
    subsystem: dict[str, Any],
    *,
    origin: str,
) -> None:
    members = {
        str(member.get("path") or ""): compact_member(member)
        for member in subsystem.get("members") or []
        if str(member.get("path") or "") in module_by_path
    }
    if not members:
        return
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
    cluster["origins"].append(origin)
    for path, member in members.items():
        existing = cluster["members"].get(path)
        if existing is None or member["confidence"] > existing["confidence"]:
            cluster["members"][path] = member
        assigned.add(path)


def _repair_missing_cluster(clusters: dict[str, dict[str, Any]], missing: list[str]) -> None:
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


def _bounded_clusters(clusters: dict[str, dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    ordered = sorted(
        clusters.values(),
        key=lambda item: (-len(item["members"]), item["subsystem"]["name"]),
    )
    if len(ordered) <= maximum:
        return ordered
    anchors = [_copy_cluster(cluster) for cluster in ordered[:maximum]]
    total_members = sum(len(cluster["members"]) for cluster in ordered)
    target_limit = max(
        max(len(cluster["members"]) for cluster in ordered),
        math.ceil(total_members / maximum) * 2,
    )
    for cluster in ordered[maximum:]:
        candidates = [
            anchor
            for anchor in anchors
            if len(anchor["members"]) + len(cluster["members"]) <= target_limit
        ] or anchors
        target = max(
            candidates,
            key=lambda anchor: (
                len(_cluster_terms(anchor) & _cluster_terms(cluster)),
                -len(anchor["members"]),
                str(anchor["subsystem"]["name"]),
            ),
        )
        _merge_cluster(target, cluster)
    return anchors


def _copy_cluster(cluster: dict[str, Any]) -> dict[str, Any]:
    return {
        **cluster,
        "area": dict(cluster["area"]),
        "subsystem": dict(cluster["subsystem"]),
        "members": dict(cluster["members"]),
        "origins": list(cluster["origins"]),
        "components": [{"area": dict(cluster["area"]), "subsystem": dict(cluster["subsystem"])}],
    }


def _merge_cluster(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["members"].update(source["members"])
    target["origins"].extend(source["origins"])
    target["components"].extend(
        source.get("components")
        or [{"area": dict(source["area"]), "subsystem": dict(source["subsystem"])}]
    )


def _cluster_terms(cluster: dict[str, Any]) -> set[str]:
    components = cluster.get("components") or [
        {"area": cluster["area"], "subsystem": cluster["subsystem"]}
    ]
    values = []
    for component in components:
        for node in (component["area"], component["subsystem"]):
            values.extend(
                str(node.get(field) or "")
                for field in ("key", "name", "description", "responsibility")
            )
    values.extend(str(path) for path in cluster["members"])
    return set(re.findall(r"[a-z0-9]{3,}", " ".join(values).lower()))


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
        confidence = _average_confidence(members)
        confidences.append(confidence)
        sample = _member_sample(members)
        area = cluster["area"]
        subsystem = cluster["subsystem"]
        representatives.append(
            _representative_module(
                representative, members, module_by_path, cluster, confidence, sample
            )
        )
        summaries.append(
            _cluster_summary(representative, area, subsystem, members, sample, cluster)
        )
        _add_representative_group(areas, representative, area, subsystem, confidence, sample)
    return {
        "modules": representatives,
        "expansion": expansion,
        "path_to_representative": path_to_representative,
        "summaries": summaries,
        "taxonomy": {
            "summary": "Partition-reviewed representative taxonomy.",
            "areas": list(areas.values()),
            "facets": [],
            "confidence": _average_confidence(confidences),
            "evidence": [item["path"] for item in representatives[:10]],
        },
    }


def _average_confidence(values: list[Any]) -> float:
    if not values:
        return 0.0
    return sum(
        float(value.get("confidence") or 0) if isinstance(value, dict) else float(value)
        for value in values
    ) / len(values)


def _member_sample(members: list[dict[str, Any]], limit: int = 5) -> list[str]:
    paths = sorted(str(item["path"]) for item in members)
    if len(paths) <= limit:
        return paths
    return [paths[index * (len(paths) - 1) // (limit - 1)] for index in range(limit)]


def _representative_module(
    representative: str,
    members: list[dict[str, Any]],
    module_by_path: dict[str, dict[str, Any]],
    cluster: dict[str, Any],
    confidence: float,
    sample: list[str],
) -> dict[str, Any]:
    subsystem = cluster["subsystem"]
    lines = sum(
        int(module_by_path.get(item["path"], {}).get("lines_of_code") or 0) for item in members
    )
    return {
        "path": representative,
        "artifact_type": "semantic_cluster",
        "language": "mixed",
        "lines_of_code": lines,
        "dossier": {
            "summary": subsystem["description"] or subsystem["responsibility"],
            "responsibilities": _component_values(cluster, "responsibility"),
            "public_contracts": [],
            "architecture_role": subsystem["name"],
            "domain_concepts": _component_values(cluster, "name"),
            "collaborators": [],
            "overlaps": [],
            "extension_points": [],
            "placement_guidance": "",
            "confidence": confidence,
            "member_count": len(members),
            "sample_members": sample,
        },
    }


def _cluster_summary(
    representative: str,
    area: dict[str, Any],
    subsystem: dict[str, Any],
    members: list[dict[str, Any]],
    sample: list[str],
    cluster: dict[str, Any],
) -> dict[str, Any]:
    return {
        "representative": representative,
        "area": area["name"],
        "subsystem": subsystem["name"],
        "responsibility": subsystem["responsibility"],
        "members": len(members),
        "sample_members": sample,
        "origins": cluster["origins"][:10],
        "component_groups": _component_values(cluster, "name"),
        "component_responsibilities": _component_values(cluster, "responsibility"),
    }


def _component_values(cluster: dict[str, Any], field: str) -> list[str]:
    components = cluster.get("components") or [
        {"area": cluster["area"], "subsystem": cluster["subsystem"]}
    ]
    values = [str(item["subsystem"].get(field) or "") for item in components]
    return list(dict.fromkeys(value for value in values if value))[:10]


def _add_representative_group(
    areas: dict[str, dict[str, Any]],
    representative: str,
    area: dict[str, Any],
    subsystem: dict[str, Any],
    confidence: float,
    sample: list[str],
) -> None:
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


def _slug(value: Any) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return result[:100] or "group"
