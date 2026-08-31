"""Read the finalized snapshot-scoped semantic architecture map."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.semantic_taxonomy_language import (
    semantic_taxonomy_assignment_explanation,
    semantic_taxonomy_explanation,
)


def current_taxonomy(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM semantic_taxonomies
        WHERE snapshot_id = ? AND status = 'current' ORDER BY id DESC LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["validation"] = json.loads(result.pop("validation_json") or "{}")
    result["facets"] = json.loads(result.pop("facets_json") or "[]")
    result["changes"] = json.loads(result.pop("change_json") or "[]")
    result["reviews"] = [
        _review_payload(review)
        for review in connection.execute(
            """
            SELECT pass_index, verdict, issues_json, validation_json, created_at
            FROM semantic_taxonomy_reviews WHERE taxonomy_id = ? ORDER BY pass_index
            """,
            (result["id"],),
        ).fetchall()
    ]
    return result


def _review_payload(review: sqlite3.Row) -> dict[str, Any]:
    result = dict(review)
    result["issues"] = json.loads(result.pop("issues_json") or "[]")
    result["validation"] = json.loads(result.pop("validation_json") or "{}")
    return result


def taxonomy_assignments(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    artifact_ids: tuple[int, ...] | None = None,
) -> dict[int, dict[str, Any]]:
    taxonomy = current_taxonomy(connection, snapshot_id)
    if taxonomy is None:
        return {}
    if artifact_ids is not None and not artifact_ids:
        return {}
    restriction = ""
    parameters: tuple[Any, ...] = (taxonomy["id"],)
    if artifact_ids is not None:
        placeholders = ",".join("?" for _ in artifact_ids)
        restriction = f"AND stm.artifact_id IN ({placeholders})"
        parameters = (taxonomy["id"], *artifact_ids)
    rows = connection.execute(
        f"""
        SELECT stm.artifact_id, stm.node_key AS subsystem_key,
               subsystem.name AS subsystem_name,
               subsystem.parent_key AS area_key, area.name AS area_name,
               stm.confidence, stm.rationale, stm.evidence_json,
               stm.alternatives_json, stm.locked
        FROM semantic_taxonomy_memberships stm
        JOIN semantic_taxonomy_nodes subsystem
          ON subsystem.taxonomy_id = stm.taxonomy_id
         AND subsystem.node_key = stm.node_key
        LEFT JOIN semantic_taxonomy_nodes area
          ON area.taxonomy_id = subsystem.taxonomy_id
         AND area.node_key = subsystem.parent_key
        WHERE stm.taxonomy_id = ? {restriction}
        """,
        parameters,
    ).fetchall()
    return {int(row["artifact_id"]): _taxonomy_assignment(row, taxonomy) for row in rows}


def _taxonomy_assignment(row: sqlite3.Row, taxonomy: dict[str, Any]) -> dict[str, Any]:
    assignment = {
        "taxonomy_id": taxonomy["id"],
        "area": row["area_key"] or row["subsystem_key"],
        "area_name": row["area_name"] or row["subsystem_name"],
        "subsystem": row["subsystem_key"],
        "subsystem_name": row["subsystem_name"],
        "confidence": row["confidence"],
        "rationale": row["rationale"],
        "evidence": json.loads(row["evidence_json"] or "[]"),
        "alternatives": json.loads(row["alternatives_json"] or "[]"),
        "locked": bool(row["locked"]),
        "source": "inferred responsibility map",
        "freshness": taxonomy["updated_at"],
    }
    assignment["plain_language"] = semantic_taxonomy_assignment_explanation(assignment)
    assignment["area_label"] = assignment["plain_language"]["area_name"]
    assignment["subsystem_label"] = assignment["plain_language"]["subsystem_name"]
    return assignment


def read_semantic_hierarchy(
    connection: sqlite3.Connection, snapshot_id: int
) -> list[dict[str, Any]]:
    taxonomy = current_taxonomy(connection, snapshot_id)
    if taxonomy is None:
        return []
    rows = connection.execute(
        """
        SELECT node_key, name, level, parent_key, description, responsibility,
               confidence, rationale, evidence_json, counter_evidence_json, display_order
        FROM semantic_taxonomy_nodes WHERE taxonomy_id = ?
        ORDER BY display_order, name
        """,
        (taxonomy["id"],),
    ).fetchall()
    stats = {
        str(row["node_key"]): {
            "direct_files": int(row["files"] or 0),
            "direct_lines_of_code": int(row["lines_of_code"] or 0),
        }
        for row in connection.execute(
            """
            SELECT stm.node_key, COUNT(*) AS files,
                   COALESCE(SUM(fv.lines_of_code), 0) AS lines_of_code
            FROM semantic_taxonomy_memberships stm
            JOIN projected_file_versions fv ON fv.artifact_id = stm.artifact_id
            WHERE stm.taxonomy_id = ? GROUP BY stm.node_key
            """,
            (taxonomy["id"],),
        ).fetchall()
    }
    nodes = {}
    for row in rows:
        key = str(row["node_key"])
        nodes[key] = _semantic_node(row, taxonomy, stats.get(key))
    children = hierarchy_children(nodes)
    roots = [key for key, node in nodes.items() if node["parent"] not in nodes]
    return sorted(
        (materialize_hierarchy(key, nodes, children) for key in roots),
        key=lambda item: (-int(item["lines_of_code"]), item["name"]),
    )


def _semantic_node(
    row: sqlite3.Row,
    taxonomy: dict[str, Any],
    stats: dict[str, int] | None,
) -> dict[str, Any]:
    node = {
        "key": str(row["node_key"]),
        "name": str(row["node_key"]),
        "label": row["name"],
        "level": row["level"],
        "parent": row["parent_key"],
        "source": "responsibility",
        "description": row["description"],
        "responsibility": row["responsibility"],
        "confidence": row["confidence"],
        "rationale": row["rationale"],
        "evidence": json.loads(row["evidence_json"] or "[]"),
        "counter_evidence": json.loads(row["counter_evidence_json"] or "[]"),
        "taxonomy_id": taxonomy["id"],
        "freshness": taxonomy["updated_at"],
        **(stats or {"direct_files": 0, "direct_lines_of_code": 0}),
    }
    node["plain_language"] = semantic_taxonomy_explanation(node)
    return node


def taxonomy_map_payload(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    taxonomy = current_taxonomy(connection, snapshot_id)
    if taxonomy is None:
        return None
    return {
        "id": taxonomy["id"],
        "snapshot_id": taxonomy["snapshot_id"],
        "status": taxonomy["status"],
        "source": taxonomy["source"],
        "provider": taxonomy["provider"],
        "model": taxonomy["model"],
        "executor_id": taxonomy["executor_id"],
        "executor_model": taxonomy["executor_model"],
        "confidence": taxonomy["confidence"],
        "review_passes": taxonomy["review_passes"],
        "validation": taxonomy["validation"],
        "facets": taxonomy["facets"],
        "changes": taxonomy["changes"],
        "reviews": taxonomy["reviews"],
        "created_at": taxonomy["created_at"],
        "updated_at": taxonomy["updated_at"],
        "hierarchy": read_semantic_hierarchy(connection, snapshot_id),
    }


def hierarchy_children(nodes: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {key: [] for key in nodes}
    for key, node in nodes.items():
        if node["parent"] in children and node["parent"] != key:
            children[node["parent"]].append(key)
    return children


def materialize_hierarchy(
    key: str,
    nodes: dict[str, dict[str, Any]],
    children: dict[str, list[str]],
    ancestors: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    node = nodes[key]
    child_items = (
        []
        if key in ancestors
        else [
            materialize_hierarchy(child, nodes, children, ancestors | {key})
            for child in children[key]
        ]
    )
    return {
        **node,
        "files": int(node["direct_files"]) + sum(int(item["files"]) for item in child_items),
        "lines_of_code": int(node["direct_lines_of_code"])
        + sum(int(item["lines_of_code"]) for item in child_items),
        "children": sorted(
            child_items, key=lambda item: (-int(item["lines_of_code"]), item["name"])
        ),
    }
