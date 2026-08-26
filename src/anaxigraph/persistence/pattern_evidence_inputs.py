"""Decode persisted analyzer and semantic inputs for evidence projection."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from anaxigraph.analyzer_capabilities import capabilities_from_dict

_LEVEL_CONFIDENCE = {
    "unavailable": 0.0,
    "heuristic": 0.45,
    "lexical": 0.65,
    "structural": 0.85,
    "deep": 1.0,
}


def capability(raw: dict[str, Any]) -> dict[str, Any] | None:
    metadata = json.loads(raw["metadata_json"] or "{}")
    declaration = capabilities_from_dict((metadata.get("ir") or {}).get("analyzer_capabilities"))
    return declaration.as_dict() if declaration else None


def capability_confidence(value: dict[str, Any] | None, fact: str) -> float:
    if value is None:
        return 0.0
    levels = {item["fact"]: item["level"] for item in value.get("facts") or []}
    return _LEVEL_CONFIDENCE[levels.get(fact, "unavailable")]


def capability_contracts(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        value = capability(row)
        if value:
            result[str(value["fingerprint"])] = value
    return result


def facts_by_artifact(rows: Iterable[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        result[int(row["artifact_id"])] = list(
            (metadata.get("ir") or {}).get("evidence_facts") or []
        )
    return result


def parse_status(raw: dict[str, Any]) -> str:
    metadata = json.loads(raw["metadata_json"] or "{}")
    return str((metadata.get("ir") or {}).get("parse_status") or raw["analysis_status"])


def semantic_documents(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    scope_key: str = "",
) -> dict[str, dict[str, Any]]:
    sql = """
        SELECT ss.scope_key, sd.id AS document_id, sd.value_json, sd.confidence
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
          AND ss.status IN ('current', 'intrinsic_current') AND sd.id IS NOT NULL
        """
    parameters: tuple[Any, ...] = (snapshot_id,)
    if scope_key:
        sql += " AND ss.scope_key = ?"
        parameters = (*parameters, scope_key)
    rows = connection.execute(sql, parameters).fetchall()
    result = {}
    for row in rows:
        value = json.loads(row["value_json"] or "{}")
        value["_confidence"] = float(row["confidence"] or 0)
        value["_document_id"] = int(row["document_id"])
        result[str(row["scope_key"])] = value
    return result
