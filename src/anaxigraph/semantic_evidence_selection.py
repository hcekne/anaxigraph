"""Deterministic coverage and explicit size limits for architectural evidence packets."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from anaxigraph.pattern_evaluation_contract import PATTERN_SCORE_CONTRACT_VERSION

EVIDENCE_SELECTION_VERSION = "representative-evidence-v2"
REVIEW_PACKET_BYTES = 800_000
_COLLECTIONS = {
    "module_dossiers",
    "area_summaries",
    "pattern_reviews",
    "dependency_evidence",
    "areas",
    "subsystems",
}
_PRESERVED_FIELDS = {
    "scope",
    "path",
    "key",
    "kind",
    "responsibility_owner",
    "capability_brief",
    "external_constraints",
    "declared_context",
    "public_contracts",
    "invariants",
    "protected_behavior",
    "counter_evidence",
}
_IDENTITIES = {
    "contract",
    "schema_version",
    "protocol_version",
    "analysis_kind",
    "detailed_reviews",
    "max_output_tokens",
    "writing_contract_version",
    "writing_requirements",
    "input_manifest",
    "information_boundary",
    "review_goal",
    "understandability_policy",
}


def evidence_bytes(value: Any) -> int:
    """Include ASCII escaping and pretty-print overhead used by provider prompts."""
    return len(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True).encode("utf-8"))


def safe_review_evidence(value: dict[str, Any]) -> dict[str, Any]:
    """Keep legacy reviews for audit without presenting their advice as usable evidence."""
    evaluation = value.get("evaluation") or {}
    if evaluation.get("score_contract_version") == PATTERN_SCORE_CONTRACT_VERSION:
        return value
    return {
        "summary": "Legacy pattern scores predate failure-mode-aware validation. Refresh before acting.",
        "evaluation": {
            "pattern_key": evaluation.get("pattern_key"),
            "target_key": evaluation.get("target_key"),
            "recommendation": "insufficient_evidence",
        },
        "legacy_advice_withheld": True,
    }


def representative_items(
    items: list[dict[str, Any]],
    *,
    group: Callable[[dict[str, Any]], str],
    rank: Callable[[dict[str, Any]], Any],
    limit: int,
) -> list[dict[str, Any]]:
    buckets: dict[str, deque] = defaultdict(deque)
    for item in sorted(items, key=rank):
        buckets[group(item)].append(item)
    ordered = sorted(buckets, key=lambda key: (rank(buckets[key][0]), key))
    selected = []
    while ordered and len(selected) < limit:
        for key in ordered:
            selected.append(buckets[key].popleft())
            if len(selected) == limit:
                break
        ordered = [key for key in ordered if buckets[key]]
    return selected


def stable_order(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def module_role(path: str) -> str:
    parts = path.lower().split("/")
    if any(part in {"tests", "test", "__tests__"} for part in parts) or parts[-1].startswith(
        "test_"
    ):
        return "test"
    if any(part in {"docs", "documentation"} for part in parts) or parts[-1].endswith(
        (".md", ".rst", ".txt")
    ):
        return "documentation"
    return "production"


def responsibility_memberships(taxonomy: dict[str, Any]) -> dict[str, str]:
    return {
        str(member["path"]): f"{area['key']}/{subsystem['key']}"
        for area in taxonomy.get("areas") or []
        for subsystem in area.get("subsystems") or []
        for member in subsystem.get("members") or []
    }


def select_modules(
    rows: list[dict[str, Any]],
    inventory: dict[str, Any],
    relationships: dict[str, Any],
    memberships: dict[str, str],
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    def rank(item: dict[str, Any]) -> tuple:
        path = str(item["scope_key"])
        return (
            not item.get("reread"),
            -len(inventory.get(path, {}).get("public_interfaces") or []),
            -len(relationships.get(path) or []),
            stable_order(path),
        )

    def group(item: dict[str, Any]) -> str:
        return memberships.get(str(item["scope_key"]), "unmapped")

    result = []
    production, tests = int(limit * 0.7), int(limit * 0.15)
    for role, quota in (
        ("production", production),
        ("test", tests),
        ("documentation", limit - production - tests),
    ):
        pool = [item for item in rows if module_role(str(item["scope_key"])) == role]
        result.extend(representative_items(pool, group=group, rank=rank, limit=min(quota, limit)))
    selected = {item["scope_key"] for item in result}
    rest = [item for item in rows if item["scope_key"] not in selected]
    result.extend(
        representative_items(rest, group=group, rank=rank, limit=max(0, limit - len(result)))
    )
    return result[:limit]


def bounded_evidence(value: dict[str, Any], *, limit: int = REVIEW_PACKET_BYTES) -> dict[str, Any]:
    """Preserve identities and essential constraints before shortening supporting descriptions."""
    if evidence_bytes(value) <= limit:
        return value
    for text_limit, list_limit in ((600, 8), (300, 4), (300, 2), (300, 1), (120, 1), (60, 1)):
        counts = {"shortened_strings": 0, "omitted_list_entries": 0}
        result = {
            key: item if key in _IDENTITIES else _compact(item, text_limit, list_limit, counts, key)
            for key, item in value.items()
        }
        result["evidence_limits"] = {
            "policy": EVIDENCE_SELECTION_VERSION,
            "original_bytes": evidence_bytes(value),
            "maximum_bytes": limit,
            "text_characters": text_limit,
            "nested_list_entries": list_limit,
            **counts,
            "caveat": "This is selected evidence, not exhaustive coverage. Missing evidence cannot justify a rewrite.",
        }
        if evidence_bytes(result) <= limit:
            return result
    raise ValueError(
        "Review identity metadata or essential constraints exceed the evidence budget; "
        "narrow the requested evidence"
    )


def _compact(
    value: Any, text_limit: int, list_limit: int, counts: dict[str, int], key: str = ""
) -> Any:
    if key in _PRESERVED_FIELDS:
        return value
    if isinstance(value, str) and len(value) > text_limit:
        counts["shortened_strings"] += 1
        return value[:text_limit] + "… [shortened]"
    if isinstance(value, list):
        selected = value if key in _COLLECTIONS else value[:list_limit]
        counts["omitted_list_entries"] += len(value) - len(selected)
        return [_compact(item, text_limit, list_limit, counts) for item in selected]
    if isinstance(value, dict):
        return {
            name: _compact(item, text_limit, list_limit, counts, name)
            for name, item in value.items()
        }
    return value
