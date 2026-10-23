"""Bounded-memory paging of virtual unknown targets from canonical call facts."""

from __future__ import annotations

import heapq

from anaxigraph.knowledge_unresolved import iter_unresolved_nodes


def unresolved_page(connection, context, **filters):
    offset = max(0, int(filters.get("offset", 0)))
    limit = min(1000, max(1, int(filters.get("limit", 100))))
    total = 0

    def selected():
        nonlocal total
        for node in iter_unresolved_nodes(connection, context["snapshot_id"]):
            if _matches(node, filters):
                total += 1
                yield node

    page = heapq.nsmallest(offset + limit, selected(), key=lambda node: _order(node, filters))[
        offset:
    ]
    for node in page:
        node["placement"] = _placement(node, filters)
    return {
        "context": context,
        "nodes": page,
        "edges": [],
        "total_nodes": total,
        "returned_nodes": len(page),
        "total_edges": 0,
        "returned_edges": 0,
        "next_offset": offset + limit if offset + limit < total else None,
        "facets": {"areas": [], "subsystems": [], "languages": []},
        "selection": "Virtual unresolved targets; expand a target to inspect its callers and evidence.",
    }


def _matches(node, filters):
    if filters.get("evidence_state", "") not in {"", "unresolved"}:
        return False
    if filters.get("kind", "") not in {"", "unresolved"}:
        return False
    if node["reference"] and not filters.get("include_reference", False):
        return False
    query = str(filters.get("q", "")).casefold()
    if query not in (node["id"] + " " + node["label"] + " " + node["overview"]).casefold():
        return False
    placement = _placement(node, filters)
    for key in ("area", "subsystem", "language"):
        value = node["language"] if key == "language" else placement.get(key, "")
        if filters.get(key) and filters[key] != value:
            return False
    scope = filters.get("scope")
    return not scope or scope in {node["parent_id"], node["path"], placement.get("area")}


def _order(node, filters):
    field = filters.get("sort", "path")
    if field in {"summary", "overview"}:
        value = node["overview"]
    elif field == "architecture_area":
        value = _placement(node, filters)["area"]
    elif field == "coupling":
        value = node["metrics"]["fan_in"]
    else:
        value = node.get(field, node["metrics"].get(field))
    sortable = value if value is not None else ""
    if filters.get("direction") == "desc":
        sortable = _Descending(sortable)
    return (value is None, sortable, node["id"])


def _placement(node, filters):
    layer = filters.get("map_layer", "current")
    fallback = (
        node["placement"]
        if layer == "current"
        else {"area": "unconfigured", "subsystem": "unconfigured"}
    )
    return node["architecture_layers"].get(layer) or fallback


class _Descending:
    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        return self.value > other.value

    def __eq__(self, other):
        return self.value == other.value
