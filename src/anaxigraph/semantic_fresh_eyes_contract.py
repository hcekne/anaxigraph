"""Strict contracts for the fixed, implementation-blind architecture review recipe."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from anaxigraph.semantic_contract import SemanticAnalysisError, SemanticResult, _validate_schema
from anaxigraph.semantic_freshness import semantic_digest as semantic_digest
from anaxigraph.semantic_freshness import semantic_input_hash as semantic_input_hash

FRESH_EYES_REVIEW_VERSION = "fresh-eyes-review-v1"
FRESH_EYES_PROPOSAL_VERSION = "fresh-eyes-proposal-v1"
FRESH_EYES_ADJUDICATION_VERSION = "fresh-eyes-adjudication-v1"
FRESH_EYES_COMPARISON_VERSION = "fresh-eyes-comparison-v1"
FRESH_EYES_PROTOCOL_VERSION = "fresh-eyes-recipe-v1"

ANY_EXECUTOR = "any"
FRESH_EYES_EXECUTORS = ("codex", "claude", ANY_EXECUTOR)
PROPOSAL_SCOPE_PREFIX = "proposal:"


def fresh_eyes_plan_options(plan: dict[str, Any]) -> tuple[int, int]:
    """Read proposal count and explicit rerun generation from one plan row."""

    proposal_text, generation_text, _executors = _plan_token_parts(plan)
    try:
        proposal_count = int(proposal_text)
        generation = int(generation_text) if generation_text else 1
    except ValueError:
        return 2, 1
    return max(1, min(3, proposal_count)), max(1, generation)


def fresh_eyes_plan_executors(plan: dict[str, Any]) -> tuple[str, ...]:
    """Read the per-slot executor assignment; a two-part token records no assignment."""

    _proposals, _generation, executor_text = _plan_token_parts(plan)
    named = [item.strip().lower() for item in executor_text.split(",")]
    return tuple(item for item in named if item in FRESH_EYES_EXECUTORS)


def fresh_eyes_required_executor(executors: Sequence[str], scope_key: str) -> str | None:
    """Name the executor family pinned to one proposal slot, or None when any may take it."""

    key = str(scope_key)
    if not key.startswith(PROPOSAL_SCOPE_PREFIX):
        return None
    slot = key[len(PROPOSAL_SCOPE_PREFIX) :]
    index = ord(slot) - ord("a") if len(slot) == 1 else -1
    if index < 0 or index >= len(executors) or executors[index] == ANY_EXECUTOR:
        return None
    return str(executors[index])


def fresh_eyes_plan_token(
    proposal_count: int, generation: int, executors: Sequence[str] = ()
) -> str:
    """Encode small plan controls without adding model identity to semantic freshness.

    The executor assignment names who should take each proposal slot, not which model produced
    a result, so it stays out of every stage manifest and leaves stage input hashes unchanged.
    """

    families = proposal_executor_families(executors, proposal_count)
    token = f"{proposal_count}:{generation}"
    return f"{token}:{','.join(families)}" if families else token


def proposal_executor_families(executors: Sequence[str], proposal_count: int) -> tuple[str, ...]:
    """Validate one executor family per proposal slot before any job is queued."""

    families = tuple(str(item).strip().lower() for item in executors if str(item).strip())
    if not families:
        return ()
    unknown = [item for item in families if item not in FRESH_EYES_EXECUTORS]
    if unknown:
        raise ValueError(
            "Fresh-eyes proposal executors must each be one of "
            f"{', '.join(FRESH_EYES_EXECUTORS)}; received {', '.join(unknown)}"
        )
    if len(families) != proposal_count:
        raise ValueError(
            "Fresh-eyes review needs one proposal executor per slot: "
            f"{proposal_count} proposals requested, {len(families)} executors named"
        )
    return families


def parse_proposal_executors(value: Any) -> tuple[str, ...]:
    """Read ``codex,claude`` from a CLI or MCP string, or a REST list, as executor families."""

    named = value.split(",") if isinstance(value, str) else list(value or ())
    return tuple(str(item).strip().lower() for item in named if str(item).strip())


def _plan_token_parts(plan: dict[str, Any]) -> tuple[str, str, str]:
    parts = str(plan.get("interface_hash") or "2").split(":")
    padded = (*parts, "", "")
    return padded[0], padded[1], padded[2]


def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


_STRING = {"type": "string"}
_STRINGS = _array(_STRING)
_EVIDENCE = {**_array({"type": "string", "minLength": 1}), "minItems": 1}
_CONFIDENCE = {"type": "number", "minimum": 0, "maximum": 1}

_COMPONENT = _object(
    key=_STRING,
    name=_STRING,
    responsibility=_STRING,
    collaborators=_STRINGS,
    extension_points=_STRINGS,
)
_FLOW = _object(name=_STRING, steps=_STRINGS, rationale=_STRING)
_PATTERN = _object(name=_STRING, purpose=_STRING, tradeoffs=_STRINGS)
_DESIGN = _object(
    summary=_STRING,
    components=_array(_COMPONENT),
    information_flows=_array(_FLOW),
    boundary_rules=_STRINGS,
    operating_model=_STRINGS,
    extension_strategy=_STRINGS,
    patterns=_array(_PATTERN),
    simplifications=_STRINGS,
    tradeoffs=_STRINGS,
    assumptions=_STRINGS,
    unknowns=_STRINGS,
)

FRESH_EYES_PROPOSAL_SCHEMA: dict[str, Any] = _object(
    contract_version={"type": "string", "enum": [FRESH_EYES_PROPOSAL_VERSION]},
    design=_DESIGN,
    isolation=_object(
        requested={"type": "string", "enum": ["fresh_context"]},
        status={"type": "string", "enum": ["self_reported", "unverified"]},
        note=_STRING,
    ),
    confidence=_CONFIDENCE,
    evidence=_EVIDENCE,
)

_DISAGREEMENT = _object(
    topic=_STRING,
    positions=_STRINGS,
    adjudication=_STRING,
    preserved_alternative=_STRING,
)
FRESH_EYES_ADJUDICATION_SCHEMA: dict[str, Any] = _object(
    contract_version={"type": "string", "enum": [FRESH_EYES_ADJUDICATION_VERSION]},
    summary=_STRING,
    shared_ground=_STRINGS,
    disagreements=_array(_DISAGREEMENT),
    common_blind_spots=_STRINGS,
    proposal_assessments=_array(_object(proposal=_STRING, strengths=_STRINGS, weaknesses=_STRINGS)),
    reference_design=_DESIGN,
    confidence=_CONFIDENCE,
    evidence=_EVIDENCE,
)

_CLASSIFICATIONS = [
    "already_satisfies",
    "good_reason_to_differ",
    "useful_simplification",
    "missing_capability",
    "migration_cost_outweighs_value",
    "insufficient_evidence",
]
_MAPPING = _object(
    reference_responsibility=_STRING,
    current_responsibilities=_STRINGS,
    classification={"type": "string", "enum": _CLASSIFICATIONS},
    explanation=_STRING,
    evidence=_EVIDENCE,
    counter_evidence=_STRINGS,
    migration_cost={"type": "string", "enum": ["none", "low", "medium", "high"]},
)
_CANDIDATE_CHANGE = _object(
    title=_STRING,
    classification={"type": "string", "enum": _CLASSIFICATIONS},
    explanation=_STRING,
    affected_responsibilities=_STRINGS,
    evidence=_EVIDENCE,
    counter_evidence=_STRINGS,
    migration_cost={"type": "string", "enum": ["low", "medium", "high"]},
)
FRESH_EYES_COMPARISON_SCHEMA: dict[str, Any] = _object(
    contract_version={"type": "string", "enum": [FRESH_EYES_COMPARISON_VERSION]},
    summary=_STRING,
    mappings=_array(_MAPPING),
    current_strengths=_STRINGS,
    candidate_changes=_array(_CANDIDATE_CHANGE),
    unknowns=_STRINGS,
    confidence=_CONFIDENCE,
    evidence=_EVIDENCE,
)

_ACTIONS = ["retain", "move", "split", "consolidate", "delete", "refactor"]
_RECOMMENDATION = _object(
    rank={"type": "integer", "minimum": 1},
    title=_STRING,
    action={"type": "string", "enum": _ACTIONS},
    mission_capability=_STRING,
    current_evidence=_EVIDENCE,
    reference_insight=_STRING,
    smallest_change=_STRING,
    expected_benefit=_STRING,
    expected_deletions=_STRINGS,
    protected_behavior=_STRINGS,
    affected_contracts=_STRINGS,
    risks=_STRINGS,
    counter_evidence=_STRINGS,
    reasons_not_to_proceed=_STRINGS,
    dependencies=_STRINGS,
    verification=_STRINGS,
    reversible={"type": "boolean"},
    confidence=_CONFIDENCE,
)
FRESH_EYES_REVIEW_SCHEMA: dict[str, Any] = _object(
    contract_version={"type": "string", "enum": [FRESH_EYES_REVIEW_VERSION]},
    summary=_STRING,
    mission_alignment=_STRING,
    recommendations=_array(_RECOMMENDATION),
    rejected_ideas=_array(_object(idea=_STRING, reason=_STRING, evidence=_EVIDENCE)),
    sequence=_STRINGS,
    caveats=_STRINGS,
    confidence=_CONFIDENCE,
    evidence=_EVIDENCE,
)

_SCHEMAS = {
    "fresh_proposal": FRESH_EYES_PROPOSAL_SCHEMA,
    "fresh_adjudication": FRESH_EYES_ADJUDICATION_SCHEMA,
    "fresh_comparison": FRESH_EYES_COMPARISON_SCHEMA,
    "fresh_review": FRESH_EYES_REVIEW_SCHEMA,
}
_NAMES = {
    "fresh_proposal": "fresh_eyes_proposal",
    "fresh_adjudication": "fresh_eyes_adjudication",
    "fresh_comparison": "fresh_eyes_comparison",
    "fresh_review": "fresh_eyes_review",
}
_IMPLEMENTATION_IDENTITY = re.compile(
    r"(?:^|[\s'\"`(])(?:\.?\.?/|src/|tests?/|packages?/|[\w.-]+\.(?:py|js|jsx|ts|tsx|rs|go|java))(?:$|[\s'\"`),:])",
    re.IGNORECASE,
)


def fresh_eyes_schema(request: dict[str, Any]) -> dict[str, Any] | None:
    return _SCHEMAS.get(str(request.get("analysis_kind") or ""))


def fresh_eyes_contract_name(request: dict[str, Any]) -> str | None:
    return _NAMES.get(str(request.get("analysis_kind") or ""))


def validated_fresh_eyes_response(
    value: Any,
    request: dict[str, Any],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SemanticResult | None:
    kind = str(request.get("analysis_kind") or "")
    schema = _SCHEMAS.get(kind)
    if schema is None:
        return None
    _validate_schema(value, schema, _NAMES[kind])
    if kind in {"fresh_proposal", "fresh_adjudication"}:
        leaked = _IMPLEMENTATION_IDENTITY.search(json.dumps(value, ensure_ascii=False))
        if leaked:
            raise SemanticAnalysisError(
                "implementation-blind architecture result contains a repository path or file identity"
            )
    confidence = max(0.0, min(1.0, float(value.get("confidence") or 0)))
    evidence = tuple(str(item)[:2_000] for item in (value.get("evidence") or [])[:100])
    return SemanticResult(
        value=value,
        confidence=confidence,
        evidence=evidence,
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
    )
