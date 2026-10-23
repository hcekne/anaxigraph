"""Strict contracts for autonomous repository taxonomy proposal and critique."""

from __future__ import annotations

from typing import Any

from anaxigraph.architecture_charter_contract import (
    ARCHITECTURE_CHARTER_SCHEMA,
    is_architecture_charter_request,
    validated_architecture_charter,
)
from anaxigraph.architecture_plan_contract import PLAN_SCHEMA, validate_plan_structure
from anaxigraph.pattern_evaluation_contract import (
    pattern_response_name,
    pattern_response_schema,
    validated_pattern_response,
)
from anaxigraph.semantic_contract import (
    SemanticResult,
    _validate_schema,
    validated_mapping,
)
from anaxigraph.semantic_fresh_eyes_contract import (
    fresh_eyes_contract_name,
    fresh_eyes_schema,
    validated_fresh_eyes_response,
)
from anaxigraph.semantic_request_support import MAPPING_SCHEMA

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
    if request.get("analysis_kind") == "annotation":
        from anaxigraph.knowledge_annotation_contract import ANNOTATION_SCHEMA

        return ANNOTATION_SCHEMA
    if request.get("analysis_kind") == "architecture_plan":
        return PLAN_SCHEMA
    review_schema = fresh_eyes_schema(request)
    if review_schema is not None:
        return review_schema
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
    return MAPPING_SCHEMA


def response_contract_name(request: dict[str, Any]) -> str:
    if request.get("analysis_kind") == "annotation":
        return "graph_annotation"
    if request.get("analysis_kind") == "architecture_plan":
        return "architecture_plan"
    review_name = fresh_eyes_contract_name(request)
    if review_name is not None:
        return review_name
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
    if kind == "annotation":
        from anaxigraph.knowledge_annotation_contract import validated_annotation

        return validated_annotation(
            value, input_tokens=input_tokens, output_tokens=output_tokens, request=request
        )
    if kind == "architecture_plan":
        return _validated_plan(value, input_tokens, output_tokens)
    specialized = _specialized_response(value, request, input_tokens, output_tokens)
    if specialized is not None:
        return specialized
    if not kind.startswith("taxonomy_"):
        return validated_mapping(value, input_tokens=input_tokens, output_tokens=output_tokens)
    review = kind.startswith("taxonomy_review")
    schema = TAXONOMY_REVIEW_SCHEMA if review else TAXONOMY_SCHEMA
    label = "taxonomy review" if review else "taxonomy"
    _validate_schema(value, schema, label)
    return SemanticResult(
        value=value,
        confidence=max(0.0, min(1.0, float(value.get("confidence") or 0))),
        evidence=tuple(str(item)[:2000] for item in (value.get("evidence") or [])[:100]),
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
    )


def _validated_plan(value: Any, input_tokens: int, output_tokens: int) -> SemanticResult:
    _validate_schema(value, PLAN_SCHEMA, "architecture plan")
    validate_plan_structure(value)
    return SemanticResult(
        value=value,
        confidence=float(value["confidence"]),
        evidence=tuple(value["evidence"]),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _specialized_response(
    value: Any, request: Any, input_tokens: int, output_tokens: int
) -> SemanticResult | None:
    fresh_result = validated_fresh_eyes_response(
        value,
        request,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    if fresh_result is not None:
        return fresh_result
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
    return None


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
