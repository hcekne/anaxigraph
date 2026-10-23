"""Current and incomplete catalogue coverage, independent of display pagination."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_catalogue_contract import resolved_evaluation
from anaxigraph.pattern_catalogue_query import PatternCatalogueQuery
from anaxigraph.pattern_evaluation_contract import PATTERN_SCORE_DIMENSIONS
from anaxigraph.persistence.pattern_manifest import read_pattern_manifest

_STATES = """SELECT ss.scope_key, ss.status, a.value_json AS assessment_json,
r.value_json AS review_json, COALESCE(r.model, a.model) AS model,
COALESCE(r.executor_model, a.executor_model) AS executor_model,
COALESCE(r.created_at, a.created_at) AS created_at
FROM semantic_scope_states ss
LEFT JOIN semantic_document_values a ON a.id = ss.intrinsic_document_id
LEFT JOIN semantic_document_values r ON r.id = ss.context_document_id
WHERE ss.repository_id = ? AND ss.snapshot_id = ? AND ss.scope_type = 'pattern'
ORDER BY CASE ss.status WHEN 'current' THEN 0 ELSE 1 END, ss.scope_key"""


def read_pattern_catalogue(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int | None,
    query: PatternCatalogueQuery,
) -> dict[str, Any]:
    catalog = bundled_pattern_catalog()
    manifest = (
        read_pattern_manifest(connection, repository_id, snapshot_id) if snapshot_id else None
    )
    cards = manifest["cards"] if manifest else [card.as_dict() for card in catalog.cards]
    expected = manifest["expected_ids"] if manifest else [card["stable_key"] for card in cards]
    rows = (
        connection.execute(_STATES, (repository_id, snapshot_id)).fetchall() if snapshot_id else []
    )
    records = {}
    for row in rows:
        key = str(row["scope_key"]).rpartition("|pattern:")[2]
        records.setdefault(key, {**dict(row), "pair_count": 0})["pair_count"] += 1
    all_items = [_catalogue_item(card, records.get(card["stable_key"])) for card in cards]
    # Saved coverage belongs to its immutable run manifest. Only an unplanned catalogue
    # needs the current cards serialized and hashed here.
    fingerprint = manifest["catalogue_fingerprint"] if manifest else catalog.fingerprint
    coverage = _coverage(expected, all_items, records, manifest, fingerprint)
    if not query.include_manifest:
        for key in ("expected_ids", "missing_ids", "unreviewed_ids"):
            coverage.pop(key)
    items = [item for item in all_items if _matches(item, query)]
    items.sort(key=lambda item: _sort_key(item, query.sort_by))
    page = items[query.offset : query.offset + query.limit]
    next_offset = query.offset + len(page)
    return {
        "contract_version": "pattern-catalogue-query-v1",
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "catalogue": coverage,
        "total": len(items),
        "returned": len(page),
        "offset": query.offset,
        "next_offset": next_offset if next_offset < len(items) else None,
        "filters": query.filters(),
        "families": sorted({item["pattern"]["family"] for item in all_items}),
        "items": page,
    }


def _catalogue_item(card, record):
    assessment = _object(record.get("assessment_json")) if record else {}
    review = _object(record.get("review_json")) if record else {}
    final = resolved_evaluation(review, assessment)
    evaluation = final or assessment
    rated = evaluation.get("pattern_key") == card["stable_key"] and _rated(evaluation)
    reviewed = bool(record and record["status"] == "current" and final and rated)
    unresolved = bool(rated and evaluation.get("recommendation") == "insufficient_evidence")
    state = _state(bool(record), rated, reviewed, unresolved)
    return {
        "pattern": {
            "key": card["stable_key"],
            **{key: card[key] for key in ("name", "family", "kind", "intent", "version")},
        },
        "state": state,
        "considered": bool(record),
        "rated": rated,
        "reviewed": reviewed,
        "unresolved": unresolved,
        "summary": evaluation.get("summary", ""),
        "presence": evaluation.get("presence"),
        "recommendation": evaluation.get("recommendation"),
        "scores": {key: value["value"] for key, value in evaluation["scores"].items()}
        if rated
        else None,
        "pros": evaluation.get("pros", []),
        "cons": evaluation.get("cons", []),
        "placements": evaluation.get("placements", []),
        "provenance": {key: record.get(key) for key in ("model", "executor_model", "created_at")}
        if record
        else None,
    }


def _rated(evaluation):
    scores = evaluation.get("scores") or {}
    return all(
        isinstance(scores.get(key), dict) and isinstance(scores[key].get("value"), int)
        for key in PATTERN_SCORE_DIMENSIONS
    )


def _state(considered, rated, reviewed, unresolved):
    if unresolved:
        return "unresolved"
    if reviewed:
        return "reviewed"
    if rated:
        return "rated"
    return "considered" if considered else "missing"


def _coverage(expected, items, records, manifest, fingerprint):
    expected_set = set(expected)
    sets = {
        field: {item["pattern"]["key"] for item in items if item[field]}
        for field in ("considered", "rated", "reviewed", "unresolved")
    }
    missing = expected_set - sets["rated"]
    unexpected = sorted(set(records) - expected_set)
    duplicates = sorted(key for key, row in records.items() if manifest and row["pair_count"] > 1)
    complete = bool(
        manifest and expected_set <= sets["reviewed"] and not unexpected and not duplicates
    )
    return {
        "fingerprint": manifest["catalogue_fingerprint"] if manifest else fingerprint,
        "manifest_saved": bool(manifest),
        "manifest_available": True,
        "expected_ids": expected,
        "expected": len(expected_set),
        **{key: len(value & expected_set) for key, value in sets.items()},
        "missing": len(missing),
        "not_considered": len(expected_set - sets["considered"]),
        "pending_review": len(expected_set - sets["reviewed"]),
        "missing_ids": sorted(missing),
        "unreviewed_ids": sorted(expected_set - sets["reviewed"]),
        "unexpected_ids": unexpected,
        "duplicate_ids": duplicates,
        "assessment_pairs": sum(row["pair_count"] for row in records.values()),
        "complete": complete,
        "fully_supported": complete and not sets["unresolved"],
    }


def _matches(item, query):
    return (
        (not query.pattern or item["pattern"]["key"] == query.pattern)
        and (not query.family or item["pattern"]["family"] == query.family)
        and (not query.state or item["state"] == query.state)
    )


def _sort_key(item, key):
    score = (item.get("scores") or {}).get(key)
    return (
        (-(score if score is not None else -1), item["pattern"]["key"])
        if key != "pattern"
        else (0, item["pattern"]["key"])
    )


def _object(value) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
