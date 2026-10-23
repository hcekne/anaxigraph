"""Deterministic functional alternatives for queue and isolation contract tests."""

from __future__ import annotations

from copy import deepcopy


def functional_result(request):
    stage = request["functional_stage"]
    if stage == "hierarchy":
        return _hierarchy(request)
    if stage == "proposal":
        return _proposal(request)
    if stage == "comparison":
        return _comparison(request)
    return {
        "contract_version": "functional-review-v2",
        "summary": "Retain the functional choices.",
        "reviewed_scope_ids": request["scope_ids"],
        "useful_differences": ["The alternatives place responsibility and state differently."],
        "composition_conflicts": ["Select compatible parent constraints during planning."],
        "unknowns": [],
        "confidence": 0.8,
        "evidence": request["scope_ids"],
    }


def _hierarchy(request):
    projection = request["capability_projection"]
    ids = [item["id"] for item in projection["required_capabilities"]]
    scope = {
        "inputs": ["A requested operation"],
        "outputs": ["The required result"],
        "constraints": projection["non_functional_requirements"],
        "dependencies": [],
        "origin": "inferred",
        "confidence": 0.8,
        "unknowns": [],
        "capability_ids": ids,
    }
    return {
        "contract_version": "functional-brief-v2",
        "purpose": projection["purpose"],
        "required_capabilities": deepcopy(projection["required_capabilities"]),
        "scopes": [
            {
                **scope,
                "id": "product",
                "parent_id": "",
                "level": "product",
                "purpose": projection["purpose"],
            },
            {
                **scope,
                "id": "understanding",
                "parent_id": "product",
                "level": "capability",
                "purpose": "Provide understandable evidence-backed knowledge.",
            },
            {
                **scope,
                "id": "retrieval",
                "parent_id": "understanding",
                "level": "subsystem",
                "purpose": "Retrieve the relevant explanation for a question.",
            },
        ],
        "confidence": 0.8,
        "evidence": ids,
    }


def _proposal(request):
    packet = request["functional_scope"]
    slot = request["proposal_slot"]
    count = ord(slot) - ord("a") + 1
    nodes = [
        {
            "key": f"responsibility-{i}",
            "name": f"Responsibility {i}",
            "responsibility": [
                "Own the complete behavior",
                "Transform information",
                "Coordinate requests",
                "Own state",
                "Enforce invariants",
            ][i],
            "contracts": ["Preserve the required behavior"],
        }
        for i in range(count)
    ]
    edges = [
        {
            "source": nodes[i - 1]["key"],
            "target": nodes[i]["key"],
            "relationship": "delegates",
            "rationale": "An explicit responsibility boundary",
        }
        for i in range(1, count)
    ]
    return {
        "contract_version": "functional-proposal-v2",
        "scope_id": packet["scope"]["id"],
        "brief_revision": packet["revision"],
        "design": {
            "summary": f"Alternative {slot}: {count} explicit responsibilities.",
            "components": nodes,
            "relationships": edges,
            "control_model": "Direct requests" if slot == "a" else "Explicit state transitions",
            "state_ownership": "Behavior owner" if slot == "a" else "Separate state owner",
            "failure_isolation": "Whole request" if slot == "a" else "Contract boundary",
            "information_flows": ["Request to owned behavior to result"],
            "boundary_rules": ["Consumers use declared contracts"],
            "operating_model": ["Use only justified deployment machinery"],
            "extension_strategy": ["Extend the owner of the relevant behavior"],
            "assumptions": [],
            "unknowns": [],
        },
        "pros": ["Responsibilities can change through explicit contracts"],
        "cons": ["Each boundary requires a clear behavioral agreement"],
        "parent_constraints": packet["scope"]["constraints"],
        "compatible_parent_alternative_ids": [
            item["id"] for item in request.get("parent_alternatives", [])
        ],
        "isolation": {
            "requested": "fresh_context",
            "status": "unverified",
            "note": "Fixture response does not attest execution isolation.",
        },
        "confidence": 0.8,
        "evidence": [packet["scope"]["id"]],
    }


def _comparison(request):
    packet = request["functional_scope"]
    ids = [item["id"] for item in request["alternatives"]]
    return {
        "contract_version": "functional-comparison-v2",
        "scope_id": packet["scope"]["id"],
        "brief_revision": packet["revision"],
        "summary": "Keep the different boundary choices.",
        "assessments": [
            {
                "alternative_id": key,
                "strengths": ["Clear ownership"],
                "weaknesses": ["Needs behavioral verification"],
                "functional_fit": "Preserves supplied requirements",
                "change_isolation": "Depends on enforcing the stated contract",
                "justified_complexity": "Compare boundary cost with change needs",
                "operating_constraints": "No unsupported infrastructure",
                "decomposition": "Compare the supplied responsibility boundaries",
                "control_flow": "Compare direct requests and explicit transitions",
                "data_ownership": "Compare behavior ownership and separate state ownership",
                "failure_isolation": "Compare request and contract failure boundaries",
                "confidence": 0.8,
            }
            for key in ids
        ],
        "retained_alternative_ids": ids,
        "diversity": {
            "status": "materially_different",
            "differences": ["Responsibility decomposition and ownership differ"],
            "limitations": ["Fixture exploration does not establish real-world novelty"],
            "unexplored_directions": [],
            "novelty": "unverified",
        },
        "disagreements": ["Different state ownership"],
        "composition_conflicts": [],
        "unknowns": [],
        "confidence": 0.8,
        "evidence": [packet["scope"]["id"]],
    }
