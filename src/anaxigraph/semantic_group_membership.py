"""Resolve semantic-map or deterministic fallback members for scope synthesis."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.config import AnaxiGraphConfig


def synthesis_groups(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    inventory: dict[str, dict[str, Any]],
    config: AnaxiGraphConfig,
) -> tuple[dict[str, set[str]], dict[str, dict[str, Any]]]:
    taxonomy = connection.execute(
        """
        SELECT * FROM semantic_taxonomies
        WHERE snapshot_id = ? AND status = 'current' ORDER BY id DESC LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    if taxonomy is not None:
        return _semantic_groups(connection, int(taxonomy["id"]), set(inventory))
    return _fallback_groups(inventory, config)


def _semantic_groups(
    connection: sqlite3.Connection,
    taxonomy_id: int,
    inventory_paths: set[str],
) -> tuple[dict[str, set[str]], dict[str, dict[str, Any]]]:
    rows = connection.execute(
        """
        SELECT node_key, name, level, parent_key, description, responsibility, confidence
        FROM semantic_taxonomy_nodes WHERE taxonomy_id = ?
        """,
        (taxonomy_id,),
    ).fetchall()
    metadata = {
        str(row["node_key"]): {
            **dict(row),
            "source": "semantic",
            "taxonomy_id": taxonomy_id,
        }
        for row in rows
    }
    memberships = connection.execute(
        """
        SELECT a.canonical_path AS path, stm.node_key
        FROM semantic_taxonomy_memberships stm
        JOIN artifacts a ON a.id = stm.artifact_id
        WHERE stm.taxonomy_id = ?
        """,
        (taxonomy_id,),
    ).fetchall()
    members: dict[str, set[str]] = {}
    for row in memberships:
        path = str(row["path"])
        if path not in inventory_paths:
            continue
        key = str(row["node_key"])
        seen: set[str] = set()
        while key and key not in seen:
            seen.add(key)
            members.setdefault(key, set()).add(path)
            key = str(metadata.get(key, {}).get("parent_key") or "")
    return members, metadata


def _fallback_groups(
    inventory: dict[str, dict[str, Any]], config: AnaxiGraphConfig
) -> tuple[dict[str, set[str]], dict[str, dict[str, Any]]]:
    metadata = {
        group.name: {
            "node_key": group.name,
            "name": group.name,
            "level": group.level,
            "parent_key": group.parent,
            "description": group.description,
            "responsibility": group.description,
            "confidence": 1.0,
            "source": "policy",
            "taxonomy_id": None,
        }
        for group in config.groups
    }
    members: dict[str, set[str]] = {}
    for path, module in inventory.items():
        key = str(module.get("declared_group") or module.get("inferred_group") or "ungrouped")
        metadata.setdefault(
            key,
            {
                "node_key": key,
                "name": key,
                "level": "subsystem",
                "parent_key": None,
                "description": "",
                "responsibility": "",
                "confidence": 1.0,
                "source": "inferred",
                "taxonomy_id": None,
            },
        )
        seen: set[str] = set()
        while key and key not in seen:
            seen.add(key)
            members.setdefault(key, set()).add(path)
            key = str(metadata.get(key, {}).get("parent_key") or "")
    return members, metadata
