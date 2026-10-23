"""Bound agent journey summaries while making omitted detail explicit."""

from __future__ import annotations

import copy
import json
from typing import Any

from anaxigraph.call_graph_contract import CALLABLE_SYMBOL_KINDS
from anaxigraph.knowledge_nodes import sentence

_IDENTITIES = {
    "path",
    "checkout_path",
    "repository_path",
    "entity_id",
    "qualified_name",
    "graph_subject",
    "id",
    "source",
    "target",
}


def compact_file_response(value):
    documents = value.get("semantic_dossiers") or {}
    selected = documents.get("context") or documents.get("intrinsic") or {}
    annotation = selected.get("value") or {}
    file = value.get("file") or {}
    functions = {
        item["qualified_name"]: item["overview"] for item in annotation.get("functions", [])
    }
    overview = sentence(
        annotation.get("overview") or annotation.get("summary") or file.get("summary", "")
    )
    brief = {
        "file": _file_identity(file, overview),
        "detail": annotation.get("detail", ""),
        "symbols": [
            _brief_symbol(item, file.get("path", ""), functions)
            for item in value.get("symbols", [])
        ],
        "relationships": [
            {key: row.get(key) for key in ("target_path", "relationship_type", "resolution_status")}
            for row in value.get("relationships", [])
        ],
        "dependants": [
            {key: row.get(key) for key in ("source_path", "relationship_type", "resolution_status")}
            for row in value.get("dependants", [])
        ],
        "semantic_state": value.get("semantic_state"),
        "provenance": _provenance(selected),
        "retained_legacy_claims": len(value.get("semantic_claims", [])),
        "contract_count": len(annotation.get("contracts", annotation.get("public_contracts", []))),
        "map_status": value.get("map_status"),
        "details_available": {
            "tool": "ANAXIGRAPH_FILE",
            "arguments": {"path": file.get("path"), "details": True},
        },
    }
    return small_agent_response(brief)


def _file_identity(file, overview):
    fields = ("path", "artifact_type", "language", "lines_of_code", "complexity", "raw_hash")
    return {
        **{key: file.get(key) for key in fields},
        "summary": overview,
        "entity_id": "module:" + str(file.get("path", "")),
    }


def _provenance(document):
    return {
        key: document.get(key)
        for key in (
            "id",
            "provider",
            "model",
            "executor_id",
            "executor_model",
            "created_at",
            "confidence",
        )
    }


def _brief_symbol(item, path, functions):
    kind = "function" if item.get("symbol_type") in CALLABLE_SYMBOL_KINDS else "type"
    return {
        "name": item["name"],
        "qualified_name": item["qualified_name"],
        "entity_id": f"{kind}:{path}#{item['qualified_name']}",
        "summary": sentence(functions.get(item["qualified_name"]) or item.get("summary", "")),
    }


def compact_search_response(value):
    result = {
        **value,
        "results": [
            {
                "path": item["path"],
                "entity_id": "module:" + item["path"],
                "summary": sentence(
                    (item.get("semantic") or {}).get("summary") or item.get("summary", "")
                ),
                **{
                    key: item[key]
                    for key in (
                        "artifact_type",
                        "language",
                        "score",
                        "lines_of_code",
                        "architecture_area",
                    )
                    if key in item
                },
            }
            for item in value.get("results", [])
        ],
        "graph_search": {
            "tool": "ANAXIGRAPH_GRAPH",
            "arguments": {"query": value["query"], "kind": ""},
        },
    }
    return small_agent_response(result)


def small_agent_response(value: dict[str, Any], *, limit: int = 8_000) -> dict[str, Any]:
    result = copy.deepcopy(value)
    omitted: dict[str, Any] = {}
    _project(result)
    _compact(result, "", omitted)
    result["response_budget"] = {
        "limit_bytes": limit,
        "details_argument": "details=true",
        "omitted_collections": omitted,
    }
    _sync_counts(result)
    while _size(result) > limit:
        lists = sorted(
            (item for item in _collections(result) if len(item[1]) > 1),
            key=lambda item: (item[0].count(".") + item[0].count("["), _size(item[1])),
            reverse=True,
        )
        if lists:
            path, items = lists[0]
            total = omitted.get(path, {}).get("total", len(items))
            del items[max(1, len(items) // 2) :]
            omitted[path] = {"total": total, "returned": len(items)}
            _sync_counts(result)
            continue
        if not _shorten(result):
            _minimal(result, limit)
            _sync_counts(result)
            break
    return result


def _compact(value: Any, path: str, omitted: dict[str, Any]) -> None:
    if isinstance(value, list):
        total = len(value)
        del value[5:]
        if total > len(value):
            omitted[path] = {"total": total, "returned": len(value)}
        for index, item in enumerate(value):
            if isinstance(item, str) and len(item) > 400:
                value[index] = item[:399] + "…"
            else:
                _compact(item, f"{path}[{index}]", omitted)
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and len(item) > 400 and key not in _IDENTITIES:
                value[key] = item[:399] + "…"
            else:
                _compact(item, f"{path}.{key}".lstrip("."), omitted)


def _collections(value: Any, path: str = "") -> list[tuple[str, list[Any]]]:
    if isinstance(value, list):
        return ([(path, value)] if value else []) + [
            pair
            for index, child in enumerate(value)
            for pair in _collections(child, f"{path}[{index}]")
        ]
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            if key != "response_budget"
            for item in _collections(child, f"{path}.{key}".lstrip("."))
        ]
    return []


def _shorten(value: dict[str, Any]) -> bool:
    candidates = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if isinstance(child, str) and len(child) > 100 and key not in _IDENTITIES:
                    candidates.append((len(child), item, key))
                elif key != "response_budget":
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    if not candidates:
        return False
    _, parent, key = max(candidates, key=lambda item: item[0])
    parent[key] = parent[key][:99] + "…"
    return True


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def _project(value: dict[str, Any]) -> None:
    fields = {
        "semantic": {
            "enabled",
            "state",
            "snapshot_id",
            "current",
            "eligible_modules",
            "pending",
            "failed",
            "analysis_freshness",
        },
        "architecture_charter": {
            "identity",
            "state",
            "snapshot_id",
            "purpose",
            "capabilities",
            "extension_points",
            "invariants",
            "confidence",
            "caveats",
        },
        "snapshot": {
            "id",
            "commit_sha",
            "branch",
            "dirty",
            "content_fingerprint",
            "analysis_timestamp",
        },
    }
    for key, keep in fields.items():
        if isinstance(value.get(key), dict):
            value[key] = {field: item for field, item in value[key].items() if field in keep}
    if "group_hierarchies" in value:
        value["group_hierarchies"] = {
            key: {"top_level_groups": len(items)}
            for key, items in value["group_hierarchies"].items()
        }
    for key in ("input_manifests", "generations"):
        if key in value:
            value[key] = {"total": len(value[key]), "details_required": True}
    _project_review(value)


def _project_review(value: dict[str, Any]) -> None:
    if isinstance(value.get("review"), dict):
        _project(value["review"])
    if "review_generation" in value:
        _project_functional_scopes(value)
        value["stages"] = [
            {key: stage.get(key) for key in ("key", "state", "document_id", "required_executor")}
            for stage in value.get("stages", [])
        ]
        if isinstance(value.get("telemetry"), dict):
            value["telemetry"] = {
                key: item for key, item in value["telemetry"].items() if key != "stages"
            }
        value["proposals"] = [
            {key: item.get(key) for key in ("key", "document_id", "provenance")}
            for item in value.get("proposals", [])
        ]
        for key in ("adjudication", "comparison", "strategy"):
            if isinstance(value.get(key), dict):
                value[key] = {
                    field: value[key][field]
                    for field in ("contract_version", "summary", "conclusion")
                    if field in value[key]
                }


def _project_functional_scopes(value: dict[str, Any]) -> None:
    brief = value.get("functional_brief")
    if isinstance(brief, dict):
        value["functional_brief"] = {
            key: brief[key] for key in ("contract_version", "purpose", "revision") if key in brief
        }
    if "scope_reviews" not in value:
        return
    value["scope_reviews"] = [
        {
            "scope_id": scope["scope_id"],
            "state": scope["state"],
            "alternative_count": scope["alternative_count"],
            "alternatives": [
                {"id": item["id"], "summary": item["design"]["summary"]}
                for item in scope["alternatives"]
            ],
            "details_available": True,
        }
        for scope in value["scope_reviews"]
    ]


def _minimal(value: dict[str, Any], limit: int) -> None:
    """Retain identity and the first recommendation if the full schema alone is too large."""
    keep = {
        "contract_version",
        "repository_id",
        "snapshot_id",
        "state",
        "identity",
        "goal",
        "review_goal",
        "review_generation",
        "ready",
        "stages",
        "review",
        "map_status",
        "baseline_snapshot",
        "target_snapshot",
        "baseline_selection",
        "agent_journey",
        "recommendations",
        "architectural_effects",
        "counts",
        "architecture_charter",
        "response_budget",
    }
    for key in list(value):
        if _size(value) <= limit:
            break
        if key not in keep:
            del value[key]
    value["response_budget"]["summary_only"] = True


def _sync_counts(value: dict[str, Any]) -> None:
    counts = value.get("counts")
    if isinstance(counts, dict) and "total" in counts and "architectural_effects" in value:
        counts["returned"] = len(value["architectural_effects"])
        counts["omitted"] = max(0, counts["total"] - counts["returned"])


def compact_finding(item: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in item.items()
        if key in {"id", "finding_type", "severity", "priority_score", "summary", "plain_language"}
    }
    result["summary"] = str(result.get("summary") or "")[:180]
    language = result.get("plain_language") or {}
    result["plain_language"] = {
        key: str(language[key])[:180] for key in ("version", "what", "why") if key in language
    }
    return result
