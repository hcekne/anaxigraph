"""Bound agent journey summaries while making omitted detail explicit."""

from __future__ import annotations

import copy
import json
from typing import Any


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
            if (
                isinstance(item, str)
                and len(item) > 400
                and key not in {"path", "checkout_path", "repository_path"}
            ):
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
                if (
                    isinstance(child, str)
                    and len(child) > 100
                    and key not in {"path", "checkout_path", "repository_path"}
                ):
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
