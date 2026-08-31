"""Hierarchies for each explicit responsibility-map layer."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.architecture_vocabulary import (
    CURRENT_MAP,
    DECLARED_MAP,
    MAP_LAYERS,
    PATH_MAP,
    RESPONSIBILITY_MAP,
)
from anaxigraph.persistence.semantic_taxonomy_read import (
    hierarchy_children,
    materialize_hierarchy,
    read_semantic_hierarchy,
    taxonomy_assignments,
)


def read_group_hierarchy(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    *,
    layer: str = CURRENT_MAP,
) -> list[dict[str, Any]]:
    if layer not in MAP_LAYERS:
        raise ValueError(f"Map layer must be one of: {', '.join(MAP_LAYERS)}")
    responsibility = read_semantic_hierarchy(connection, snapshot_id)
    if layer == RESPONSIBILITY_MAP:
        return responsibility
    metadata = _metadata(connection, repository_id, layer, responsibility)
    nodes = {
        name: _node(name, stat, metadata.get(name))
        for name, stat in _stats(connection, snapshot_id, layer).items()
    }
    _add_parents(nodes, metadata)
    children = hierarchy_children(nodes)
    roots = [name for name, node in nodes.items() if node["parent"] not in nodes]
    return sorted(
        (materialize_hierarchy(name, nodes, children) for name in roots),
        key=lambda item: (-int(item["lines_of_code"]), item["name"]),
    )


def _stats(
    connection: sqlite3.Connection, snapshot_id: int, layer: str
) -> dict[str, dict[str, Any]]:
    assignments = taxonomy_assignments(connection, snapshot_id) if layer == CURRENT_MAP else {}
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"files": 0, "lines_of_code": 0, "source": None}
    )
    rows = connection.execute(
        "SELECT artifact_id, declared_group, inferred_group, lines_of_code "
        "FROM projected_file_versions"
    ).fetchall()
    for row in rows:
        name, source = _selected_group(dict(row), layer, assignments)
        stat = grouped[name]
        stat["files"] += 1
        stat["lines_of_code"] += int(row["lines_of_code"] or 0)
        stat["source"] = source if stat["source"] in {None, source} else "mixed"
    return grouped


def _selected_group(
    row: dict[str, Any], layer: str, assignments: dict[int, dict[str, Any]]
) -> tuple[str, str]:
    declared = row.get("declared_group")
    path_group = str(row.get("inferred_group") or "ungrouped")
    if layer == DECLARED_MAP:
        return (str(declared), DECLARED_MAP) if declared else ("unconfigured", "missing")
    if layer == PATH_MAP:
        return path_group, PATH_MAP
    assignment = assignments.get(int(row["artifact_id"]))
    if declared:
        return str(declared), DECLARED_MAP
    if assignment:
        return str(assignment["subsystem"]), RESPONSIBILITY_MAP
    return path_group, PATH_MAP


def _metadata(
    connection: sqlite3.Connection,
    repository_id: int,
    layer: str,
    responsibility: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    clause = {
        DECLARED_MAP: "AND source = 'declared'",
        PATH_MAP: "AND source = 'inferred'",
        CURRENT_MAP: "",
    }[layer]
    rows = [
        {
            **dict(row),
            "label": _label(str(row["name"])),
            "source": DECLARED_MAP if row["source"] == "declared" else PATH_MAP,
        }
        for row in connection.execute(
            f"""SELECT name, level, parent_name, source, description FROM groups
                WHERE repository_id = ? {clause}
                ORDER BY CASE source WHEN 'declared' THEN 0 ELSE 1 END, name""",
            (repository_id,),
        ).fetchall()
    ]
    if layer == CURRENT_MAP:
        rows.extend(_responsibility_nodes(responsibility))
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        result.setdefault(str(row["name"]), row)
    return result


def _responsibility_nodes(hierarchy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in hierarchy:
        result.append(
            {
                **{key: value for key, value in item.items() if key != "children"},
                "parent_name": item.get("parent"),
                "source": RESPONSIBILITY_MAP,
            }
        )
        result.extend(_responsibility_nodes(item.get("children") or []))
    return result


def _node(name: str, stat: dict[str, Any], metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    source = str(stat["source"])
    node = {
        "key": name,
        "name": name,
        "label": metadata.get("label") or _label(name),
        "level": metadata.get("level") or "subsystem",
        "parent": metadata.get("parent_name"),
        "source": source,
        "description": metadata.get("description") or "",
        "fallback_reason": (
            "No declared map rule places these files."
            if source == "missing"
            else "Some files use deterministic path placement because richer evidence is absent."
            if source in {PATH_MAP, "mixed"}
            else None
        ),
        "direct_files": int(stat["files"]),
        "direct_lines_of_code": int(stat["lines_of_code"]),
    }
    for key in ("responsibility", "confidence", "rationale", "evidence", "plain_language"):
        if key in metadata:
            node[key] = metadata[key]
    return node


def _add_parents(nodes: dict[str, dict[str, Any]], metadata: dict[str, dict[str, Any]]) -> None:
    for node in list(nodes.values()):
        name = node["parent"]
        if not name or name in nodes:
            continue
        item = metadata.get(name) or {}
        nodes[name] = {
            "key": name,
            "name": name,
            "label": item.get("label") or _label(name),
            "level": item.get("level") or "area",
            "parent": item.get("parent_name"),
            "source": item.get("source") or "derived",
            "description": item.get("description") or f"Top-level {_label(name)} area.",
            "fallback_reason": None,
            "direct_files": 0,
            "direct_lines_of_code": 0,
        }


def _label(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").title()
