"""Typed structural links with conservative function-call resolution."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.knowledge_call_resolution import call_index, call_owner, resolve_call
from anaxigraph.knowledge_nodes import entity_id, symbol_kind
from anaxigraph.knowledge_schema import compact_edge_evidence


def insert_edge(
    connection: sqlite3.Connection,
    snapshot_id: int,
    source: str,
    target: str,
    kind: str,
    *,
    evidence: Any = None,
    confidence: float = 1.0,
    resolution: str = "resolved_internal",
    method: str = "extracted",
) -> None:
    identity = json.dumps([source, target, kind], separators=(",", ":"))
    key = hashlib.sha256(identity.encode()).hexdigest()[:24]
    connection.execute(
        "INSERT OR REPLACE INTO graph_connections VALUES (?,?,?,?,?,?,?,?,?)",
        (
            snapshot_id,
            key,
            source,
            target,
            kind,
            confidence,
            resolution,
            json.dumps(compact_edge_evidence(evidence or [], source)),
            json.dumps({"method": method}),
        ),
    )


def structural_links(connection, snapshot_id, files, symbols, relationships) -> None:
    paths = {file["artifact_id"]: file["path"] for file in files}
    for symbol in symbols:
        path = paths[symbol["artifact_id"]]
        kind = symbol_kind(symbol)
        node = entity_id(kind, path, symbol["qualified_name"])
        insert_edge(connection, snapshot_id, entity_id("module", path), node, "defines")
        if kind == "function" and symbol.get("visibility") == "public":
            insert_edge(
                connection,
                snapshot_id,
                node,
                entity_id("interface", path, symbol["qualified_name"]),
                "implements",
            )
    for edge in relationships:
        target_path = paths.get(edge["target_artifact_id"])
        if target_path is None:
            continue
        source_path = paths[edge["source_artifact_id"]]
        metadata = json.loads(edge.get("metadata_json") or "{}")
        insert_edge(
            connection,
            snapshot_id,
            entity_id("module", source_path),
            entity_id("module", target_path),
            edge["relationship_type"],
            evidence=[{"path": source_path, "line": edge["source_line"], "text": edge["evidence"]}],
            confidence=edge["confidence"],
            resolution=metadata.get("resolution_status", "resolved_internal"),
        )


def prepare_function_links(files, symbols):
    """Resolve calls once before inserting nodes, including their final lazy references."""
    by_fact = defaultdict(list)
    for symbol in symbols:
        by_fact[symbol["file_fact_id"]].append(symbol)
    index = call_index(files, symbols)
    links, references = [], {}
    for file in files:
        metadata = file["call_metadata"]
        local = by_fact[file["file_fact_id"]]
        unresolved = defaultdict(list)
        for position, call in enumerate(metadata.get("call_sites", [])):
            owner, link = _resolved_call(file, call, local, index)
            if link is None:
                unresolved[owner].append((position, call["target"]))
            else:
                links.append(link)
        references.update(
            {
                owner: {
                    "unresolved_call_sites": [position for position, _target in entries],
                    "unresolved_call_count": len(entries),
                    "unresolved_target_count": len({target for _position, target in entries}),
                }
                for owner, entries in unresolved.items()
            }
        )
    return links, references


def _resolved_call(file, call, symbols, index):
    caller = call_owner(symbols, call)
    candidates = resolve_call(file, call, caller, index)
    source = (
        entity_id("function", file["path"], caller["qualified_name"])
        if caller
        else entity_id("module", file["path"])
    )
    if len(candidates) != 1:
        return source, None
    callee = candidates[0]
    destination = entity_id(symbol_kind(callee), callee["path"], callee["qualified_name"])
    inferred = call.get("binding") == "receiver" or call["target"].startswith(
        ("self.", "cls.", "this.")
    )
    return source, (source, destination, file["path"], call["line"], call["target"], inferred)


def function_links(connection, snapshot, links) -> None:
    for source, destination, path, line, target, inferred in links:
        evidence = [{"path": path, "line": line, "target": target}]
        insert_edge(
            connection,
            snapshot,
            source,
            destination,
            "calls",
            evidence=evidence,
            confidence=0.75 if inferred else 1.0,
            resolution="inferred" if inferred else "resolved_internal",
        )
        if path.startswith(("tests/", "test/")):
            insert_edge(connection, snapshot, source, destination, "tests", evidence=evidence)
