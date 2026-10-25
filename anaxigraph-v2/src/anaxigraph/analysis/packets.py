"""Explicit work contracts for external coding agents.

Fresh Eyes receives only behavior statements with opaque requirement identities.
Current source, paths, symbols, dependencies and prior recommendations stay out.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from importlib.resources import files
from typing import Any

from anaxigraph.contracts import Graph, Node

KINDS = {"annotate", "patterns", "fresh-eyes"}
MAX_PACKET_BYTES = 256_000


def catalogue() -> list[dict[str, Any]]:
    content = files(__package__).joinpath("catalog/patterns.json").read_text(encoding="utf-8")
    return json.loads(content)["cards"]


def _scope(graph: Graph, requested: list[str] | None, kind: str) -> list[Node]:
    modules = [node for node in graph.nodes if node.kind == "module"]
    if not modules:
        raise ValueError("No supported source modules are mapped; scan Python source first")
    if not requested:
        requested = [modules[0].id] if kind != "fresh-eyes" else [node.id for node in modules]
    chosen = [node for node in modules if node.id in requested or node.path in requested]
    matched = {value for value in requested if any(value in (n.id, n.path) for n in chosen)}
    if len(matched) != len(set(requested)):
        raise ValueError("Scope must name mapped module IDs or repository-relative source paths")
    if kind in {"annotate", "patterns"} and len(chosen) > 4:
        raise ValueError("Select at most four modules per independent review batch")
    return chosen


def _annotation_current(node: Node) -> bool:
    return bool(node.data.get("annotation")) and node.data.get("annotation_status") == "current"


def build_request(
    graph: Graph, kind: str, scope: list[str] | None = None, sources: dict[str, str] | None = None
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError("Analysis kind must be annotate, patterns, or fresh-eyes")
    chosen = _scope(graph, scope, kind)
    ids = {node.id for node in chosen}
    symbols = [
        node
        for node in graph.nodes
        if node.path in {n.path for n in chosen} and node.kind in {"function", "method"}
    ]
    packet: dict[str, Any]
    if kind == "annotate":
        packet = {
            "instruction": (
                "Explain behavior concisely: one module overview sentence and short paragraph, "
                "one sentence for EVERY supplied function, capabilities and behavioral contracts. "
                "Use source evidence for claims; distinguish declared from inferred obligations. "
                "Capabilities must describe observable behavior without implementation names, source "
                "paths or current module boundaries, for later blind design. Do not duplicate "
                "signatures or invent guarantees. List uncertainty."
            ),
            "modules": [asdict(node) for node in chosen],
            "functions": [asdict(node) for node in symbols],
            "relationships": [
                asdict(edge) for edge in graph.edges if edge.source in ids or edge.target in ids
            ][:200],
            "source": {},
        }
        for node in chosen:
            if sources is None or node.path not in sources:
                raise ValueError("Annotation needs captured source supplied by the application")
            packet["source"][node.path] = sources[node.path]
        schema = {
            "annotations": [
                {
                    "node_id": "module ID",
                    "overview": "sentence",
                    "detail": "short paragraph",
                    "capabilities": ["behavior"],
                    "functions": [{"node_id": "function ID", "overview": "sentence"}],
                    "contracts": [
                        {
                            "statement": "obligation",
                            "basis": "declared|inferred",
                            "evidence": [{"path": "relative path", "line": 1}],
                        }
                    ],
                    "uncertainty": ["unresolved question"],
                }
            ],
            "producer": "agent/model identity",
        }
    elif kind == "patterns":
        selected_paths = {node.path for node in chosen}
        selected_ids = {node.id for node in graph.nodes if node.path in selected_paths}
        owners = {node.id: node.path for node in graph.nodes}
        packet = {
            "instruction": (
                "Independently advocate for EACH catalogue pattern against EACH supplied module. "
                "Look for useful alternate responsibility, state, interface and control-flow designs, "
                "not just existing defects. Give opportunity 0–3 (0=no useful benefit, 3=strong), "
                "or null when evidence is insufficient. Explain concrete pros AND costs for every "
                "pair, including rejections. Compare a simple local alternative. Do not manufacture "
                "a problem to justify a pattern. Separate current_fit (present/partial/absent/unknown) "
                "from incremental opportunity. A pattern already implemented well earns no change "
                "opportunity merely because it is a good fit. Positive scores require a specific "
                "proposed_change and evidence for its benefit beyond current behavior. Check existing "
                "language/framework guarantees before proposing equivalent behavior. No card or module may be skipped."
            ),
            "catalogue": catalogue(),
            "modules": [asdict(node) for node in chosen],
            "symbols": [
                asdict(node)
                for node in graph.nodes
                if node.id in selected_ids and node.kind not in {"module", "external"}
            ],
            "connectivity": [
                {
                    "module_id": node.id,
                    "consumer_modules": len(
                        {
                            owners.get(edge.source)
                            for edge in graph.edges
                            if owners.get(edge.target) == node.path
                            and owners.get(edge.source) != node.path
                        }
                    ),
                    "dependency_modules": len(
                        {
                            owners.get(edge.target)
                            for edge in graph.edges
                            if owners.get(edge.source) == node.path
                            and owners.get(edge.target) != node.path
                        }
                    ),
                }
                for node in chosen
            ],
            "relationships": [
                asdict(edge)
                for edge in graph.edges
                if edge.source in selected_ids or edge.target in selected_ids
            ][:300],
            "evidence_limit": "Static Python graph and saved annotations; inspect source for verification.",
        }
        schema = {
            "evaluations": [
                {
                    "module_id": "module ID",
                    "pattern_id": "catalogue ID",
                    "opportunity": "integer 0–3 or null",
                    "current_fit": "present|partial|absent|unknown",
                    "proposed_change": "specific incremental improvement, or no change",
                    "pros": ["specific benefit or none"],
                    "cons": ["cost or counterevidence"],
                    "alternative": "simpler approach",
                    "evidence": [{"path": "relative path", "line": 1}],
                }
            ],
            "producer": "agent/model identity",
        }
    else:
        missing = [n.path for n in chosen if not _annotation_current(n)]
        if missing:
            raise ValueError(
                f"Fresh Eyes needs current behavior annotations; missing/stale: {missing[:5]}"
            )
        requirements = []
        for node in chosen:
            annotation = node.data["annotation"]
            for capability in annotation.get("capabilities", []):
                requirements.append({"id": f"R{len(requirements) + 1}", "behavior": capability})
            for contract in annotation.get("contracts", []):
                requirements.append(
                    {
                        "id": f"R{len(requirements) + 1}",
                        "behavior": contract["statement"],
                        "basis": contract["basis"],
                    }
                )
        if not requirements:
            raise ValueError("No functional requirements available; annotate capabilities first")
        implementation_tokens = {node.id for node in graph.nodes}
        implementation_tokens.update(node.path for node in graph.nodes if node.kind == "module")
        for requirement in requirements:
            if any(token and token in requirement["behavior"] for token in implementation_tokens):
                raise ValueError(
                    "Functional statement contains source identity; rewrite it as behavior before Fresh Eyes"
                )
        packet = {
            "instruction": (
                "You are an independent product designer. You receive BEHAVIOR ONLY. Do not inspect "
                "source, repository files or existing architecture. Propose THREE materially different "
                "ways to deliver ALL requirements. Compare responsibility, state and failure ownership; "
                "justify added complexity and explain a minimal option. Preserve the original behavior. "
                "Each design must list every requirement ID and supply its own high-level Mermaid diagram. "
                "Do not collapse the alternatives into a winner or claim tested implementation."
            ),
            "requirements": requirements,
            "blindness": "No source, source paths, symbols, observed dependency topology or prior reviews.",
        }
        schema = {
            "alternatives": [
                {
                    "name": "distinct design",
                    "design": "concrete explanation",
                    "requirements": ["ALL requirement IDs"],
                    "pros": ["benefit"],
                    "cons": ["cost"],
                    "diagram": "flowchart TB ...",
                }
            ],
            "producer": "agent/model identity",
        }
    digest = hashlib.sha256(
        json.dumps(
            {
                "schema": 1,
                "snapshot": graph.snapshot.id,
                "kind": kind,
                "scope": sorted(ids),
                "packet": packet,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:24]
    # Only the task packet is delivered to blind designers; the envelope is for the
    # orchestrating agent. Source-aware comparison is a later, separate operation.
    request = {
        "request_id": digest,
        "kind": kind,
        "snapshot_id": graph.snapshot.id,
        "scope": sorted(ids),
        "packet": packet,
        "response_schema": schema,
        "function_ids": {n.id: [s.id for s in symbols if s.path == n.path] for n in chosen},
    }
    if len(json.dumps(request).encode()) > MAX_PACKET_BYTES:
        raise ValueError("Analysis packet exceeds 256 KB; select a smaller independent scope")
    return request
