"""Shared relationship-resolution provenance and quality summaries."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

RESOLVED_INTERNAL = "resolved_internal"
AMBIGUOUS_INTERNAL = "ambiguous_internal"
UNRESOLVED_INTERNAL = "unresolved_internal"
EXTERNAL = "external"

RESOLUTION_STATUSES = frozenset(
    {RESOLVED_INTERNAL, AMBIGUOUS_INTERNAL, UNRESOLVED_INTERNAL, EXTERNAL}
)


def relationship_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    """Decode relationship metadata while remaining compatible with older indexes."""

    raw = row.get("metadata_json", "{}")
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def resolution_status(row: Mapping[str, Any]) -> str:
    """Return explicit provenance, inferring a safe legacy value when necessary."""

    status = relationship_metadata(row).get("resolution_status")
    if status in RESOLUTION_STATUSES:
        return str(status)
    return RESOLVED_INTERNAL if row.get("target_artifact_id") is not None else EXTERNAL


def relationship_quality(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize how many references AnaxiGraph could resolve without hiding misses."""

    materialized = list(rows)
    counts = Counter(resolution_status(row) for row in materialized)
    internal_references = (
        counts[RESOLVED_INTERNAL]
        + counts[AMBIGUOUS_INTERNAL]
        + counts[UNRESOLVED_INTERNAL]
    )
    resolution_rate = (
        counts[RESOLVED_INTERNAL] / internal_references if internal_references else None
    )
    unresolved = counts[AMBIGUOUS_INTERNAL] + counts[UNRESOLVED_INTERNAL]
    status = (
        "unavailable"
        if not internal_references
        else "complete"
        if unresolved == 0
        else "partial"
    )
    return {
        "status": status,
        "resolution_rate": resolution_rate,
        "total_relationships": len(materialized),
        "internal_references": internal_references,
        "resolved_internal": counts[RESOLVED_INTERNAL],
        "ambiguous_internal": counts[AMBIGUOUS_INTERNAL],
        "unresolved_internal": counts[UNRESOLVED_INTERNAL],
        "external": counts[EXTERNAL],
        "caveat": (
            "Resolution measures extracted references only; dynamic runtime wiring can still be absent."
        ),
    }
