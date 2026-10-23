"""Rehydrate implementation-free scoped review packets from canonical saved results."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.semantic_fresh_eyes_designs import design_observations
from anaxigraph.semantic_fresh_eyes_functional import (
    FUNCTIONAL_PROTOCOL,
    assert_functional,
    functional_boundary,
    functional_scope_packet,
    semantic_input_hash,
)
from anaxigraph.semantic_graph import SupersededSemanticJob

_CONTRACTS = {
    "hierarchy": (
        "Describe the required functionality at product, capability and functional-subsystem "
        "levels. Build a hierarchy of purpose, inputs, outputs, behavioral constraints and "
        "functional dependencies. This is required behavior, not a guess at existing modules, "
        "folders, services, frameworks or deployment. Include at least one scope at each level. "
        "Use opaque scope identities and mark inferred requirements and unknowns honestly. "
        "Retain every supplied observable capability. Never introduce implementation facts."
        " Group related capabilities into a concise initial hierarchy, normally 3–12 scopes "
        "and at most 24; cover all requirements without creating a scope for every source file."
    ),
    "proposal": (
        "Design a strong alternative for the supplied functional scope. Preserve its required "
        "behavior. Challenge the obvious design: choose responsibility boundaries, state "
        "ownership, interfaces and coordination deliberately. Explain contextual pros and cons "
        "and the obligations each component preserves. Define proposed nodes and typed edges. "
        "Names describe proposed responsibilities, not current code. A parent scope is a "
        "functional requirement, not the current implementation. Do not default to extra "
        "services, classes or layers without explaining the benefit and cost."
        " Explicitly describe control flow, data/state ownership and failure isolation; a "
        "different label or deployment count alone is not a different architecture."
        " Keep descriptions concise and use at most 12 proposed components and 30 edges."
        " For child scopes, name compatible proposed-parent alternative IDs and the parent "
        "contracts they require. Do not merge incompatible parents; if compatibility is unknown, "
        "say so explicitly in design unknowns."
    ),
    "comparison": (
        "Critically compare ALL supplied alternatives against the same required functionality. "
        "Assess functional fit, change isolation, justified complexity and operating constraints. "
        "Explain meaningful differences, shared blind spots and composition conflicts. Keep all "
        "alternatives and all their identities; do not replace them with a single reference "
        "design or a universal winner. Explain where responsibility, state ownership, interface "
        "obligations or coordination materially differ; renaming the same components is not a "
        "different architecture. If designs converge, report that limitation and missing design "
        "directions explicitly. Assess decomposition, control flow, data ownership and failure "
        "isolation for each alternative. Use the conservative design observations as prompts "
        "for investigation: equal topology can implement materially different semantics, and "
        "different topology can disguise the same architecture. Do not claim verified novelty. "
        "You have no current implementation to compare or defend."
    ),
    "review": (
        "Review the functional alternatives across every supplied scope. Explain useful design "
        "differences and conflicts between levels without collapsing to one architecture. "
        "Preserve alternative choices and unknowns. This is blind design exploration, not a "
        "refactor plan, current-code critique or permission to change source. Source-aware "
        "selection and migration occur later in Architecture Planning. Preserve reported "
        "convergence and unexplored directions; do not present three saved slots as proof "
        "that three materially different architectures were found."
    ),
}
_DIRECTIONS = {
    "a": "Explore direct behavior ownership with minimal coordination and explicit contracts.",
    "b": "Explore data/state ownership and transformation boundaries, beyond obvious objects or services.",
    "c": "Explore lifecycle/control and failure boundaries; justify any event or state coordination costs.",
    "d": "Explore a materially different composition around transformations and invariants.",
    "e": "Explore a different organization of lifecycles, transitions and extension points.",
}


def functional_request(database: Any, job: Any) -> dict[str, Any]:
    metadata = job["metadata"]
    stage = metadata["functional_stage"]
    manifest = metadata["input_manifest"]
    expected = semantic_input_hash(f"functional-{stage}-v2", job["prompt_version"], manifest)
    if expected != job["input_hash"]:
        raise SupersededSemanticJob("Functional review manifest no longer matches its job")
    request = {
        "analysis_kind": job["job_kind"],
        "protocol_version": FUNCTIONAL_PROTOCOL,
        "functional_stage": stage,
        "contract": _CONTRACTS[stage],
        "input_manifest": manifest,
        "information_boundary": functional_boundary(),
        "isolation_request": {
            "mode": "fresh_context",
            "repository_access": "disabled",
            "tools": "none",
            "external_execution_status": "unverified",
        },
    }
    with database.connect() as connection:
        _add_evidence(connection, request, metadata)
    assert_functional(request)
    return request


def _add_evidence(connection: Any, request: Any, metadata: Any) -> None:
    stage = request["functional_stage"]
    if stage == "hierarchy":
        request["capability_projection"] = metadata["capability_projection"]
        return
    brief = _document(connection, metadata["functional_brief_document_id"])["value"]
    if stage == "review":
        request["scope_ids"] = [scope["id"] for scope in brief["scopes"]]
        request["comparisons"] = [
            _document(connection, identifier)["value"]
            for identifier in metadata["comparison_document_ids"]
        ]
        return
    request["functional_scope"] = functional_scope_packet(brief, metadata["scope_id"])
    if stage == "proposal":
        request["proposal_slot"] = metadata["slot"]
        request["exploration_direction"] = _DIRECTIONS[metadata["slot"]]
        request["parent_alternatives"] = [
            _alternative(connection, identifier)
            for identifier in metadata.get("parent_proposal_document_ids", [])
        ]
    else:
        request["alternatives"] = [
            _alternative(connection, identifier) for identifier in metadata["proposal_document_ids"]
        ]
        request["design_observations"] = design_observations(request["alternatives"])


def _alternative(connection: Any, identifier: int) -> dict[str, Any]:
    document = _document(connection, identifier)
    return {"id": f"alternative:{document['input_hash']}", **document["value"]}


def _document(connection: Any, identifier: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT id,input_hash,value_json FROM semantic_document_values WHERE id=?", (identifier,)
    ).fetchone()
    if row is None:
        raise SupersededSemanticJob(f"Functional review result {identifier} is unavailable")
    return {
        "id": row["id"],
        "input_hash": row["input_hash"],
        "value": json.loads(row["value_json"]),
    }
