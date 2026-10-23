"""Resolve a review's immutable assessment reference, including historical revisions."""

from __future__ import annotations

import json

from anaxigraph.pattern_catalogue_contract import resolved_evaluation


def expanded_pattern_review(connection, document: dict) -> dict:
    value = document.get("value") or json.loads(document.get("value_json") or "{}")
    if isinstance(value.get("evaluation"), dict):
        return value
    reference = value.get("assessment_input_hash")
    if not reference:
        return value
    rows = connection.execute(
        """SELECT value_json FROM semantic_document_values WHERE repository_id = ?
        AND scope_type = 'pattern' AND scope_key = ? AND document_kind = 'pattern_assessment'
        AND input_hash = ? ORDER BY id DESC""",
        (document["repository_id"], document["scope_key"], reference),
    ).fetchall()
    for row in rows:
        evaluation = resolved_evaluation(value, json.loads(row["value_json"]))
        if evaluation:
            return {**value, "evaluation": evaluation}
    return {**value, "assessment_unavailable": True}
