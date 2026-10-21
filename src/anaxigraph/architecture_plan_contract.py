"""Strict architecture options, agent selection, diagrams and migration milestones."""

from __future__ import annotations

from typing import Any

PLAN_VERSION = "architecture-plan-v1"
DEFAULT_DIRECTION = "Preserve behavior, reuse sound existing boundaries, and reduce evidenced complexity. Prefer small reversible changes and avoid speculative infrastructure."
STR = {"type": "string", "maxLength": 4000}
STRINGS = {"type": "array", "items": STR, "maxItems": 30}


def obj(**properties: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


NODE = obj(key=STR, label=STR, responsibility=STR, paths=STRINGS, evidence=STRINGS)
EDGE = obj(source=STR, target=STR, label=STR, evidence=STRINGS)
GRAPH = obj(
    nodes={"type": "array", "items": NODE, "maxItems": 32},
    edges={"type": "array", "items": EDGE, "maxItems": 64},
    unknowns=STRINGS,
)
MILESTONE = obj(
    key=STR,
    title=STR,
    outcome=STR,
    owners=STRINGS,
    affected_contracts=STRINGS,
    depends_on=STRINGS,
    verification=STRINGS,
    rollback=STR,
    evidence=STRINGS,
)
OPTION = obj(
    key=STR,
    strategy={"type": "string", "enum": ["preserve", "evolve", "redesign"]},
    title=STR,
    summary=STR,
    benefits=STRINGS,
    costs=STRINGS,
    risks=STRINGS,
    evidence=STRINGS,
    target=GRAPH,
    milestones={"type": "array", "items": MILESTONE, "maxItems": 12},
)
PLAN_SCHEMA = obj(
    contract_version={"type": "string", "enum": [PLAN_VERSION]},
    summary=STR,
    direction=STR,
    assumptions=STRINGS,
    current=GRAPH,
    options={"type": "array", "items": OPTION, "minItems": 2, "maxItems": 4},
    selected_option=STR,
    selection_rationale=STR,
    disagreements=STRINGS,
    evidence=STRINGS,
    confidence={"type": "number", "minimum": 0, "maximum": 1},
)


def validate_plan_structure(value: Any) -> None:
    keys = [option["key"] for option in value["options"]]
    if len(set(keys)) != len(keys) or value["selected_option"] not in keys:
        raise ValueError("Architecture plan must select one uniquely named option")
    if not {"preserve", "evolve"}.issubset({option["strategy"] for option in value["options"]}):
        raise ValueError(
            "Architecture options must include preserving the design and incremental evolution"
        )
    for option in value["options"]:
        validate_graph(option["target"])
        validate_milestones(option["milestones"])
    validate_graph(value["current"])


def validate_graph(graph: Any) -> None:
    keys = [node["key"] for node in graph["nodes"]]
    if len(keys) != len(set(keys)) or any(
        edge[side] not in keys for edge in graph["edges"] for side in ("source", "target")
    ):
        raise ValueError("Architecture diagram has duplicate nodes or dangling relationships")


def validate_milestones(milestones: Any) -> None:
    completed: set[str] = set()
    for milestone in milestones:
        if milestone["key"] in completed or not set(milestone["depends_on"]).issubset(completed):
            raise ValueError(
                "Architecture milestones must have unique keys and earlier dependencies"
            )
        if not milestone["verification"]:
            raise ValueError("Architecture milestones must include verification")
        completed.add(milestone["key"])
