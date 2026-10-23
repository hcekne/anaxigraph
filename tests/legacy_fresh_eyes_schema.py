"""Immutable v1 wire fixture; production legacy results are read-only archives."""

from typing import Any

FRESH_EYES_REVIEW_VERSION = "fresh-eyes-review-v1"


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


_VERIFICATION_RESULT = _object(
    status={
        "type": "string",
        "enum": ["unverified", "passed", "failed"],
        "description": (
            "Whether the check was actually run. It stays unverified unless a tool that ran it "
            "supplied the outcome; a structural improvement is not a result."
        ),
    },
    revision={
        **_STRING,
        "description": (
            "The revision the result belongs to. A result from another revision is not evidence "
            "about this one."
        ),
    },
    source={**_STRING, "description": "What produced the result, for example a test command."},
    observed_at=_STRING,
)


_TRANSFORMATION = _object(
    target={**_STRING, "description": "The exact path or symbol the change applies to."},
    preconditions={
        "type": "array",
        "items": _STRING,
        "maxItems": 6,
        "description": "What must already hold before the first step is safe.",
    },
    sequence={
        "type": "array",
        "items": _STRING,
        "maxItems": 8,
        "description": "Small ordered steps, each leaving the code working.",
    },
    preserved_behavior={
        **_STRING,
        "description": "The observable behavior that must be identical afterwards.",
    },
    verification_command={
        **_STRING,
        "description": "The check that would establish the behavior was preserved.",
    },
    rollback={**_STRING, "description": "How to undo the change if the check fails."},
    result=_VERIFICATION_RESULT,
)


_TRANSFORMATION["required"] = [n for n in _TRANSFORMATION["required"] if n != "result"]


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
    transformation=_TRANSFORMATION,
)


_RECOMMENDATION["required"] = [n for n in _RECOMMENDATION["required"] if n != "transformation"]


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
