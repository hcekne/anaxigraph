"""Strict contracts for autonomous repository taxonomy proposal and critique."""

from __future__ import annotations

from typing import Any

from anaxigraph.architecture_charter_contract import (
    ARCHITECTURE_CHARTER_SCHEMA,
    is_architecture_charter_request,
    validated_architecture_charter,
)
from anaxigraph.pattern_evaluation_contract import (
    pattern_response_name,
    pattern_response_schema,
    validated_pattern_response,
)
from anaxigraph.semantic_contract import (
    DOSSIER_SCHEMA,
    SemanticResult,
    _validate_schema,
    validated_result,
)

_STRINGS = {"type": "array", "items": {"type": "string"}}
_MEMBERSHIP = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "evidence": _STRINGS,
        "alternatives": _STRINGS,
    },
    "required": ["path", "confidence", "rationale", "evidence", "alternatives"],
    "additionalProperties": False,
}
_SUBSYSTEM = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "responsibility": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "evidence": _STRINGS,
        "counter_evidence": _STRINGS,
        "members": {"type": "array", "items": _MEMBERSHIP},
    },
    "required": [
        "key",
        "name",
        "description",
        "responsibility",
        "confidence",
        "rationale",
        "evidence",
        "counter_evidence",
        "members",
    ],
    "additionalProperties": False,
}
_AREA = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "responsibility": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "evidence": _STRINGS,
        "counter_evidence": _STRINGS,
        "subsystems": {"type": "array", "items": _SUBSYSTEM},
    },
    "required": [
        "key",
        "name",
        "description",
        "responsibility",
        "confidence",
        "rationale",
        "evidence",
        "counter_evidence",
        "subsystems",
    ],
    "additionalProperties": False,
}
_FACET = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "members": _STRINGS,
        "evidence": _STRINGS,
    },
    "required": ["name", "description", "members", "evidence"],
    "additionalProperties": False,
}

TAXONOMY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "areas": {"type": "array", "items": _AREA},
        "facets": {"type": "array", "items": _FACET},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": _STRINGS,
    },
    "required": ["summary", "areas", "facets", "confidence", "evidence"],
    "additionalProperties": False,
}

_REVIEW_ISSUE = {
    "type": "object",
    "properties": {
        "kind": {"type": "string"},
        "severity": {"type": "string", "enum": ["info", "warning", "error"]},
        "scope": {"type": "string"},
        "explanation": {"type": "string"},
        "evidence": _STRINGS,
        "recommendation": {"type": "string"},
    },
    "required": [
        "kind",
        "severity",
        "scope",
        "explanation",
        "evidence",
        "recommendation",
    ],
    "additionalProperties": False,
}

TAXONOMY_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "revise"]},
        "summary": {"type": "string"},
        "issues": {"type": "array", "items": _REVIEW_ISSUE},
        "taxonomy": TAXONOMY_SCHEMA,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": _STRINGS,
    },
    "required": ["verdict", "summary", "issues", "taxonomy", "confidence", "evidence"],
    "additionalProperties": False,
}


def response_schema(request: dict[str, Any]) -> dict[str, Any]:
    pattern_schema = pattern_response_schema(request)
    if pattern_schema is not None:
        return pattern_schema
    if is_architecture_charter_request(request):
        return ARCHITECTURE_CHARTER_SCHEMA
    kind = str(request.get("analysis_kind") or "")
    if kind.startswith("taxonomy_review"):
        return TAXONOMY_REVIEW_SCHEMA
    if kind.startswith("taxonomy_"):
        return TAXONOMY_SCHEMA
    return DOSSIER_SCHEMA


def response_contract_name(request: dict[str, Any]) -> str:
    pattern_name = pattern_response_name(request)
    if pattern_name is not None:
        return pattern_name
    if is_architecture_charter_request(request):
        return "architecture_charter"
    kind = str(request.get("analysis_kind") or "")
    if kind.startswith("taxonomy_review"):
        return "taxonomy_review"
    if kind.startswith("taxonomy_"):
        return "taxonomy"
    return "dossier"


def validated_semantic_response(
    value: Any,
    request: dict[str, Any],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SemanticResult:
    kind = str(request.get("analysis_kind") or "")
    if pattern_response_schema(request) is not None:
        return validated_pattern_response(
            value,
            request,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    if is_architecture_charter_request(request):
        return validated_architecture_charter(
            value,
            request,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    if not kind.startswith("taxonomy_"):
        return validated_result(value, input_tokens=input_tokens, output_tokens=output_tokens)
    review = kind.startswith("taxonomy_review")
    schema = TAXONOMY_REVIEW_SCHEMA if review else TAXONOMY_SCHEMA
    label = "taxonomy review" if review else "taxonomy"
    _validate_schema(value, schema, label)
    confidence = max(0.0, min(1.0, float(value.get("confidence") or 0)))
    evidence = tuple(str(item)[:2_000] for item in (value.get("evidence") or [])[:100])
    return SemanticResult(
        value=value,
        confidence=confidence,
        evidence=evidence,
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
    )


def validated_agent_semantic_response(
    value: Any,
    request: dict[str, Any],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SemanticResult:
    """Strictly validate any untrusted agent submission before normalization."""

    _validate_schema(value, response_schema(request), response_contract_name(request))
    return validated_semantic_response(
        value,
        request,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
