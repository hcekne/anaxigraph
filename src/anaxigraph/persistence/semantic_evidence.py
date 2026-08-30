"""Canonical temporal evidence used to plan and execute semantic work."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_reads import (
    artifact_types_for_files,
    snapshot_files,
    snapshot_relationship_edges,
    symbols_for_files,
)
from anaxigraph.relationships import relationship_metadata


def semantic_inventory(
    connection: sqlite3.Connection,
    snapshot_id: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    files = snapshot_files(connection, snapshot_id)
    symbols = symbols_for_files(connection, files)
    edges = snapshot_relationship_edges(connection, snapshot_id)
    artifact_types = artifact_types_for_files(connection, files)
    inventory = _inventory(files, symbols, artifact_types)
    return inventory, _relationship_map(files, edges)


def module_facts(
    connection: sqlite3.Connection,
    snapshot_id: int,
    artifact_id: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    files = snapshot_files(connection, snapshot_id)
    module = next(
        (file for file in files if int(file["artifact_id"]) == artifact_id),
        None,
    )
    if module is None:
        return None, []
    symbols = symbols_for_files(connection, [module])
    return module, [
        {
            key: symbol[key]
            for key in ("symbol_type", "name", "signature", "start_line", "end_line", "summary")
        }
        for symbol in symbols
    ]


def relationships_for_artifact(
    connection: sqlite3.Connection,
    snapshot_id: int,
    artifact_id: int,
) -> list[dict[str, Any]]:
    files = snapshot_files(connection, snapshot_id)
    paths = {int(file["artifact_id"]): str(file["path"]) for file in files}
    result: list[dict[str, Any]] = []
    for edge in snapshot_relationship_edges(connection, snapshot_id):
        source_id = int(edge["source_artifact_id"])
        target_id = (
            int(edge["target_artifact_id"]) if edge["target_artifact_id"] is not None else None
        )
        if artifact_id not in {source_id, target_id}:
            continue
        outgoing = source_id == artifact_id
        metadata = relationship_metadata(edge)
        result.append(
            {
                "direction": "uses" if outgoing else "used_by",
                "path": (
                    paths.get(target_id) or edge["target_external"]
                    if outgoing
                    else paths.get(source_id)
                ),
                "type": edge["relationship_type"],
                "confidence": edge["confidence"],
                "resolution": metadata.get("resolution_status", "unknown"),
                "evidence": edge["evidence"],
            }
        )
    return sorted(result, key=lambda item: (str(item["path"]), item["direction"], item["type"]))


def _inventory(
    files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    artifact_types: dict[int, str],
) -> dict[str, dict[str, Any]]:
    symbols_by_fact: dict[int, list[dict[str, Any]]] = {}
    for symbol in symbols:
        symbols_by_fact.setdefault(int(symbol["file_fact_id"]), []).append(
            {
                key: symbol[key]
                for key in ("symbol_type", "name", "signature", "start_line", "end_line")
            }
        )
    result: dict[str, dict[str, Any]] = {}
    for file in files:
        module = dict(file)
        artifact_id = int(module["artifact_id"])
        fact_id = int(module["file_fact_id"])
        module["artifact_type"] = artifact_types.get(artifact_id, "source")
        module["artifact_version_id"] = None
        module["public_interfaces"] = _json_list(module["public_interfaces_json"])
        module["symbols"] = symbols_by_fact.get(fact_id, [])
        result[str(module["path"])] = module
    return result


def _relationship_map(
    files: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    paths = {int(file["artifact_id"]): str(file["path"]) for file in files}
    result: dict[str, list[dict[str, Any]]] = {path: [] for path in paths.values()}
    for edge in edges:
        source = paths.get(int(edge["source_artifact_id"]))
        if source is None:
            continue
        target_id = edge["target_artifact_id"]
        target = paths.get(int(target_id)) if target_id is not None else edge["target_external"]
        metadata = relationship_metadata(edge)
        result[source].append(
            {
                "direction": "uses",
                "path": target,
                "type": edge["relationship_type"],
                "resolution": metadata.get("resolution_status", "unknown"),
                "candidates": metadata.get("candidate_paths", []),
            }
        )
        if target_id is not None and int(target_id) in paths:
            result[paths[int(target_id)]].append(
                {
                    "direction": "used_by",
                    "path": source,
                    "type": edge["relationship_type"],
                    "resolution": metadata.get("resolution_status", "resolved_internal"),
                    "candidates": [],
                }
            )
    for values in result.values():
        values.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return result


def _json_list(value: str) -> list[Any]:
    decoded = json.loads(value or "[]")
    return decoded if isinstance(decoded, list) else []
