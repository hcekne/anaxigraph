"""Contextual catalogue ratings and reference-based independent review contracts."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

CATALOGUE_SCORE_VERSION = "pattern-scores-v3"
CATALOGUE_REVIEW_VERSION = "pattern-review-v2"
CATALOGUE_SELECTION_VERSION = "whole-catalogue-v1"
CATALOGUE_TEXTS = {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}
_PLACEMENT = {
    "type": "object",
    "properties": {
        "target_key": {"type": "string", "minLength": 1},
        "reason": {"type": "string", "minLength": 1},
        "evidence": CATALOGUE_TEXTS,
        "pros": CATALOGUE_TEXTS,
        "cons": CATALOGUE_TEXTS,
    },
    "required": ["target_key", "reason", "evidence", "pros", "cons"],
    "additionalProperties": False,
}


def is_catalogue_request(request: dict[str, Any]) -> bool:
    candidate = request.get("candidate") or {}
    return "catalogue_coverage" in (candidate.get("selection_reasons") or [])


def catalogue_schema(schema: dict[str, Any], *, review: bool) -> dict[str, Any]:
    result = copy.deepcopy(schema)
    evaluation = result["properties"]["evaluation"] if review else result
    evaluation["properties"].update(
        pros=copy.deepcopy(CATALOGUE_TEXTS),
        cons=copy.deepcopy(CATALOGUE_TEXTS),
        placements={"type": "array", "items": copy.deepcopy(_PLACEMENT)},
    )
    evaluation["required"].extend(["pros", "cons", "placements"])
    evaluation["properties"]["score_contract_version"] = {
        "type": "string",
        "enum": [CATALOGUE_SCORE_VERSION],
    }
    if review:
        evaluation["type"] = ["object", "null"]
        result["properties"]["assessment_fingerprint"] = {"type": "string"}
        result["properties"]["assessment_input_hash"] = {"type": "string"}
        result["required"].extend(["assessment_fingerprint", "assessment_input_hash"])
        result["properties"]["review_contract_version"] = {
            "type": "string",
            "enum": [CATALOGUE_REVIEW_VERSION],
        }
    return result


def validate_catalogue_value(value, request, schema, *, review, validate):
    validate(value, schema, "catalogue_review" if review else "catalogue_assessment")
    evaluation = value.get("evaluation") if review else value
    if review:
        expected = assessment_fingerprint(request.get("assessment") or {})
        if value["assessment_fingerprint"] != expected:
            raise ValueError("pattern review assessment_fingerprint does not match its assessment")
        if value["assessment_input_hash"] != request.get("assessment_input_hash"):
            raise ValueError("pattern review assessment_input_hash does not match its assessment")
        if evaluation is None and value["verdict"] != "approve":
            raise ValueError(
                "a revised or competing evaluation must supply the corrected assessment"
            )
    evaluation = evaluation or request.get("assessment")
    if not isinstance(evaluation, dict):
        raise ValueError("catalogue evaluation requires its canonical assessment")
    target = schema["properties"]["evaluation"] if review else schema
    validate(evaluation, {**target, "type": "object"}, "catalogue_evaluation")
    if evaluation["score_contract_version"] != CATALOGUE_SCORE_VERSION:
        raise ValueError("unsupported catalogue score contract version")
    if review and value["review_contract_version"] != CATALOGUE_REVIEW_VERSION:
        raise ValueError("unsupported catalogue review contract version")
    return evaluation


def resolved_evaluation(review: dict, assessment: dict | None = None) -> dict:
    value = review.get("evaluation")
    if isinstance(value, dict):
        return value
    if assessment and review.get("assessment_fingerprint") == assessment_fingerprint(assessment):
        return assessment
    return {}


def assessment_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
