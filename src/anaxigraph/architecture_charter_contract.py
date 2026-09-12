"""Strict result contract for the agent-funded Living Architecture Charter."""

from __future__ import annotations

import json
import re
from typing import Any

from anaxigraph.semantic_contract import SemanticAnalysisError, SemanticResult, _validate_schema

ARCHITECTURE_CHARTER_VERSION = "architecture-charter-v1"
CAPABILITY_BRIEF_VERSION = "capability-brief-v1"


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
_CLAIM = _object(
    statement=_STRING,
    evidence=_EVIDENCE,
    counter_evidence=_STRINGS,
    confidence=_CONFIDENCE,
)
_NAMED_CLAIM = _object(
    key=_STRING,
    name=_STRING,
    statement=_STRING,
    related=_STRINGS,
    entry_points=_STRINGS,
    evidence=_EVIDENCE,
    counter_evidence=_STRINGS,
    confidence=_CONFIDENCE,
    owner_scope={
        **_STRING,
        "description": (
            "The area or subsystem that owns this rule, when the evidence names one. Leave it "
            "out when ownership is unclear rather than inferring it from a file path."
        ),
    },
)
# Optional: claims recorded before ownership existed stay valid and are not re-requested.
_NAMED_CLAIM["required"] = [n for n in _NAMED_CLAIM["required"] if n != "owner_scope"]

_DEFINITION = _object(
    term=_STRING,
    meaning=_STRING,
    scope={
        **_STRING,
        "description": "Where this meaning holds. One term may mean different things elsewhere.",
    },
    evidence=_EVIDENCE,
    distinct_from={
        "type": "array",
        "items": _STRING,
        "maxItems": 6,
        "description": (
            "Other scopes that use the same term for a different thing. Recording the difference "
            "keeps a deliberate distinction from being merged away."
        ),
    },
)
_UNKNOWN = _object(question=_STRING, why_it_matters=_STRING, evidence_needed=_EVIDENCE)
_CONFLICT = _object(
    claim=_STRING,
    documentation_evidence=_EVIDENCE,
    code_evidence=_EVIDENCE,
    status={"type": "string", "enum": ["open", "explained", "resolved"]},
)

CAPABILITY_BRIEF_SCHEMA: dict[str, Any] = _object(
    contract_version={"type": "string", "enum": [CAPABILITY_BRIEF_VERSION]},
    purpose=_STRING,
    actors=_STRINGS,
    observable_capabilities=_STRINGS,
    user_journeys=_STRINGS,
    external_interfaces=_STRINGS,
    non_functional_requirements=_STRINGS,
    compatibility_obligations=_STRINGS,
    non_goals=_STRINGS,
    unknowns=_STRINGS,
    evidence=_EVIDENCE,
    confidence=_CONFIDENCE,
)

ARCHITECTURE_CHARTER_SCHEMA: dict[str, Any] = _object(
    contract_version={"type": "string", "enum": [ARCHITECTURE_CHARTER_VERSION]},
    purpose=_CLAIM,
    actors=_array(_NAMED_CLAIM),
    capabilities=_array(_NAMED_CLAIM),
    responsibilities=_array(_NAMED_CLAIM),
    execution_flows=_array(_NAMED_CLAIM),
    public_contracts=_array(_NAMED_CLAIM),
    invariants=_array(_NAMED_CLAIM),
    extension_points=_array(_NAMED_CLAIM),
    patterns=_array(_NAMED_CLAIM),
    coherence_concerns=_array(_NAMED_CLAIM),
    unknowns=_array(_UNKNOWN),
    conflicts=_array(_CONFLICT),
    capability_brief=CAPABILITY_BRIEF_SCHEMA,
    confidence=_CONFIDENCE,
    evidence=_EVIDENCE,
    definitions={
        "type": "array",
        "items": _DEFINITION,
        "maxItems": 24,
        "description": (
            "Terms whose meaning is scoped. Record one only when the evidence establishes it; "
            "ask for the missing domain knowledge instead of inventing a meaning from names."
        ),
    },
)
# Optional: charters saved before scoped definitions stay valid.
ARCHITECTURE_CHARTER_SCHEMA["required"] = [
    n for n in ARCHITECTURE_CHARTER_SCHEMA["required"] if n != "definitions"
]

_INTERNAL_PATH = re.compile(
    r"(?:^|\W)(?:src/|tests?/|packages?/|[\w.-]+\.(?:py|js|jsx|ts|tsx|rs|go|java))(?:$|\W)",
    re.IGNORECASE,
)


def is_architecture_charter_request(request: dict[str, Any]) -> bool:
    kind = str(request.get("analysis_kind") or "")
    return request.get("scope_type") == "repository" and kind.startswith("synthesis")


def validated_architecture_charter(
    value: Any,
    request: dict[str, Any],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SemanticResult:
    _validate_schema(value, ARCHITECTURE_CHARTER_SCHEMA, "architecture charter")
    brief = dict(value["capability_brief"])
    brief.pop("compatibility_obligations", None)
    leaked = _INTERNAL_PATH.search(json.dumps(brief, ensure_ascii=False))
    if leaked:
        raise SemanticAnalysisError(
            "capability brief contains an internal file or package identity; describe behavior instead"
        )
    return SemanticResult(
        value=value,
        confidence=float(value["confidence"]),
        evidence=tuple(str(item)[:2_000] for item in value["evidence"][:100]),
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
    )


def compact_architecture_charter(value: dict[str, Any]) -> dict[str, Any]:
    """Bound a partial Charter while retaining every reasoning category.

    The categories come from the schema rather than a list kept beside it. A hand-written
    list cannot know about a section added later, and the one that used to be here silently
    dropped scoped definitions from every reduction after they were introduced. Deriving the
    keys means a new section is carried through compaction the moment the schema declares it.
    """

    keys = tuple(ARCHITECTURE_CHARTER_SCHEMA["properties"])
    return {
        key: value[key][:20] if isinstance(value.get(key), list) else value.get(key)
        for key in keys
        if key in value
    }
