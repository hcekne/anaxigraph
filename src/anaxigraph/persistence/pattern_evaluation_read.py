"""Read the current independently reviewed pattern evaluations."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.pattern_evaluation_contract import score_values
from anaxigraph.pattern_query import PATTERN_QUERY_VERSION, PatternEvaluationQuery

_CURRENT_EVALUATIONS_SQL = """
SELECT ss.scope_key, ss.artifact_id, a.canonical_path,
       sd.value_json, sd.provider, sd.model, sd.executor_id, sd.executor_model,
       sd.prompt_version, sd.schema_version, sd.confidence, sd.input_tokens,
       sd.output_tokens, sd.estimated_cost_usd, sd.actual_cost_usd, sd.created_at,
       (
           SELECT sj.metadata_json FROM semantic_jobs sj
           WHERE sj.repository_id = ss.repository_id
             AND sj.scope_type = 'pattern' AND sj.scope_key = ss.scope_key
             AND sj.job_kind = 'pattern_assessment'
             AND sj.input_hash = ss.intrinsic_input_hash
           ORDER BY sj.id DESC LIMIT 1
       ) AS assessment_metadata_json
FROM semantic_scope_states ss
JOIN semantic_documents sd ON sd.id = ss.context_document_id
LEFT JOIN artifacts a ON a.id = ss.artifact_id
WHERE ss.repository_id = ? AND ss.snapshot_id = ?
  AND ss.scope_type = 'pattern' AND ss.status = 'current'
  AND sd.document_kind = 'pattern_review'
ORDER BY ss.scope_key
"""
_TEXT_LIMIT = 2_000
_LIST_LIMIT = 100


def read_pattern_evaluations(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    query: PatternEvaluationQuery,
) -> dict[str, Any]:
    rows = connection.execute(_CURRENT_EVALUATIONS_SQL, (repository_id, snapshot_id)).fetchall()
    cards = {card.stable_key: card for card in bundled_pattern_catalog().cards}
    items = []
    for row in rows:
        item = _evaluation_item(dict(row), cards, query.include_evidence)
        if item is not None and _matches(item, query):
            items.append(item)
    items.sort(key=lambda item: _sort_key(item, query.sort_by))
    total = len(items)
    page = items[query.offset : query.offset + query.limit]
    next_offset = query.offset + len(page)
    return {
        "contract_version": PATTERN_QUERY_VERSION,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "filters": query.filters(),
        "total": total,
        "returned": len(page),
        "offset": query.offset,
        "next_offset": next_offset if next_offset < total else None,
        "omitted": max(0, total - len(page)),
        "items": page,
    }


def empty_pattern_evaluations(repository_id: int, query: PatternEvaluationQuery) -> dict[str, Any]:
    return {
        "contract_version": PATTERN_QUERY_VERSION,
        "repository_id": repository_id,
        "snapshot_id": None,
        "filters": query.filters(),
        "total": 0,
        "returned": 0,
        "offset": query.offset,
        "next_offset": None,
        "omitted": 0,
        "items": [],
    }


def _evaluation_item(
    row: dict[str, Any], cards: dict[str, Any], include_evidence: bool
) -> dict[str, Any] | None:
    review = _object(row.get("value_json"))
    evaluation = review.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    pattern_key = str(evaluation.get("pattern_key") or "")
    card = cards.get(pattern_key)
    metadata = _object(row.get("assessment_metadata_json"))
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    if candidate.get("input_fingerprint") != evaluation.get("candidate_fingerprint"):
        candidate = {}
    item = {
        "target": _target(evaluation, candidate, row),
        "pattern": _pattern(pattern_key, card),
        "candidate": _candidate_summary(candidate),
        "presence": str(evaluation.get("presence") or "uncertain"),
        "recommendation": str(evaluation.get("recommendation") or "insufficient_evidence"),
        "summary": _text(evaluation.get("summary")),
        "rationale": _text(evaluation.get("rationale")),
        "scores": score_values(evaluation),
        "evidence_count": len(evaluation.get("evidence") or []),
        "counter_evidence_count": len(evaluation.get("counter_evidence") or []),
        "review": _review_summary(review),
        "provenance": _provenance(row),
    }
    if include_evidence:
        item["details"] = _details(evaluation, review)
    return item


def _target(
    evaluation: dict[str, Any], candidate: dict[str, Any], row: dict[str, Any]
) -> dict[str, Any]:
    target = candidate.get("target") if isinstance(candidate.get("target"), dict) else {}
    key = str(evaluation.get("target_key") or target.get("key") or "")
    level = str(target.get("level") or key.partition(":")[0])
    path = str(target.get("path") or row.get("canonical_path") or "")
    label = str(target.get("label") or path.rsplit("/", 1)[-1] or key)
    return {
        "key": key,
        "level": level,
        "label": label,
        "parent_key": target.get("parent_key"),
        "path": path,
        "qualified_name": str(target.get("qualified_name") or ""),
        "symbol_kind": str(target.get("symbol_kind") or ""),
    }


def _pattern(pattern_key: str, card: Any | None) -> dict[str, Any]:
    return {
        "key": pattern_key,
        "name": str(card.name if card else pattern_key),
        "family": str(card.family if card else ""),
        "kind": str(card.kind if card else ""),
        "version": int(card.version if card else 0),
    }


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "priority": int(candidate.get("priority") or 0),
        "selection_reasons": _strings(candidate.get("selection_reasons")),
        "missing_evidence": _strings(candidate.get("missing_evidence")),
        "capability_gaps": _strings(candidate.get("capability_gaps")),
    }


def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
    issues = review.get("issues") if isinstance(review.get("issues"), list) else []
    severities = Counter(
        str(issue.get("severity") or "unknown") for issue in issues if isinstance(issue, dict)
    )
    return {
        "verdict": str(review.get("verdict") or ""),
        "summary": _text(review.get("summary")),
        "confidence": int(review.get("confidence") or 0),
        "issue_counts": dict(sorted(severities.items())),
        "competing_interpretation_count": len(review.get("competing_interpretations") or []),
    }


def _provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": str(row.get("provider") or ""),
        "model": str(row.get("model") or ""),
        "executor_id": str(row.get("executor_id") or ""),
        "executor_model": str(row.get("executor_model") or ""),
        "prompt_version": str(row.get("prompt_version") or ""),
        "schema_version": str(row.get("schema_version") or ""),
        "confidence": float(row.get("confidence") or 0),
        "input_tokens": int(row.get("input_tokens") or 0),
        "output_tokens": int(row.get("output_tokens") or 0),
        "estimated_cost_usd": row.get("estimated_cost_usd"),
        "actual_cost_usd": row.get("actual_cost_usd"),
        "created_at": str(row.get("created_at") or ""),
    }


def _details(evaluation: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    score_rationales = {
        name: {
            "rationale": _text(value.get("rationale")),
            "evidence": _strings(value.get("evidence")),
        }
        for name, value in (evaluation.get("scores") or {}).items()
        if isinstance(value, dict)
    }
    return {
        "score_rationales": score_rationales,
        **{
            key: _strings(evaluation.get(key))
            for key in (
                "evidence",
                "counter_evidence",
                "affected_targets",
                "local_precedents",
                "alternatives",
                "prerequisites",
                "risks",
                "invariants",
                "invalidation_conditions",
            )
        },
        "review_issues": _bounded_objects(review.get("issues")),
        "competing_interpretations": _bounded_objects(review.get("competing_interpretations")),
        "review_evidence": _strings(review.get("evidence")),
    }


def _matches(item: dict[str, Any], query: PatternEvaluationQuery) -> bool:
    target = item["target"]
    target_match = not query.target or query.target in {
        target["key"],
        target["path"],
        target["qualified_name"],
    }
    return bool(
        target_match
        and (not query.pattern or item["pattern"]["key"] == query.pattern)
        and (not query.level or target["level"] == query.level)
        and (not query.recommendation or item["recommendation"] == query.recommendation)
        and (not query.presence or item["presence"] == query.presence)
        and item["scores"][query.sort_by] >= query.minimum_score
    )


def _sort_key(item: dict[str, Any], score: str) -> tuple[int, str, str]:
    return (-int(item["scores"][score]), item["target"]["key"], item["pattern"]["key"])


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text(value: Any) -> str:
    return str(value or "")[:_TEXT_LIMIT]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item) for item in value[:_LIST_LIMIT]]


def _bounded_objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:_LIST_LIMIT]:
        if isinstance(item, dict):
            result.append({str(key): _bounded_value(nested) for key, nested in item.items()})
    return result


def _bounded_value(value: Any) -> Any:
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        return [_bounded_value(item) for item in value[:_LIST_LIMIT]]
    return value
