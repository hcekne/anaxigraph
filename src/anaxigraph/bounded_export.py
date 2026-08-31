"""One bounded export contract shared by local and HTTP clients."""

from __future__ import annotations

from typing import Any

from anaxigraph.finding_transport import query_findings

FINDING_LIMIT = 200
SNAPSHOT_LIMIT = 100
TAXONOMY_LIMIT = 250


def bounded_export(database: Any, repository_id: int, config: Any) -> dict[str, Any]:
    findings = query_findings(
        database,
        repository_id,
        config,
        view="diagnostics",
        page_size=FINDING_LIMIT,
    )
    return {
        "contract_version": "anaxigraph-export-v1",
        "limits": {
            "graph_nodes": 250,
            "graph_edges": 500,
            "finding_items": FINDING_LIMIT,
            "snapshots": SNAPSHOT_LIMIT,
            "taxonomy_nodes": TAXONOMY_LIMIT,
        },
        "overview": _compact_overview(database.overview(repository_id)),
        "graph": database.graph(repository_id, include_external=True),
        "findings": _compact_findings(findings),
        "snapshots": database.snapshots(repository_id, limit=SNAPSHOT_LIMIT),
        "semantic_taxonomy": _compact_taxonomy(database.semantic_taxonomy(repository_id)),
    }


def _compact_overview(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    hierarchy_count = sum(
        _tree_size(items) for items in (result.get("group_hierarchies") or {}).values()
    )
    result.pop("group_hierarchies", None)
    result["export_omissions"] = {
        "hierarchy_nodes": hierarchy_count,
    }
    result["languages"] = list(result.get("languages") or [])[:250]
    return result


def _compact_findings(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    groups = list(result.get("groups") or [])
    result["groups"] = groups[:250]
    omitted = dict(result.get("omitted") or {})
    omitted["diagnostic_groups"] = int(omitted.get("diagnostic_groups") or 0) + max(
        0, len(groups) - 250
    )
    filters = dict(result.get("available_filters") or {})
    result["available_filters"] = {key: list(items)[:250] for key, items in filters.items()}
    omitted["available_filters"] = {key: max(0, len(items) - 250) for key, items in filters.items()}
    result["omitted"] = omitted
    return result


def _compact_taxonomy(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result = dict(value)
    hierarchy = list(result.get("hierarchy") or [])
    total = _tree_size(hierarchy)
    remaining = [TAXONOMY_LIMIT]
    result["hierarchy"] = _bound_tree(hierarchy, remaining)
    result["export_omitted_nodes"] = max(0, total - TAXONOMY_LIMIT)
    result["reviews"] = list(result.get("reviews") or [])[:25]
    result["changes"] = list(result.get("changes") or [])[:250]
    return result


def _bound_tree(items: list[dict[str, Any]], remaining: list[int]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        if remaining[0] <= 0:
            break
        remaining[0] -= 1
        bounded = {key: value for key, value in item.items() if key != "children"}
        bounded["children"] = _bound_tree(list(item.get("children") or []), remaining)
        result.append(bounded)
    return result


def _tree_size(items: list[dict[str, Any]]) -> int:
    return sum(1 + _tree_size(list(item.get("children") or [])) for item in items)
