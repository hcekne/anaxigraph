"""Compact semantic graph annotation wire contract and validation."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_model_contract import (
    SemanticAnalysisError,
    SemanticResult,
    _validate_schema,
)

ANNOTATION_VERSION = "graph-annotation-v1"
_STRINGS = {"type": "array", "items": {"type": "string"}}


def _object(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


ANNOTATION_SCHEMA = _object(
    overview={"type": "string", "minLength": 1},
    detail={"type": "string"},
    functions={
        "type": "array",
        "items": _object(qualified_name={"type": "string"}, overview={"type": "string"}),
    },
    contracts={
        "type": "array",
        "items": _object(
            name={"type": "string"},
            statement={"type": "string"},
            functions=_STRINGS,
            inputs=_STRINGS,
            outputs=_STRINGS,
            errors=_STRINGS,
            side_effects=_STRINGS,
            invariants=_STRINGS,
            evidence=_STRINGS,
        ),
    },
    capabilities={
        "type": "array",
        "items": _object(
            name={"type": "string"},
            purpose={"type": "string"},
            inputs=_STRINGS,
            outputs=_STRINGS,
            constraints=_STRINGS,
        ),
    },
    evidence=_STRINGS,
    confidence={"type": "number", "minimum": 0, "maximum": 1},
)

ANNOTATION_INSTRUCTIONS = (
    "Annotate the supplied module as a compact semantic graph. Give exactly one short overview "
    "sentence and one short detail paragraph (usually 40–80 words). Give each supplied function "
    "one behavior sentence, using its exact qualified name. State important caller obligations, "
    "invariants, failures, side effects and ordering once in named contracts; link the functions "
    "they apply to. Describe externally useful capabilities without dictating implementation. "
    "Use supplied evidence, retain unknowns, and do not invent functions or obligations. "
    "Do not write separate intrinsic/context essays or pattern/refactoring recommendations."
)


def validated_annotation(value: Any, *, input_tokens=0, output_tokens=0, request=None):
    _validate_schema(value, ANNOTATION_SCHEMA, "graph_annotation")
    if request is not None:
        expected = {item["qualified_name"] for item in request.get("functions", [])}
        names = [item["qualified_name"] for item in value["functions"]]
        if set(names) != expected or len(names) != len(set(names)):
            raise SemanticAnalysisError(
                "Graph annotation must describe each supplied function exactly once"
            )
    _validate_annotation_contracts(value)
    return SemanticResult(
        value,
        float(value["confidence"]),
        tuple(value["evidence"]),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _validate_annotation_contracts(value: Any) -> None:
    names = {item["qualified_name"] for item in value["functions"]}
    if not value["overview"].strip():
        raise SemanticAnalysisError("Graph annotation overview cannot be blank")
    for function in value["functions"]:
        if not function["qualified_name"].strip() or not function["overview"].strip():
            raise SemanticAnalysisError(
                "Graph annotation functions need names and behavior sentences"
            )
    _validate_named_entities(value["contracts"], ("name", "statement"), "contracts")
    _validate_named_entities(value["capabilities"], ("name", "purpose"), "capabilities")
    for contract in value["contracts"]:
        _validate_named_contract(contract, names)


def _validate_named_entities(items: Any, fields: tuple[str, ...], kind: str) -> None:
    names = [item["name"] for item in items]
    if len(names) != len(set(names)):
        raise SemanticAnalysisError(f"Graph annotation {kind} need unique names")
    if any(not item[field].strip() for item in items for field in fields):
        raise SemanticAnalysisError(f"Graph annotation {kind} need nonblank {' and '.join(fields)}")


def _validate_named_contract(contract: Any, names: set[str]) -> None:
    if any(name not in names for name in contract["functions"]):
        raise SemanticAnalysisError("Contract bindings must reference supplied functions")
    for field in ("inputs", "outputs", "errors", "side_effects", "invariants", "evidence"):
        if any(not item.strip() for item in contract[field]):
            raise SemanticAnalysisError("Contract obligations and evidence cannot be blank")
