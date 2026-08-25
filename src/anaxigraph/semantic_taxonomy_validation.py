"""Deterministic validation, repair, and stable identity for semantic taxonomies."""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from anaxigraph.semantic_taxonomy_identity import stable_taxonomy_nodes

_INTERNAL_GROUP_REFERENCE = re.compile(r"\b(?:cluster|group)-\d+\b", re.IGNORECASE)


def normalize_taxonomy(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    value: dict[str, Any],
    eligible_paths: list[str],
    settings: dict[str, Any],
    locked_memberships: dict[str, str],
) -> dict[str, Any]:
    known_paths = set(eligible_paths)
    artifacts = _artifact_ids(connection, repository_id, known_paths)
    nodes, candidates, issues = _flatten(value, known_paths)
    _plain_language_issues(nodes, candidates, issues)
    assignments = _primary_assignments(candidates, issues)
    _apply_locks(nodes, assignments, locked_memberships, known_paths, issues)
    _assign_missing(nodes, assignments, known_paths, issues)
    _prune_empty(nodes, assignments)
    _bound_areas(nodes, assignments, int(settings.get("max_areas") or 6), issues)
    _bound_subsystems(nodes, assignments, int(settings.get("max_subsystems") or 30), issues)
    _prune_empty(nodes, assignments)
    stable_nodes, events = stable_taxonomy_nodes(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        nodes=nodes,
        assignments=assignments,
        stability_bias=float(settings.get("stability_bias") or 0.8),
    )
    memberships = _memberships(assignments, stable_nodes, artifacts, locked_memberships)
    _group_shape_issues(stable_nodes, memberships, issues)
    repairs = [issue for issue in issues if issue["kind"].startswith("repaired_")]
    return {
        "summary": str(value.get("summary") or "")[:4_000],
        "confidence": max(0.0, min(1.0, float(value.get("confidence") or 0))),
        "facets": _facets(value.get("facets"), known_paths),
        "nodes": stable_nodes,
        "memberships": memberships,
        "events": events,
        "validation": {
            "status": "adjusted" if repairs else "valid",
            "eligible_modules": len(known_paths),
            "assigned_modules": len(memberships),
            "areas": sum(node["level"] == "area" for node in stable_nodes),
            "subsystems": sum(node["level"] == "subsystem" for node in stable_nodes),
            "repairs": len(repairs),
            "issues": issues,
        },
    }


def _flatten(
    value: dict[str, Any], known_paths: set[str]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    memberships: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    used: set[str] = set()
    for area_index, area in enumerate(value.get("areas") or []):
        area_key = _unique_key(_slug(area.get("key") or area.get("name") or "area"), used)
        nodes[area_key] = _node(area, area_key, "area", None, area_index)
        for subsystem_index, subsystem in enumerate(area.get("subsystems") or []):
            proposed = _slug(subsystem.get("key") or subsystem.get("name") or "subsystem")
            key = _unique_key(proposed, used)
            nodes[key] = _node(subsystem, key, "subsystem", area_key, subsystem_index)
            for member in subsystem.get("members") or []:
                path = str(member.get("path") or "")
                if path not in known_paths:
                    issues.append(_issue("ignored_unknown_module", path, "warning"))
                    continue
                memberships.append({**member, "path": path, "node_key": key})
    return nodes, memberships, issues


def _node(
    value: dict[str, Any], key: str, level: str, parent: str | None, order: int
) -> dict[str, Any]:
    return {
        "temp_key": key,
        "name": str(value.get("name") or key.replace("-", " ").title())[:250],
        "level": level,
        "parent_temp_key": parent,
        "description": str(value.get("description") or "")[:2_000],
        "responsibility": str(value.get("responsibility") or "")[:2_000],
        "confidence": max(0.0, min(1.0, float(value.get("confidence") or 0))),
        "rationale": str(value.get("rationale") or "")[:4_000],
        "evidence": _strings(value.get("evidence")),
        "counter_evidence": _strings(value.get("counter_evidence")),
        "display_order": order,
        "locked": False,
    }


def _plain_language_issues(
    nodes: dict[str, dict[str, Any]],
    memberships: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    for key, node in nodes.items():
        for field in ("name", "description", "responsibility", "rationale"):
            if _INTERNAL_GROUP_REFERENCE.search(str(node.get(field) or "")):
                issues.append(
                    _issue("unexplained_internal_group_reference", f"{key}.{field}", "warning")
                )
    for membership in memberships:
        if _INTERNAL_GROUP_REFERENCE.search(str(membership.get("rationale") or "")):
            issues.append(
                _issue(
                    "unexplained_internal_group_reference",
                    f"{membership['path']}.rationale",
                    "warning",
                )
            )


def _primary_assignments(
    candidates: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate["path"]].append(candidate)
    assignments = {}
    for path, values in grouped.items():
        values.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
        assignments[path] = values[0]
        if len(values) > 1:
            issues.append(_issue("repaired_duplicate_membership", path, "warning"))
    return assignments


def _apply_locks(
    nodes: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    locks: dict[str, str],
    known_paths: set[str],
    issues: list[dict[str, Any]],
) -> None:
    for path, requested in locks.items():
        if path not in known_paths:
            continue
        target = next(
            (
                key
                for key, node in nodes.items()
                if node["level"] == "subsystem"
                and requested in {key, node["name"], _slug(node["name"])}
            ),
            None,
        )
        if target is None:
            parent = next((key for key, node in nodes.items() if node["level"] == "area"), None)
            if parent is None:
                parent = _unique_key("operator-hints", set(nodes))
                nodes[parent] = _fallback_node(parent, "Operator hints", "area", None)
            target = _unique_key(_slug(requested), set(nodes))
            nodes[target] = _fallback_node(target, requested, "subsystem", parent)
        nodes[target]["locked"] = True
        assignments[path] = {
            "path": path,
            "node_key": target,
            "confidence": 1.0,
            "rationale": "Membership locked by repository map configuration.",
            "evidence": [f"map.locked_memberships: {path}"],
            "alternatives": [],
        }
        issues.append(_issue("applied_locked_membership", path, "info"))


def _assign_missing(
    nodes: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    known_paths: set[str],
    issues: list[dict[str, Any]],
) -> None:
    missing = sorted(known_paths - set(assignments))
    if not missing:
        return
    parent = _unique_key("needs-classification", set(nodes))
    nodes[parent] = _fallback_node(parent, "Needs classification", "area", None)
    subsystem = _unique_key("unclassified-modules", set(nodes))
    nodes[subsystem] = _fallback_node(subsystem, "Unclassified modules", "subsystem", parent)
    for path in missing:
        assignments[path] = {
            "path": path,
            "node_key": subsystem,
            "confidence": 0.0,
            "rationale": (
                "The agent omitted this eligible module; deterministic repair keeps it visible "
                "for the next autonomous map revision."
            ),
            "evidence": [],
            "alternatives": [],
        }
        issues.append(_issue("repaired_missing_membership", path, "warning"))


def _prune_empty(nodes: dict[str, dict[str, Any]], assignments: dict[str, dict[str, Any]]) -> None:
    used_subsystems = {item["node_key"] for item in assignments.values()}
    for key in list(nodes):
        if nodes[key]["level"] == "subsystem" and key not in used_subsystems:
            del nodes[key]
    used_areas = {
        node["parent_temp_key"] for node in nodes.values() if node["level"] == "subsystem"
    }
    for key in list(nodes):
        if nodes[key]["level"] == "area" and key not in used_areas:
            del nodes[key]


def _bound_areas(
    nodes: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    maximum: int,
    issues: list[dict[str, Any]],
) -> None:
    areas = [key for key, node in nodes.items() if node["level"] == "area"]
    if len(areas) <= maximum:
        return
    counts = Counter(item["node_key"] for item in assignments.values())
    area_sizes = {
        area: sum(counts[key] for key, node in nodes.items() if node["parent_temp_key"] == area)
        for area in areas
    }
    keep_count = max(0, maximum - 1)
    kept = set(sorted(areas, key=lambda key: (-area_sizes[key], key))[:keep_count])
    overflow = _unique_key("other-responsibilities", set(nodes))
    nodes[overflow] = _fallback_node(overflow, "Other responsibilities", "area", None)
    for node in nodes.values():
        if node["level"] == "subsystem" and node["parent_temp_key"] not in kept:
            node["parent_temp_key"] = overflow
    for area in areas:
        if area not in kept:
            del nodes[area]
    issues.append(_issue("repaired_area_limit", str(len(areas)), "warning"))


def _bound_subsystems(
    nodes: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    maximum: int,
    issues: list[dict[str, Any]],
) -> None:
    subsystems = [key for key, node in nodes.items() if node["level"] == "subsystem"]
    if len(subsystems) <= maximum:
        return
    counts = Counter(item["node_key"] for item in assignments.values())
    locked = {key for key in subsystems if nodes[key]["locked"]}
    if len(locked) >= maximum:
        _bound_locked_subsystems(nodes, assignments, subsystems, locked, issues)
        return
    ordered = sorted(
        subsystems,
        key=lambda key: (not nodes[key]["locked"], -counts[key], key),
    )
    kept = set(locked)
    for key in ordered:
        if len(kept) >= maximum - 1:
            break
        kept.add(key)
    moved = set(subsystems) - kept
    _merge_subsystems(nodes, assignments, moved, nodes[ordered[0]]["parent_temp_key"])
    issues.append(_issue("repaired_subsystem_limit", str(len(subsystems)), "warning"))


def _bound_locked_subsystems(
    nodes: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    subsystems: list[str],
    locked: set[str],
    issues: list[dict[str, Any]],
) -> None:
    unlocked = set(subsystems) - locked
    if unlocked:
        parent = nodes[sorted(locked)[0]]["parent_temp_key"]
        _merge_subsystems(nodes, assignments, unlocked, parent)
        issues.append(
            _issue("repaired_subsystem_limit_with_locked_overflow", str(len(unlocked)), "warning")
        )
    issues.append(_issue("subsystem_limit_overridden_by_locks", str(len(locked)), "warning"))


def _merge_subsystems(
    nodes: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    moved: set[str],
    parent: str | None,
) -> None:
    overflow = _unique_key("other-modules", set(nodes))
    nodes[overflow] = _fallback_node(overflow, "Other modules", "subsystem", parent)
    for assignment in assignments.values():
        if assignment["node_key"] in moved:
            assignment["node_key"] = overflow
            assignment["confidence"] = min(float(assignment.get("confidence") or 0), 0.4)
    for subsystem in moved:
        del nodes[subsystem]


def _memberships(
    assignments: dict[str, dict[str, Any]],
    nodes: list[dict[str, Any]],
    artifacts: dict[str, int],
    locks: dict[str, str],
) -> list[dict[str, Any]]:
    stable = {node["temp_key"]: node["node_key"] for node in nodes}
    result = []
    for path, assignment in sorted(assignments.items()):
        if path not in artifacts:
            continue
        result.append(
            {
                "artifact_id": artifacts[path],
                "path": path,
                "node_key": stable[assignment["node_key"]],
                "confidence": max(0.0, min(1.0, float(assignment.get("confidence") or 0))),
                "rationale": str(assignment.get("rationale") or "")[:4_000],
                "evidence": _strings(assignment.get("evidence")),
                "alternatives": _strings(assignment.get("alternatives")),
                "locked": path in locks,
            }
        )
    return result


def _group_shape_issues(
    nodes: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    counts = Counter(item["node_key"] for item in memberships)
    total = max(1, len(memberships))
    for node in nodes:
        if node["level"] != "subsystem":
            continue
        count = counts[node["node_key"]]
        if count == 1:
            issues.append(_issue("tiny_subsystem", node["node_key"], "info"))
        if count / total > 0.5:
            issues.append(_issue("large_catchall_candidate", node["node_key"], "warning"))


def _facets(value: Any, known_paths: set[str]) -> list[dict[str, Any]]:
    result = []
    for item in value or []:
        result.append(
            {
                "name": str(item.get("name") or "")[:250],
                "description": str(item.get("description") or "")[:2_000],
                "members": [path for path in _strings(item.get("members")) if path in known_paths],
                "evidence": _strings(item.get("evidence")),
            }
        )
    return result[:100]


def _artifact_ids(
    connection: sqlite3.Connection, repository_id: int, paths: set[str]
) -> dict[str, int]:
    if not paths:
        return {}
    placeholders = ",".join("?" for _ in paths)
    rows = connection.execute(
        f"SELECT id, canonical_path FROM artifacts WHERE repository_id = ? AND canonical_path IN ({placeholders})",
        (repository_id, *sorted(paths)),
    ).fetchall()
    return {str(row["canonical_path"]): int(row["id"]) for row in rows}


def _fallback_node(key: str, name: str, level: str, parent: str | None) -> dict[str, Any]:
    return {
        "temp_key": key,
        "name": name[:250],
        "level": level,
        "parent_temp_key": parent,
        "description": "Deterministically retained so every module stays visible.",
        "responsibility": "Holds low-confidence or overflow semantic-map membership.",
        "confidence": 0.0,
        "rationale": "Created by deterministic taxonomy validation.",
        "evidence": [],
        "counter_evidence": [],
        "display_order": 10_000,
        "locked": False,
    }


def _issue(kind: str, scope: str, severity: str) -> dict[str, Any]:
    return {"kind": kind, "scope": scope, "severity": severity}


def _slug(value: Any) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return result[:120] or "unnamed"


def _unique_key(value: str, used: set[str]) -> str:
    if value not in used:
        used.add(value)
        return value
    index = 2
    while f"{value}-{index}" in used:
        index += 1
    result = f"{value}-{index}"
    used.add(result)
    return result


def _strings(value: Any) -> list[str]:
    return [str(item)[:2_000] for item in (value or [])[:100]] if isinstance(value, list) else []
