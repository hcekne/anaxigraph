"""Canonical semantic dossier schema, result types, and output normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

SEMANTIC_SCHEMA_VERSION = "repository-understanding-v5"

_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
_PATTERN_OPPORTUNITY = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "scope": {"type": "string"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "evidence": _STRING_ARRAY,
        "counter_evidence": _STRING_ARRAY,
        "migration_cost": {
            "type": "string",
            "enum": ["low", "medium", "high", "unknown"],
        },
        "preconditions": _STRING_ARRAY,
    },
    "required": [
        "name",
        "scope",
        "score",
        "confidence",
        "rationale",
        "evidence",
        "counter_evidence",
        "migration_cost",
        "preconditions",
    ],
    "additionalProperties": False,
}
_CONSOLIDATION_ASSESSMENT = {
    "type": "object",
    "properties": {
        "recommendation": {
            "type": "string",
            "enum": ["keep", "merge", "split", "review", "insufficient_evidence"],
        },
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "rationale": {"type": "string"},
        "candidates": _STRING_ARRAY,
        "evidence": _STRING_ARRAY,
        "counter_evidence": _STRING_ARRAY,
    },
    "required": [
        "recommendation",
        "score",
        "rationale",
        "candidates",
        "evidence",
        "counter_evidence",
    ],
    "additionalProperties": False,
}
_DEAD_CODE_CANDIDATE = {
    "type": "object",
    "properties": {
        "path_or_symbol": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "reachability_evidence": _STRING_ARRAY,
        "counter_evidence": _STRING_ARRAY,
        "verification": {"type": "string"},
    },
    "required": [
        "path_or_symbol",
        "confidence",
        "rationale",
        "reachability_evidence",
        "counter_evidence",
        "verification",
    ],
    "additionalProperties": False,
}
DOSSIER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "detailed_summary": {"type": "string"},
        "responsibilities": _STRING_ARRAY,
        "inputs": _STRING_ARRAY,
        "outputs": _STRING_ARRAY,
        "side_effects": _STRING_ARRAY,
        "public_contracts": _STRING_ARRAY,
        "invariants": _STRING_ARRAY,
        "architecture_role": {"type": "string"},
        "domain_concepts": _STRING_ARRAY,
        "collaborators": _STRING_ARRAY,
        "overlaps": _STRING_ARRAY,
        "extension_points": _STRING_ARRAY,
        "similar_modules": _STRING_ARRAY,
        "pattern_opportunities": {"type": "array", "items": _PATTERN_OPPORTUNITY},
        "consolidation_assessment": _CONSOLIDATION_ASSESSMENT,
        "dead_code_candidates": {"type": "array", "items": _DEAD_CODE_CANDIDATE},
        "placement_guidance": {"type": "string"},
        "testing_guidance": _STRING_ARRAY,
        "change_summary": {"type": "string"},
        "risks": _STRING_ARRAY,
        "evidence": _STRING_ARRAY,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "summary",
        "detailed_summary",
        "responsibilities",
        "inputs",
        "outputs",
        "side_effects",
        "public_contracts",
        "invariants",
        "architecture_role",
        "domain_concepts",
        "collaborators",
        "overlaps",
        "extension_points",
        "similar_modules",
        "pattern_opportunities",
        "consolidation_assessment",
        "dead_code_candidates",
        "placement_guidance",
        "testing_guidance",
        "change_summary",
        "risks",
        "evidence",
        "confidence",
    ],
    "additionalProperties": False,
}


class SemanticAnalysisError(RuntimeError):
    """The configured semantic provider could not return a valid dossier."""


@dataclass(frozen=True, slots=True)
class SemanticResult:
    value: dict[str, Any]
    confidence: float
    evidence: tuple[str, ...]
    input_tokens: int = 0
    output_tokens: int = 0


class SemanticProvider(Protocol):
    name: str

    def analyze(self, request: dict[str, Any]) -> SemanticResult: ...


def validated_result(
    value: Any,
    *,
    input_tokens: int,
    output_tokens: int,
) -> SemanticResult:
    if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
        raise SemanticAnalysisError("Semantic response requires a summary string")
    confidence = float(value.get("confidence", 0.5))
    if not 0 <= confidence <= 1:
        raise SemanticAnalysisError("Semantic confidence must be between 0 and 1")

    normalized: dict[str, Any] = {
        "summary": str(value.get("summary") or "")[:4_000],
        "detailed_summary": str(value.get("detailed_summary") or "")[:12_000],
        "architecture_role": str(
            value.get("architecture_role") or value.get("architectural_group") or ""
        )[:2_000],
        "placement_guidance": str(value.get("placement_guidance") or "")[:4_000],
        "change_summary": str(value.get("change_summary") or "")[:4_000],
    }
    for key in (
        "responsibilities",
        "inputs",
        "outputs",
        "side_effects",
        "public_contracts",
        "invariants",
        "domain_concepts",
        "collaborators",
        "overlaps",
        "extension_points",
        "similar_modules",
        "testing_guidance",
        "risks",
        "evidence",
    ):
        normalized[key] = list(_strings(value.get(key)))
    normalized["pattern_opportunities"] = list(
        _pattern_opportunities(value.get("pattern_opportunities"))
    )
    normalized["consolidation_assessment"] = _consolidation_assessment(
        value.get("consolidation_assessment")
    )
    normalized["dead_code_candidates"] = list(
        _dead_code_candidates(value.get("dead_code_candidates"))
    )
    normalized["confidence"] = confidence
    evidence = tuple(normalized["evidence"])
    return SemanticResult(
        value=normalized,
        confidence=confidence,
        evidence=evidence,
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
    )


def validated_agent_result(
    value: Any,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SemanticResult:
    """Strictly validate an untrusted MCP submission before normalizing it."""

    _validate_schema(value, DOSSIER_SCHEMA, "dossier")
    return validated_result(
        value,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise SemanticAnalysisError(f"{path} must be an object")
        properties = schema.get("properties") or {}
        missing = [key for key in schema.get("required") or [] if key not in value]
        if missing:
            raise SemanticAnalysisError(
                f"{path} is missing required fields: {', '.join(sorted(missing))}"
            )
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(value) - set(properties))
            if unexpected:
                raise SemanticAnalysisError(
                    f"{path} has unsupported fields: {', '.join(unexpected)}"
                )
        for key, child in properties.items():
            if key in value:
                _validate_schema(value[key], child, f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise SemanticAnalysisError(f"{path} must be an array")
        child = schema.get("items") or {}
        for index, item in enumerate(value):
            _validate_schema(item, child, f"{path}[{index}]")
        return
    if expected == "string" and not isinstance(value, str):
        raise SemanticAnalysisError(f"{path} must be a string")
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise SemanticAnalysisError(f"{path} must be an integer")
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise SemanticAnalysisError(f"{path} must be a number")
    if "enum" in schema and value not in schema["enum"]:
        raise SemanticAnalysisError(f"{path} must be one of: {', '.join(schema['enum'])}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SemanticAnalysisError(f"{path} must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SemanticAnalysisError(f"{path} must be at most {schema['maximum']}")


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    for item in value:
        if isinstance(item, dict):
            item = json.dumps(item, sort_keys=True)
        if isinstance(item, (str, int, float)):
            result.append(str(item)[:2_000])
    return tuple(result[:100])


def _pattern_opportunities(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    for item in value[:50]:
        if isinstance(item, str):
            item = {"name": item, "rationale": item}
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "name": str(item.get("name") or "Unnamed pattern")[:500],
                "scope": str(item.get("scope") or "module")[:500],
                "score": max(0, min(100, int(item.get("score") or 0))),
                "confidence": max(0.0, min(1.0, float(item.get("confidence") or 0))),
                "rationale": str(item.get("rationale") or "")[:4_000],
                "evidence": list(_strings(item.get("evidence"))),
                "counter_evidence": list(_strings(item.get("counter_evidence"))),
                "migration_cost": (
                    str(item.get("migration_cost"))
                    if item.get("migration_cost") in {"low", "medium", "high", "unknown"}
                    else "unknown"
                ),
                "preconditions": list(_strings(item.get("preconditions"))),
            }
        )
    return tuple(result)


def _consolidation_assessment(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"rationale": value}
    if not isinstance(value, dict):
        value = {}
    recommendation = str(value.get("recommendation") or "insufficient_evidence")
    if recommendation not in {"keep", "merge", "split", "review", "insufficient_evidence"}:
        recommendation = "insufficient_evidence"
    return {
        "recommendation": recommendation,
        "score": max(0, min(100, int(value.get("score") or 0))),
        "rationale": str(value.get("rationale") or "")[:4_000],
        "candidates": list(_strings(value.get("candidates"))),
        "evidence": list(_strings(value.get("evidence"))),
        "counter_evidence": list(_strings(value.get("counter_evidence"))),
    }


def _dead_code_candidates(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result = []
    for item in value[:100]:
        if isinstance(item, str):
            item = {"path_or_symbol": item, "rationale": item}
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "path_or_symbol": str(item.get("path_or_symbol") or "unknown")[:2_000],
                "confidence": max(0.0, min(1.0, float(item.get("confidence") or 0))),
                "rationale": str(item.get("rationale") or "")[:4_000],
                "reachability_evidence": list(_strings(item.get("reachability_evidence"))),
                "counter_evidence": list(_strings(item.get("counter_evidence"))),
                "verification": str(item.get("verification") or "")[:4_000],
            }
        )
    return tuple(result)
