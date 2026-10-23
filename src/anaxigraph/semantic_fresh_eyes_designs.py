"""Conservative observations about proposed designs, without a novelty verdict."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any


def design_observations(alternatives: list[dict[str, Any]]) -> dict[str, Any]:
    exact, topology = defaultdict(list), defaultdict(list)
    for alternative in alternatives:
        design = alternative.get("design")
        if not design:
            continue
        exact[_signature(design)].append(alternative["id"])
        topology[_signature(_topology(design))].append(alternative["id"])
    return {
        "method": "exact_payload_and_coarse_topology_v1",
        "exact_repeated_designs": [group for group in exact.values() if len(group) > 1],
        "shared_coarse_topology": [group for group in topology.values() if len(group) > 1],
        "limitations": [
            "Equal degree profiles and edge kinds do not establish equivalent architecture.",
            "Different names, prose or graph shapes do not establish useful design differences.",
            "Novelty is unverified; compare decomposition, control, data and failure semantics.",
        ],
    }


def _topology(design: dict[str, Any]) -> dict[str, Any]:
    edges = design.get("relationships", [])
    incoming = Counter(edge["target"] for edge in edges)
    outgoing = Counter(edge["source"] for edge in edges)
    return {
        "degree_profiles": sorted(
            (incoming[node["key"]], outgoing[node["key"]]) for node in design.get("components", [])
        ),
        "relationship_kinds": sorted(Counter(edge["relationship"] for edge in edges).items()),
    }


def _signature(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
