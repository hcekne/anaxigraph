"""Bounded, lossless finding queries for humans and coding agents."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from anaxigraph.persistence.finding_read import (  # noqa: F401
    PRIORITY_VERSION,
    finding_sort_key,
    read_finding,
    read_findings,
    read_ranked_findings,
)

_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}
_STATUSES = {
    "new",
    "acknowledged",
    "accepted",
    "dismissed",
    "planned",
    "resolved",
    "regressed",
}


@dataclass(frozen=True, slots=True)
class FindingPageQuery:
    """One stable page over either the attention queue or complete diagnostics."""

    view: str = "attention"
    cursor: str = ""
    page_size: int | None = None
    statuses: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    finding_types: tuple[str, ...] = ()
    module: str = ""
    architecture_area: str = ""
    minimum_confidence: float = 0.0
    payload_budget_bytes: int | None = None
    compact: bool = False


def read_finding_page(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int | None,
    *,
    query: FindingPageQuery,
    policy: Any,
) -> dict[str, Any]:
    page_size = _validate(query, policy)
    ranked = read_ranked_findings(connection, repository_id, snapshot_id)
    view_items = [item for item in ranked if _in_view(item, query.view, policy)]
    available = _available_filters(view_items)
    matching = [item for item in view_items if _matches(item, query)]
    matching.sort(key=finding_sort_key)
    signature = _query_signature(repository_id, snapshot_id, query, policy)
    start = _cursor_start(matching, query.cursor, signature)
    candidate_items = matching[start : start + page_size]
    groups = _diagnostic_groups(matching) if query.view == "diagnostics" else []
    counts = _counts(matching)
    selected = [_compact(item) if query.compact else item for item in candidate_items]
    selected = _fit_budget(
        selected,
        matching=matching,
        start=start,
        page_size=page_size,
        signature=signature,
        query=query,
        counts=counts,
        available=available,
        groups=groups,
        policy=policy,
    )
    return _page_payload(
        selected,
        matching=matching,
        start=start,
        page_size=page_size,
        signature=signature,
        query=query,
        counts=counts,
        available=available,
        groups=groups,
        policy=policy,
    )


def _validate(query: FindingPageQuery, policy: Any) -> int:
    if query.view not in {"attention", "diagnostics"}:
        raise ValueError("finding view must be attention or diagnostics")
    unknown_statuses = set(query.statuses) - _STATUSES
    if unknown_statuses:
        raise ValueError(f"unsupported finding status: {sorted(unknown_statuses)[0]}")
    unknown_severities = set(query.severities) - set(_SEVERITY_RANK)
    if unknown_severities:
        raise ValueError(f"unsupported finding severity: {sorted(unknown_severities)[0]}")
    if not 0 <= query.minimum_confidence <= 1:
        raise ValueError("minimum confidence must be between 0 and 1")
    default = (
        policy.attention_page_size if query.view == "attention" else policy.diagnostics_page_size
    )
    page_size = default if query.page_size is None else int(query.page_size)
    if not 1 <= page_size <= 200:
        raise ValueError("finding page size must be between 1 and 200")
    if query.payload_budget_bytes is not None and query.payload_budget_bytes < 2_000:
        raise ValueError("finding payload budget must be at least 2000 bytes")
    return page_size


def _in_view(item: dict[str, Any], view: str, policy: Any) -> bool:
    if view == "diagnostics":
        return True
    status = str(item.get("status") or "new")
    if status not in {"new", "acknowledged", "planned", "regressed"}:
        return False
    if status in {"planned", "regressed"}:
        return True
    if (
        item.get("finding_type") == "long_function"
        and item.get("severity") == "info"
        and not policy.include_info_long_functions
    ):
        return False
    severity = _SEVERITY_RANK.get(str(item.get("severity") or "info"), 0)
    threshold = _SEVERITY_RANK[policy.attention_minimum_severity]
    return severity >= threshold or int(item.get("priority_score") or 0) >= int(
        policy.attention_minimum_priority
    )


def _matches(item: dict[str, Any], query: FindingPageQuery) -> bool:
    if query.statuses and item.get("status") not in query.statuses:
        return False
    if query.severities and item.get("severity") not in query.severities:
        return False
    if query.finding_types and item.get("finding_type") not in query.finding_types:
        return False
    if float(item.get("confidence") or 0) < query.minimum_confidence:
        return False
    if query.module:
        needle = query.module.casefold()
        if not any(needle in str(path).casefold() for path in item.get("affected_artifacts") or ()):
            return False
    if query.architecture_area and query.architecture_area not in _areas(item):
        return False
    return True


def _available_filters(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "statuses": sorted({str(item.get("status")) for item in items}),
        "severities": sorted(
            {str(item.get("severity")) for item in items},
            key=lambda value: -_SEVERITY_RANK.get(value, -1),
        ),
        "finding_types": sorted({str(item.get("finding_type")) for item in items}),
        "architecture_areas": sorted({area for item in items for area in _areas(item)}),
    }


def _counts(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    return {
        "severity": dict(sorted(Counter(str(item["severity"]) for item in items).items())),
        "type": dict(sorted(Counter(str(item["finding_type"]) for item in items).items())),
        "status": dict(sorted(Counter(str(item["status"]) for item in items).items())),
    }


def _diagnostic_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        areas = _areas(item)
        grouped[(str(item["finding_type"]), areas[0] if areas else "ungrouped")].append(item)
    result = []
    for (finding_type, area), values in grouped.items():
        if len(values) < 2:
            continue
        result.append(
            {
                "finding_type": finding_type,
                "architecture_area": area,
                "count": len(values),
                "highest_priority": max(int(item["priority_score"]) for item in values),
                "severities": dict(
                    sorted(Counter(str(item["severity"]) for item in values).items())
                ),
                "sample_finding_ids": [int(item["id"]) for item in values[:3]],
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -int(item["highest_priority"]),
            -int(item["count"]),
            item["finding_type"],
        ),
    )


def _areas(item: dict[str, Any]) -> list[str]:
    affected = item.get("actionability", {}).get("affected", {})
    return [str(value) for value in affected.get("architecture_areas") or ("ungrouped",)]


def _query_signature(
    repository_id: int,
    snapshot_id: int | None,
    query: FindingPageQuery,
    policy: Any,
) -> str:
    value = {
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "view": query.view,
        "statuses": query.statuses,
        "severities": query.severities,
        "finding_types": query.finding_types,
        "module": query.module,
        "architecture_area": query.architecture_area,
        "minimum_confidence": query.minimum_confidence,
        "minimum_priority": policy.attention_minimum_priority,
        "minimum_severity": policy.attention_minimum_severity,
        "include_info_long_functions": policy.include_info_long_functions,
        "priority_version": PRIORITY_VERSION,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def _cursor_start(items: list[dict[str, Any]], cursor: str, signature: str) -> int:
    if not cursor:
        return 0
    payload = _decode_cursor(cursor)
    if payload.get("v") != 1 or payload.get("q") != signature:
        raise ValueError("finding cursor does not match this query")
    raw_key = payload.get("after")
    if not isinstance(raw_key, list) or len(raw_key) != 4:
        raise ValueError("invalid finding cursor")
    after = (int(raw_key[0]), int(raw_key[1]), str(raw_key[2]), str(raw_key[3]))
    return next(
        (index for index, item in enumerate(items) if finding_sort_key(item) > after),
        len(items),
    )


def _encode_cursor(item: dict[str, Any], signature: str) -> str:
    payload = {"v": 1, "q": signature, "after": finding_sort_key(item)}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("invalid finding cursor") from exc
    if not isinstance(value, dict):
        raise ValueError("invalid finding cursor")
    return value


def _compact(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "stable_key",
        "finding_type",
        "severity",
        "confidence",
        "summary",
        "status",
        "affected_artifacts",
        "recommended_action",
        "priority_score",
        "priority_label",
        "priority_reasons",
        "priority_version",
        "actionability",
        "plain_language",
    )
    return {key: item[key] for key in keys if key in item}


def _fit_budget(
    selected: list[dict[str, Any]],
    **context: Any,
) -> list[dict[str, Any]]:
    budget = context["query"].payload_budget_bytes
    if budget is None:
        return selected
    while selected:
        payload = _page_payload(selected, **context)
        if _encoded_size(payload) <= budget:
            return selected
        selected.pop()
    if context["start"] < len(context["matching"]):
        raise ValueError("finding payload budget is too small for one result")
    return selected


def _page_payload(
    selected: list[dict[str, Any]],
    *,
    matching: list[dict[str, Any]],
    start: int,
    page_size: int,
    signature: str,
    query: FindingPageQuery,
    counts: dict[str, dict[str, int]],
    available: dict[str, list[str]],
    groups: list[dict[str, Any]],
    policy: Any,
) -> dict[str, Any]:
    shown = len(selected)
    remaining, page_capacity, next_cursor = _page_position(
        matching, start, shown, page_size, signature
    )
    visible_groups = groups[:20] if query.compact else groups
    payload = {
        "view": query.view,
        "items": selected,
        "shown": shown,
        "page_size": page_size,
        "total_matching": len(matching),
        "total_by_severity": counts["severity"],
        "total_by_type": counts["type"],
        "total_by_status": counts["status"],
        "groups": visible_groups,
        "filters": _filter_payload(query, policy),
        "available_filters": available,
        "priority_version": PRIORITY_VERSION,
        "next_cursor": next_cursor,
        "omitted": {
            "before_cursor": start,
            "after_page": remaining,
            "due_to_payload_budget": max(0, page_capacity - shown),
            "diagnostic_groups": len(groups) - len(visible_groups),
        },
        "payload_budget": {
            "limit_bytes": query.payload_budget_bytes,
            "estimated_bytes": 0,
            "estimated_tokens": 0,
            "truncated": shown < page_capacity,
        },
    }
    size = _encoded_size(payload)
    payload["payload_budget"]["estimated_bytes"] = size
    payload["payload_budget"]["estimated_tokens"] = (size + 3) // 4
    return payload


def _page_position(
    matching: list[dict[str, Any]],
    start: int,
    shown: int,
    page_size: int,
    signature: str,
) -> tuple[int, int, str | None]:
    remaining = max(0, len(matching) - start - shown)
    capacity = min(page_size, max(0, len(matching) - start))
    cursor = _encode_cursor(matching[start + shown - 1], signature) if remaining and shown else None
    return remaining, capacity, cursor


def _filter_payload(query: FindingPageQuery, policy: Any) -> dict[str, Any]:
    return {
        "statuses": list(query.statuses),
        "severities": list(query.severities),
        "finding_types": list(query.finding_types),
        "module": query.module,
        "architecture_area": query.architecture_area,
        "minimum_confidence": query.minimum_confidence,
        "attention_minimum_priority": policy.attention_minimum_priority,
        "attention_minimum_severity": policy.attention_minimum_severity,
        "include_info_long_functions": policy.include_info_long_functions,
    }


def _encoded_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
