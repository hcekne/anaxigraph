"""Strict schemas for functional hierarchy and retained blind architecture alternatives."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_fresh_eyes_designs import design_observations
from anaxigraph.semantic_fresh_eyes_functional import (
    FUNCTIONAL_BRIEF,
    FUNCTIONAL_PROTOCOL,
    assert_functional,
    validate_hierarchy,
)
from anaxigraph.semantic_model_contract import (
    SemanticAnalysisError,
    SemanticResult,
    _validate_schema,
)


def _object(**properties: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(item: Any, **bounds: Any) -> dict[str, Any]:
    return {"type": "array", "items": item, **bounds}


_STRING = {"type": "string", "maxLength": 1_200}
_STRINGS = _array(_STRING)
_CONFIDENCE = {"type": "number", "minimum": 0, "maximum": 1}
_SCOPE = _object(
    id={"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$", "maxLength": 80},
    parent_id=_STRING,
    level={"type": "string", "enum": ["product", "capability", "subsystem"]},
    purpose=_STRING,
    inputs=_STRINGS,
    outputs=_STRINGS,
    constraints=_STRINGS,
    dependencies=_STRINGS,
    origin={"type": "string", "enum": ["declared", "inferred"]},
    confidence=_CONFIDENCE,
    unknowns=_STRINGS,
    capability_ids=_STRINGS,
)
FUNCTIONAL_BRIEF_SCHEMA = _object(
    contract_version={"type": "string", "enum": [FUNCTIONAL_BRIEF]},
    purpose=_STRING,
    required_capabilities=_array(_object(id=_STRING, statement=_STRING), minItems=1),
    scopes=_array(_SCOPE, minItems=3, maxItems=24),
    confidence=_CONFIDENCE,
    evidence=_STRINGS,
)
_NODE = _object(key=_STRING, name=_STRING, responsibility=_STRING, contracts=_STRINGS)
_EDGE = _object(source=_STRING, target=_STRING, relationship=_STRING, rationale=_STRING)
_DESIGN = _object(
    summary=_STRING,
    components=_array(_NODE, minItems=1, maxItems=12),
    relationships=_array(_EDGE, maxItems=30),
    control_model=_STRING,
    state_ownership=_STRING,
    failure_isolation=_STRING,
    information_flows=_STRINGS,
    boundary_rules=_STRINGS,
    operating_model=_STRINGS,
    extension_strategy=_STRINGS,
    assumptions=_STRINGS,
    unknowns=_STRINGS,
)
_ISOLATION = _object(
    requested={"type": "string", "enum": ["fresh_context"]},
    status={"type": "string", "enum": ["unverified", "self_reported"]},
    note=_STRING,
)
FUNCTIONAL_PROPOSAL_SCHEMA = _object(
    contract_version={"type": "string", "enum": ["functional-proposal-v2"]},
    scope_id=_STRING,
    brief_revision=_STRING,
    design=_DESIGN,
    pros=_array(_STRING, minItems=1, maxItems=6),
    cons=_array(_STRING, minItems=1, maxItems=6),
    parent_constraints=_STRINGS,
    compatible_parent_alternative_ids=_STRINGS,
    isolation=_ISOLATION,
    confidence=_CONFIDENCE,
    evidence=_STRINGS,
)
_ASSESSMENT = _object(
    alternative_id=_STRING,
    strengths=_STRINGS,
    weaknesses=_STRINGS,
    functional_fit=_STRING,
    change_isolation=_STRING,
    justified_complexity=_STRING,
    operating_constraints=_STRING,
    decomposition=_STRING,
    control_flow=_STRING,
    data_ownership=_STRING,
    failure_isolation=_STRING,
    confidence=_CONFIDENCE,
)
FUNCTIONAL_COMPARISON_SCHEMA = _object(
    contract_version={"type": "string", "enum": ["functional-comparison-v2"]},
    scope_id=_STRING,
    brief_revision=_STRING,
    summary=_STRING,
    assessments=_array(_ASSESSMENT, minItems=3),
    retained_alternative_ids=_STRINGS,
    diversity=_object(
        status={
            "type": "string",
            "enum": ["materially_different", "partial_convergence", "converged", "uncertain"],
        },
        differences=_STRINGS,
        limitations=_STRINGS,
        unexplored_directions=_STRINGS,
        novelty={"type": "string", "enum": ["unverified"]},
    ),
    disagreements=_STRINGS,
    composition_conflicts=_STRINGS,
    unknowns=_STRINGS,
    confidence=_CONFIDENCE,
    evidence=_STRINGS,
)
FUNCTIONAL_REVIEW_SCHEMA = _object(
    contract_version={"type": "string", "enum": ["functional-review-v2"]},
    summary=_STRING,
    reviewed_scope_ids=_STRINGS,
    useful_differences=_STRINGS,
    composition_conflicts=_STRINGS,
    unknowns=_STRINGS,
    confidence=_CONFIDENCE,
    evidence=_STRINGS,
)
SCHEMAS = {
    "hierarchy": FUNCTIONAL_BRIEF_SCHEMA,
    "proposal": FUNCTIONAL_PROPOSAL_SCHEMA,
    "comparison": FUNCTIONAL_COMPARISON_SCHEMA,
    "review": FUNCTIONAL_REVIEW_SCHEMA,
}


def schema_for(request: dict[str, Any]) -> dict[str, Any] | None:
    if request.get("protocol_version") != FUNCTIONAL_PROTOCOL:
        return None
    return SCHEMAS.get(str(request.get("functional_stage") or ""))


def contract_name(request: dict[str, Any]) -> str | None:
    return f"functional_{request['functional_stage']}" if schema_for(request) else None


def validate_functional(value: Any, request: Any, **usage: Any) -> SemanticResult | None:
    schema = schema_for(request)
    if schema is None:
        return None
    _validate_schema(value, schema, str(contract_name(request)))
    assert_functional(value)
    stage = request["functional_stage"]
    if stage == "hierarchy":
        validate_hierarchy(value)
        _validate_capability_coverage(value, request)
    elif stage in {"proposal", "comparison"}:
        _validate_scope(value, request)
    if stage == "comparison":
        _validate_retention(value, request)
        _validate_diversity(value, request)
    if stage == "review" and set(value["reviewed_scope_ids"]) != set(request["scope_ids"]):
        raise SemanticAnalysisError("Functional review must account for every requested scope")
    return SemanticResult(
        value=value,
        confidence=float(value["confidence"]),
        evidence=tuple(value["evidence"]),
        **usage,
    )


def _validate_capability_coverage(value: Any, request: Any) -> None:
    expected = request["capability_projection"]["required_capabilities"]
    if value["required_capabilities"] != expected:
        raise SemanticAnalysisError(
            "Functional hierarchy must preserve all required capabilities exactly"
        )
    identifiers = {item["id"] for item in expected}
    covered = {
        key
        for scope in value["scopes"]
        if scope["level"] == "capability"
        for key in scope["capability_ids"]
    }
    if covered != identifiers:
        raise SemanticAnalysisError(
            "Functional capability scopes must account for every requirement ID"
        )
    if any(key not in identifiers for scope in value["scopes"] for key in scope["capability_ids"]):
        raise SemanticAnalysisError("Functional scope references an unknown capability requirement")


def _validate_scope(value: Any, request: Any) -> None:
    packet = request["functional_scope"]
    if value["scope_id"] != packet["scope"]["id"] or value["brief_revision"] != packet["revision"]:
        raise SemanticAnalysisError("Alternative must identify its exact functional scope revision")
    if request["functional_stage"] == "proposal":
        _validate_composition(value, request)
        nodes = {node["key"] for node in value["design"]["components"]}
        if len(nodes) != len(value["design"]["components"]):
            raise SemanticAnalysisError("Proposed architecture component keys must be unique")
        for edge in value["design"]["relationships"]:
            if edge["source"] not in nodes or edge["target"] not in nodes:
                raise SemanticAnalysisError("Proposed relationship must reference a proposed node")


def _validate_composition(value: Any, request: Any) -> None:
    parents = {item["id"] for item in request.get("parent_alternatives", [])}
    compatible = value["compatible_parent_alternative_ids"]
    if any(key not in parents for key in compatible):
        raise SemanticAnalysisError("Child alternatives may name only supplied proposed parents")
    if parents and not compatible and not value["design"]["unknowns"]:
        raise SemanticAnalysisError("Unresolved parent composition must be recorded as an unknown")


def _validate_retention(value: Any, request: Any) -> None:
    expected = {item["id"] for item in request["alternatives"]}
    retained = value["retained_alternative_ids"]
    assessed = [item["alternative_id"] for item in value["assessments"]]
    if set(retained) != expected or len(retained) != len(expected):
        raise SemanticAnalysisError(
            "Blind comparison must retain every alternative, not one winner"
        )
    if set(assessed) != expected or len(assessed) != len(expected):
        raise SemanticAnalysisError("Blind comparison must assess every retained alternative")


def _validate_diversity(value: Any, request: Any) -> None:
    axes = ("decomposition", "control_flow", "data_ownership", "failure_isolation")
    if any(not item[axis].strip() for item in value["assessments"] for axis in axes):
        raise SemanticAnalysisError("Compare decomposition, control, data and failure isolation")
    diversity = value["diversity"]
    if diversity["status"] == "materially_different" and not diversity["differences"]:
        raise SemanticAnalysisError("Claimed material differences need an explicit explanation")
    repeated = design_observations(request["alternatives"])["exact_repeated_designs"]
    if not repeated:
        return
    if diversity["status"] == "materially_different" or not diversity["limitations"]:
        raise SemanticAnalysisError("Repeated designs require an honest convergence limitation")
    if (
        len(repeated[0]) == len(request["alternatives"])
        and diversity["status"] == "partial_convergence"
    ):
        raise SemanticAnalysisError("All exact repeated designs have converged or remain uncertain")
