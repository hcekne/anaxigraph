"""Bounded structural guidance without pretending static facts prove behavior."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict
from typing import Any

from anaxigraph.contracts import Graph, Node


def module_for(graph: Graph, value: str) -> Node | None:
    return next(
        (node for node in graph.nodes if node.kind == "module" and value in (node.id, node.path)),
        None,
    )


def neighborhood(graph: Graph, entity_id: str, limit: int = 30) -> dict[str, Any]:
    entity = next((n for n in graph.nodes if entity_id == n.id), None) or module_for(
        graph, entity_id
    )
    if entity is None:
        raise ValueError("Entity not found in this checkout's current graph")
    incoming = [asdict(e) for e in graph.edges if e.target == entity.id and e.kind != "contains"]
    outgoing = [asdict(e) for e in graph.edges if e.source == entity.id]
    if entity.kind == "module":
        # This is a projection of existing symbol-level observations, not another
        # inferred relationship store. Preserve each original edge as evidence.
        owners = {n.id: n.path for n in graph.nodes}
        modules = {n.path: n.id for n in graph.nodes if n.kind == "module"}
        projected = {}
        for edge in graph.edges:
            source, target = owners.get(edge.source), owners.get(edge.target)
            if source == target or source not in modules or target not in modules:
                continue
            if entity.path not in {source, target}:
                continue
            key = (source, target, edge.kind, edge.resolution)
            if key not in projected:
                projected[key] = {
                    **asdict(edge),
                    "source": modules[source],
                    "target": modules[target],
                    "projected_from": asdict(edge),
                    "observations": 0,
                }
            projected[key]["observations"] += 1
        incoming = [e for e in projected.values() if e["target"] == entity.id]
        local = [
            e
            for e in outgoing
            if owners.get(e["target"]) not in modules or owners.get(e["target"]) == entity.path
        ]
        outgoing = [e for e in projected.values() if e["source"] == entity.id] + local
    related = {e["source"] for e in incoming[:limit]} | {e["target"] for e in outgoing[:limit]}
    neighbors = []
    for node in graph.nodes:
        if node.id in related:
            brief = {
                "loc": node.data.get("loc"),
                "annotation_status": node.data.get("annotation_status"),
            }
            if node.data.get("annotation"):
                brief["overview"] = node.data["annotation"]["overview"]
            neighbors.append(
                asdict(Node(node.id, node.kind, node.name, node.path, node.line, brief))
            )
    neighbors = neighbors[:limit]
    return {
        "entity": asdict(entity),
        "incoming": incoming[:limit],
        "outgoing": outgoing[:limit],
        "neighbors": neighbors,
        "incoming_total": len(incoming),
        "outgoing_total": len(outgoing),
        "truncated": len(incoming) > limit or len(outgoing) > limit,
        "projection": "module rollup of observed symbol references"
        if entity.kind == "module"
        else "source observations",
    }


def affected_paths(graph: Graph, paths: set[str], depth: int = 2) -> set[str]:
    owners = {node.id: node.path for node in graph.nodes}
    reverse: dict[str, set[str]] = {}
    for edge in graph.edges:
        source, target = owners.get(edge.source), owners.get(edge.target)
        if source and target and source != target and edge.resolution == "resolved":
            reverse.setdefault(target, set()).add(source)
    pending = deque((path, 0) for path in paths)
    found = set(paths)
    while pending:
        path, level = pending.popleft()
        if level < depth:
            for caller in reverse.get(path, ()):
                if caller not in found:
                    found.add(caller)
                    pending.append((caller, level + 1))
    return found


def prepare(graph: Graph, matches: list[dict[str, Any]], task: str) -> dict[str, Any]:
    modules = {node.id: node for node in graph.nodes if node.kind == "module"}
    by_path = {node.path: node for node in modules.values()}
    candidates = list(
        {
            match["path"]: by_path[match["path"]]
            for match in matches
            if match.get("path") in by_path
        }.values()
    )
    paths = {node.path for node in candidates}
    impacted = affected_paths(graph, paths)
    contracts = []
    for node in modules.values():
        if node.path in impacted:
            contracts.extend(
                {
                    "owner": node.id,
                    "annotation_status": node.data.get("annotation_status", "missing"),
                    **contract,
                }
                for contract in node.data.get("annotation", {}).get("contracts", [])
            )
    tests = [
        node.path
        for node in modules.values()
        if node.path in impacted and (node.data.get("is_test") or node.path.startswith("tests/"))
    ]
    return {
        "task": task,
        "snapshot_id": graph.snapshot.id,
        "likely_owners": [
            {
                "id": n.id,
                "path": n.path,
                "overview": n.data.get("annotation", {}).get("overview"),
                "annotation_status": n.data.get("annotation_status", "missing"),
            }
            for n in candidates
        ],
        "reuse_candidates": matches[:20],
        "contracts": contracts[:30],
        "contract_overflow": max(0, len(contracts) - 30),
        "affected_paths": sorted(impacted)[:50],
        "affected_total": len(impacted),
        "tests": sorted(set(tests))[:20],
        "tests_total": len(set(tests)),
        "uncertainty": [
            "Placement is ranked evidence, not accepted architectural intent.",
            "Dynamic references and unparsed languages can hide consumers.",
            "Tests are associated by observed references; no tests were executed.",
        ],
    }


def structural_findings(graph: Graph) -> list[dict[str, Any]]:
    modules = [node for node in graph.nodes if node.kind == "module"]
    owners = {node.id: node.path for node in graph.nodes}
    module_ids = {node.path: node.id for node in modules}
    incoming = Counter(
        target
        for source, target in {
            (owners.get(edge.source), module_ids.get(owners.get(edge.target)))
            for edge in graph.edges
            if edge.resolution == "resolved" and owners.get(edge.source) != owners.get(edge.target)
        }
        if source and target
    )
    findings = []
    for node in modules:
        if node.data.get("loc", 0) > 500:
            findings.append(
                {
                    "kind": "large-module",
                    "entity": node.id,
                    "measured": node.data["loc"],
                    "threshold": 500,
                    "status": "concern",
                    "message": "Inspect responsibility boundaries; size alone is not a defect.",
                }
            )
        if incoming[node.id] > 15:
            findings.append(
                {
                    "kind": "high-fan-in",
                    "entity": node.id,
                    "measured": incoming[node.id],
                    "threshold": 15,
                    "status": "concern",
                    "message": "Check public contract stability before changing this shared dependency.",
                }
            )
    return findings
