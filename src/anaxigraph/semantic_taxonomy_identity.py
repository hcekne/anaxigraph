"""Preserve semantic taxon identity across temporal repository snapshots."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.agent_lexicon import jaccard as _jaccard


def stable_taxonomy_nodes(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    nodes: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    stability_bias: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    previous_id, previous_nodes, previous_members = _previous_nodes(
        connection, repository_id, snapshot_id
    )
    member_sets = _node_member_sets(nodes, assignments)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    events: list[dict[str, Any]] = []
    level_order = {"area": 0, "subsystem": 1}
    for temp_key, node in sorted(
        nodes.items(), key=lambda item: (level_order.get(item[1]["level"], 2), item[0])
    ):
        match = _best_previous(
            temp_key,
            node,
            member_sets[temp_key],
            previous_nodes,
            previous_members,
            used,
            stability_bias,
        )
        stable_key = match or _unique_key(temp_key, used | set(previous_nodes))
        mapping[temp_key] = stable_key
        used.add(stable_key)
        if match and previous_nodes[match]["name"] != node["name"]:
            events.append(
                {
                    "type": "rename",
                    "node_key": match,
                    "from": previous_nodes[match]["name"],
                    "to": node["name"],
                }
            )
        elif not match:
            events.append({"type": "add", "node_key": stable_key, "name": node["name"]})
    if previous_id:
        for key, node in previous_nodes.items():
            if key not in used:
                events.append({"type": "remove", "node_key": key, "name": node["name"]})
    result = []
    for temp_key, node in nodes.items():
        result.append(
            {
                **{
                    key: value
                    for key, value in node.items()
                    if key not in {"temp_key", "parent_temp_key", "locked"}
                },
                "node_key": mapping[temp_key],
                "parent_key": mapping.get(node["parent_temp_key"]),
                "temp_key": temp_key,
            }
        )
    result.sort(key=lambda node: (node["level"] != "area", node["display_order"], node["name"]))
    return result, events


def _previous_nodes(
    connection: sqlite3.Connection, repository_id: int, snapshot_id: int
) -> tuple[int | None, dict[str, dict[str, Any]], dict[str, set[str]]]:
    row = connection.execute(
        """
        SELECT id FROM semantic_taxonomies
        WHERE repository_id = ? AND snapshot_id != ? AND status = 'current'
        ORDER BY snapshot_id DESC, id DESC LIMIT 1
        """,
        (repository_id, snapshot_id),
    ).fetchone()
    if row is None:
        return None, {}, {}
    taxonomy_id = int(row["id"])
    nodes = {
        str(item["node_key"]): dict(item)
        for item in connection.execute(
            """
            SELECT node_key, name, level, parent_key, responsibility
            FROM semantic_taxonomy_nodes WHERE taxonomy_id = ?
            """,
            (taxonomy_id,),
        ).fetchall()
    }
    members: dict[str, set[str]] = defaultdict(set)
    for item in connection.execute(
        """
        SELECT stm.node_key, a.canonical_path FROM semantic_taxonomy_memberships stm
        JOIN artifacts a ON a.id = stm.artifact_id WHERE stm.taxonomy_id = ?
        """,
        (taxonomy_id,),
    ).fetchall():
        members[str(item["node_key"])].add(str(item["canonical_path"]))
    for key, node in nodes.items():
        if node["level"] == "area":
            members[key] = set().union(
                *(
                    members[child]
                    for child, value in nodes.items()
                    if value.get("parent_key") == key
                )
            )
    return taxonomy_id, nodes, members


def _node_member_sets(
    nodes: dict[str, dict[str, Any]], assignments: dict[str, dict[str, Any]]
) -> dict[str, set[str]]:
    members: dict[str, set[str]] = defaultdict(set)
    for path, assignment in assignments.items():
        members[assignment["node_key"]].add(path)
    for key, node in nodes.items():
        if node["level"] == "area":
            members[key] = set().union(
                *(
                    members[child]
                    for child, value in nodes.items()
                    if value["parent_temp_key"] == key
                )
            )
    return members


def _best_previous(
    key: str,
    node: dict[str, Any],
    members: set[str],
    previous_nodes: dict[str, dict[str, Any]],
    previous_members: dict[str, set[str]],
    used: set[str],
    stability_bias: float,
) -> str | None:
    if key in previous_nodes and key not in used and previous_nodes[key]["level"] == node["level"]:
        return key
    best_key = None
    best_score = 0.0
    for candidate, previous in previous_nodes.items():
        if candidate in used or previous["level"] != node["level"]:
            continue
        member_score = _jaccard(members, previous_members.get(candidate, set()))
        words = _tokens(f"{node['name']} {node['responsibility']}")
        previous_words = _tokens(f"{previous['name']} {previous['responsibility']}")
        score = stability_bias * member_score + (1 - stability_bias) * _jaccard(
            words, previous_words
        )
        if score > best_score:
            best_key, best_score = candidate, score
    return best_key if best_score >= 0.45 else None


def _unique_key(value: str, used: set[str]) -> str:
    if value not in used:
        return value
    index = 2
    while f"{value}-{index}" in used:
        index += 1
    return f"{value}-{index}"


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9]+", value.lower()) if len(item) > 2}
