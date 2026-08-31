"""Strict assessment and independent-critique contracts for pattern candidates."""

from __future__ import annotations

import copy
from typing import Any

from anaxigraph.semantic_contract import SemanticResult, _validate_schema

PATTERN_SCORE_CONTRACT_VERSION = "pattern-scores-v1"
PATTERN_REVIEW_CONTRACT_VERSION = "pattern-review-v1"
PATTERN_ANALYSIS_KINDS = frozenset({"pattern_assessment", "pattern_review"})
PATTERN_SCORE_DIMENSIONS = (
    "applicability",
    "suitability",
    "conformance",
    "opportunity",
    "confidence",
    "benefit",
    "urgency",
    "execution_safety",
    "migration_cost",
)
PATTERN_RECOMMENDATIONS = (
    "retain",
    "introduce",
    "improve_conformance",
    "replace",
    "avoid",
    "no_action",
    "insufficient_evidence",
)
PATTERN_PRESENCE = ("present", "partial", "absent", "uncertain")
PATTERN_EVALUATION_LIST_FIELDS = (
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
PATTERN_EXPLANATION_LIST_FIELDS = tuple(
    field
    for field in PATTERN_EVALUATION_LIST_FIELDS
    if field not in {"affected_targets", "local_precedents"}
)

_STRINGS = {"type": "array", "items": {"type": "string"}}
_SCORE = {
    "type": "object",
    "properties": {
        "value": {"type": "integer", "minimum": 0, "maximum": 100},
        "rationale": {"type": "string"},
        "evidence": _STRINGS,
    },
    "required": ["value", "rationale", "evidence"],
    "additionalProperties": False,
}
_SCORES = {
    "type": "object",
    "properties": {name: _SCORE for name in PATTERN_SCORE_DIMENSIONS},
    "required": list(PATTERN_SCORE_DIMENSIONS),
    "additionalProperties": False,
}
PATTERN_EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score_contract_version": {"type": "string"},
        "candidate_fingerprint": {"type": "string"},
        "pattern_key": {"type": "string"},
        "target_key": {"type": "string"},
        "summary": {"type": "string"},
        "presence": {
            "type": "string",
            "enum": list(PATTERN_PRESENCE),
        },
        "recommendation": {"type": "string", "enum": list(PATTERN_RECOMMENDATIONS)},
        "scores": _SCORES,
        "rationale": {"type": "string"},
        **{field: _STRINGS for field in PATTERN_EVALUATION_LIST_FIELDS},
    },
    "required": [
        "score_contract_version",
        "candidate_fingerprint",
        "pattern_key",
        "target_key",
        "summary",
        "presence",
        "recommendation",
        "scores",
        "rationale",
        *PATTERN_EVALUATION_LIST_FIELDS,
    ],
    "additionalProperties": False,
}

_REVIEW_ISSUE = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "scope_choice",
                "pattern_identity",
                "overlooked_alternative",
                "counter_evidence",
                "score_consistency",
                "excess_machinery",
                "evidence_quality",
            ],
        },
        "severity": {"type": "string", "enum": ["info", "warning", "error"]},
        "explanation": {"type": "string"},
        "evidence": _STRINGS,
        "correction": {"type": "string"},
    },
    "required": ["kind", "severity", "explanation", "evidence", "correction"],
    "additionalProperties": False,
}
_COMPETING = {
    "type": "object",
    "properties": {
        "pattern_key": {"type": "string"},
        "rationale": {"type": "string"},
        "evidence": _STRINGS,
        "conditions": _STRINGS,
    },
    "required": ["pattern_key", "rationale", "evidence", "conditions"],
    "additionalProperties": False,
}

PATTERN_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "review_contract_version": {"type": "string"},
        "candidate_fingerprint": {"type": "string"},
        "verdict": {
            "type": "string",
            "enum": ["approve", "revise", "retain_competing"],
        },
        "summary": {"type": "string"},
        "issues": {"type": "array", "items": _REVIEW_ISSUE},
        "evaluation": PATTERN_EVALUATION_SCHEMA,
        "competing_interpretations": {"type": "array", "items": _COMPETING},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "evidence": _STRINGS,
    },
    "required": [
        "review_contract_version",
        "candidate_fingerprint",
        "verdict",
        "summary",
        "issues",
        "evaluation",
        "competing_interpretations",
        "confidence",
        "evidence",
    ],
    "additionalProperties": False,
}


def pattern_response_schema(request: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(request.get("analysis_kind") or "")
    schema = _base_pattern_schema(kind)
    return (
        _bound_pattern_schema(schema, request, review=kind == "pattern_review") if schema else None
    )


def _base_pattern_schema(kind: str) -> dict[str, Any] | None:
    return {
        "pattern_assessment": PATTERN_EVALUATION_SCHEMA,
        "pattern_review": PATTERN_REVIEW_SCHEMA,
    }.get(kind)


def _bound_pattern_schema(
    schema: dict[str, Any], request: dict[str, Any], *, review: bool
) -> dict[str, Any]:
    result = copy.deepcopy(schema)
    candidate = request.get("candidate") or {}
    identities = {
        "candidate_fingerprint": str(candidate.get("input_fingerprint") or ""),
        "pattern_key": str(candidate.get("pattern_key") or ""),
        "target_key": str((candidate.get("target") or {}).get("key") or ""),
        "score_contract_version": PATTERN_SCORE_CONTRACT_VERSION,
    }
    evaluation = result["properties"]["evaluation"] if review else result
    for field, expected in identities.items():
        evaluation["properties"][field] = {"type": "string", "enum": [expected]}
    if review:
        result["properties"]["candidate_fingerprint"] = {
            "type": "string",
            "enum": [identities["candidate_fingerprint"]],
        }
        result["properties"]["review_contract_version"] = {
            "type": "string",
            "enum": [PATTERN_REVIEW_CONTRACT_VERSION],
        }
    return result


def pattern_response_name(request: dict[str, Any]) -> str | None:
    kind = str(request.get("analysis_kind") or "")
    return {
        "pattern_assessment": "pattern_evaluation",
        "pattern_review": "pattern_review",
    }.get(kind)


def validated_pattern_response(
    value: Any,
    request: dict[str, Any],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SemanticResult:
    kind = str(request.get("analysis_kind") or "")
    schema = _base_pattern_schema(kind)
    name = pattern_response_name(request)
    if schema is None or name is None:
        raise ValueError(f"unsupported pattern analysis kind: {kind}")
    _validate_schema(value, schema, name)
    expected_fingerprint = str(request.get("candidate", {}).get("input_fingerprint") or "")
    _validate_identity(value, request, expected_fingerprint, review=kind == "pattern_review")
    evaluation = value["evaluation"] if kind == "pattern_review" else value
    _validate_evaluation(evaluation)
    if kind == "pattern_review":
        _validate_review(value)
    confidence = int(evaluation["scores"]["confidence"]["value"]) / 100
    evidence = tuple(str(item)[:2_000] for item in value.get("evidence", ())[:100])
    return SemanticResult(
        value=value,
        confidence=confidence,
        evidence=evidence,
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
    )


def score_values(evaluation: dict[str, Any]) -> dict[str, int]:
    return {name: int(evaluation["scores"][name]["value"]) for name in PATTERN_SCORE_DIMENSIONS}


def _validate_identity(
    value: dict[str, Any],
    request: dict[str, Any],
    expected_fingerprint: str,
    *,
    review: bool,
) -> None:
    evaluation = value["evaluation"] if review else value
    candidate = request.get("candidate") or {}
    identities = {
        "candidate_fingerprint": expected_fingerprint,
        "pattern_key": str(candidate.get("pattern_key") or ""),
        "target_key": str((candidate.get("target") or {}).get("key") or ""),
    }
    for field, expected in identities.items():
        if str(evaluation.get(field) or "") != expected:
            raise ValueError(f"pattern response {field} does not match its candidate")
    if review and str(value.get("candidate_fingerprint") or "") != expected_fingerprint:
        raise ValueError("pattern review candidate_fingerprint does not match its candidate")


def _validate_evaluation(value: dict[str, Any]) -> None:
    if value["score_contract_version"] != PATTERN_SCORE_CONTRACT_VERSION:
        raise ValueError("unsupported pattern score contract version")
    scores = score_values(value)
    if scores["suitability"] >= 70 and scores["conformance"] >= 80:
        if scores["opportunity"] > 40:
            raise ValueError("high conformance and suitability cannot create high opportunity")
        if value["recommendation"] not in {"retain", "no_action"}:
            raise ValueError("high conformance and suitability require retain or no_action")
    if value["recommendation"] == "introduce" and scores["conformance"] > 40:
        raise ValueError("an introduce recommendation cannot claim high existing conformance")


def _validate_review(value: dict[str, Any]) -> None:
    if value["review_contract_version"] != PATTERN_REVIEW_CONTRACT_VERSION:
        raise ValueError("unsupported pattern review contract version")
    if value["verdict"] == "revise" and not value["issues"]:
        raise ValueError("a revised pattern evaluation requires at least one critique issue")
    if value["verdict"] == "retain_competing" and not value["competing_interpretations"]:
        raise ValueError("retained disagreement requires a competing interpretation")
