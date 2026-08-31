"""Architecture group hierarchy over the active canonical snapshot projection."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.semantic_taxonomy_read import read_semantic_hierarchy


def read_group_hierarchy(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    *,
    layer: str = "effective",
) -> list[dict[str, Any]]:
    if layer not in {"effective", "semantic", "policy", "inferred"}:
        raise ValueError("Map layer must be effective, semantic, policy, or inferred")
    if layer in {"effective", "semantic"}:
        semantic = read_semantic_hierarchy(connection, snapshot_id)
        if semantic or layer == "semantic":
            return semantic
    expression = {
        "policy": "COALESCE(declared_group, 'unconfigured')",
        "inferred": "COALESCE(inferred_group, 'ungrouped')",
        "effective": "COALESCE(declared_group, inferred_group, 'ungrouped')",
    }[layer]
    stat_rows = connection.execute(
        f"""
        SELECT {expression} AS name,
               COUNT(*) AS files,
               COALESCE(SUM(lines_of_code), 0) AS lines_of_code,
               SUM(CASE WHEN declared_group IS NOT NULL THEN 1 ELSE 0 END) AS declared_files
        FROM projected_file_versions GROUP BY name
        """
    ).fetchall()
    source_filter = "AND source = 'inferred'" if layer == "inferred" else ""
    metadata_rows = connection.execute(
        f"""
        SELECT name, level, parent_name, source, description
        FROM groups WHERE repository_id = ? {source_filter}
        ORDER BY CASE source WHEN 'declared' THEN 0 ELSE 1 END, name
        """,
        (repository_id,),
    ).fetchall()
    nodes = _group_nodes(stat_rows, metadata_rows)
    children = _children(nodes)
    _mark_parent_areas(nodes, children)
    roots = [
        name
        for name, node in nodes.items()
        if not node["parent"] or node["parent"] not in nodes or node["parent"] == name
    ]
    materialized = [_materialize(name, nodes, children) for name in roots]
    return sorted(
        (item for item in materialized if int(item["files"]) > 0),
        key=lambda item: (-int(item["lines_of_code"]), item["name"]),
    )


def _group_nodes(
    stat_rows: list[sqlite3.Row],
    metadata_rows: list[sqlite3.Row],
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for row in metadata_rows:
        metadata.setdefault(str(row["name"]), dict(row))
    nodes = {str(row["name"]): _stat_node(row) for row in stat_rows}
    for name, item in metadata.items():
        if name not in nodes and item["source"] != "declared":
            continue
        node = nodes.setdefault(name, _empty_node(name, item))
        node.update(
            level=item["level"],
            parent=item["parent_name"],
            description=item["description"] or "",
        )
        if node["direct_files"] == 0:
            node["source"] = item["source"]
    _add_virtual_parents(nodes)
    return nodes


def _stat_node(row: sqlite3.Row) -> dict[str, Any]:
    files = int(row["files"] or 0)
    declared = int(row["declared_files"] or 0)
    source = "declared" if declared == files else "inferred" if declared == 0 else "mixed"
    return {
        "name": str(row["name"]),
        "level": "subsystem",
        "parent": None,
        "source": source,
        "description": "",
        "direct_files": files,
        "direct_lines_of_code": int(row["lines_of_code"] or 0),
    }


def _empty_node(name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "level": metadata["level"],
        "parent": None,
        "source": metadata["source"],
        "description": "",
        "direct_files": 0,
        "direct_lines_of_code": 0,
    }


def _add_virtual_parents(nodes: dict[str, dict[str, Any]]) -> None:
    for node in list(nodes.values()):
        parent = node["parent"]
        if parent and parent not in nodes:
            nodes[parent] = {
                "name": parent,
                "level": "area",
                "parent": None,
                "source": "derived",
                "description": f"Top-level {parent.replace('-', ' ')} architecture area.",
                "direct_files": 0,
                "direct_lines_of_code": 0,
            }


def _children(nodes: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {name: [] for name in nodes}
    for name, node in nodes.items():
        parent = node["parent"]
        if parent and parent in nodes and parent != name:
            children[parent].append(name)
    return children


def _mark_parent_areas(
    nodes: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
) -> None:
    for name, child_names in children.items():
        node = nodes[name]
        if child_names and not node["parent"]:
            node["level"] = "area"
            node["source"] = "mixed" if node["direct_files"] else "derived"
            if not node["description"]:
                node["description"] = (
                    f"Top-level {name.replace('-', ' ')} area; child subsystems remain "
                    "separate so their responsibilities and dependency rules stay visible."
                )


def _materialize(
    name: str,
    nodes: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
    ancestors: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    node = nodes[name]
    child_items = (
        []
        if name in ancestors
        else [
            _materialize(child, nodes, children, ancestors | {name})
            for child in sorted(children[name])
        ]
    )
    return {
        **node,
        "files": int(node["direct_files"]) + sum(int(item["files"]) for item in child_items),
        "lines_of_code": int(node["direct_lines_of_code"])
        + sum(int(item["lines_of_code"]) for item in child_items),
        "children": sorted(
            child_items,
            key=lambda item: (-int(item["lines_of_code"]), item["name"]),
        ),
    }
