"""Functional exploration preserves independent alternatives and its blind boundary."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from fresh_eyes_functional_fixtures import functional_result
from fresh_eyes_support import prepared_review

from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_fresh_eyes_designs import design_observations
from anaxigraph.semantic_fresh_eyes_functional import (
    capability_projection,
    functional_scope_packet,
)
from anaxigraph.semantic_fresh_eyes_v2_contract import validate_functional


def test_functional_projection_withholds_implementation_evidence():
    brief = {
        "purpose": "Help people complete work",
        "observable_capabilities": ["Run tasks"],
        "source": "src/private_canary.py",
        "evidence": ["secret_canary.py"],
        "module_names": ["InternalManager"],
        "current_topology": {"node": "private"},
    }
    projected = capability_projection(brief)
    assert "source" not in projected and "module_names" not in projected
    assert "private" not in str(projected) and "canary" not in str(projected)
    assert projected["required_capabilities"][0]["statement"] == "Run tasks"
    with pytest.raises(SemanticAnalysisError, match="internal source identity"):
        capability_projection({"purpose": "Read src/private_canary.py"})


def test_projection_identity_ignores_order_and_duplicate_requirements():
    before = {
        "purpose": "Deliver work",
        "observable_capabilities": ["Run work", "Keep history"],
        "non_functional_requirements": ["Respect cancellation", "Keep errors visible"],
    }
    reordered = deepcopy(before)
    reordered["observable_capabilities"] = ["Keep history", "Run work", "Keep history", ""]
    reordered["non_functional_requirements"].reverse()
    assert capability_projection(before) == capability_projection(reordered)


def test_functional_review_retains_three_alternatives_at_each_level(repository, database):
    review = prepared_review(repository, database)
    work = review.run_until_complete()
    status = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    assert status["ready"] and status["protocol_version"] == "fresh-eyes-recipe-v2"
    assert {item["scope"]["level"] for item in status["scope_reviews"]} == {
        "product",
        "capability",
        "subsystem",
    }
    assert status["counts"] == {
        "total_scopes": 3,
        "completed_scopes": 3,
        "expected_alternatives": 9,
        "retained_alternatives": 9,
    }
    assert len([kind for _executor, kind in work if kind == "fresh_proposal"]) == 9
    assert all(item["alternative_count"] == 3 for item in status["scope_reviews"])
    assert not status["recommendations"] and status["comparison"] is None
    assert status["isolation"]["status"] == "unverified"
    for claim in review.claims:
        request = claim.get("request") or {}
        if request.get("protocol_version") == "fresh-eyes-recipe-v2":
            assert request["information_boundary"]["mode"] == "implementation_blind"
            assert (
                not {"source", "current_system", "comparison", "reference_design"} & request.keys()
            )
    selected = review.engine.fresh_eyes_status(
        review.repository_id, review.config.semantic, scope_id="retrieval"
    )
    subsystem = next(item for item in selected["scope_reviews"] if item["scope_id"] == "retrieval")
    assert all(item["design"]["components"] for item in subsystem["alternatives"])
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT sd.id,sd.value_json FROM semantic_scope_states ss JOIN semantic_documents sd "
            "ON sd.id=ss.context_document_id WHERE ss.scope_type='repository' AND ss.status='current'"
        ).fetchone()
        charter = json.loads(row["value_json"])
        charter["capability_brief"]["observable_capabilities"].append(
            "Preserve delegated cancellation"
        )
        connection.execute(
            "UPDATE semantic_documents SET value_json=? WHERE id=?",
            (json.dumps(charter), row["id"]),
        )
    changed = review.engine.start_fresh_eyes_review(review.repository_id, repository, review.config)
    assert not changed["review"]["ready"]
    assert changed["review"]["review_generation"] == 2
    assert changed["review"]["functional_brief"] is None
    historic = review.engine.fresh_eyes_status(
        review.repository_id, review.config.semantic, generation=1
    )
    assert historic["counts"]["retained_alternatives"] == 9


def test_blind_comparison_cannot_discard_an_alternative():
    packet = _hierarchy_packet()
    scope = functional_scope_packet(functional_result(packet), "product")
    request = {
        "analysis_kind": "fresh_comparison",
        "protocol_version": "fresh-eyes-recipe-v2",
        "functional_stage": "comparison",
        "functional_scope": scope,
        "alternatives": [{"id": f"alternative:{i}"} for i in range(3)],
    }
    result = functional_result(request)
    validate_functional(result, request)
    result["retained_alternative_ids"].pop()
    with pytest.raises(SemanticAnalysisError, match="retain every alternative"):
        validate_functional(result, request)


def test_repeated_designs_are_retained_without_claiming_material_diversity():
    request = _comparison_packet()
    original = deepcopy(request["alternatives"][0]["design"])
    request["alternatives"][1]["design"] = deepcopy(original)
    result = functional_result(request)
    with pytest.raises(SemanticAnalysisError, match="convergence limitation"):
        validate_functional(result, request)
    result["diversity"]["status"] = "partial_convergence"
    assert validate_functional(result, request).value["retained_alternative_ids"] == [
        item["id"] for item in request["alternatives"]
    ]
    request["alternatives"][2]["design"] = deepcopy(original)
    with pytest.raises(SemanticAnalysisError, match="All exact repeated"):
        validate_functional(result, request)
    result["diversity"]["status"] = "converged"
    result["diversity"]["unexplored_directions"] = ["Investigate different control semantics"]
    assert validate_functional(result, request).value == result


def test_equal_graph_shapes_can_have_materially_different_control_and_failure_semantics():
    request = _comparison_packet()
    second, third = request["alternatives"][1:]
    third["design"]["components"] = deepcopy(second["design"]["components"])
    third["design"]["relationships"] = deepcopy(second["design"]["relationships"])
    third["design"].update(
        control_model="Pure transformations over immutable snapshots",
        state_ownership="Caller owns immutable values rather than shared mutable state",
        failure_isolation="Each value independently reports its failed transformation",
    )
    before = deepcopy(request)
    observations = design_observations(request["alternatives"])
    assert observations["exact_repeated_designs"] == []
    assert observations["shared_coarse_topology"] == [[second["id"], third["id"]]]
    assert request == before
    result = functional_result(request)
    result["diversity"]["differences"] = [
        "Identical connectivity supports different state, control and failure contracts"
    ]
    assert validate_functional(result, request).value == result
    result["assessments"][0]["failure_isolation"] = " "
    with pytest.raises(SemanticAnalysisError, match="failure isolation"):
        validate_functional(result, request)


@pytest.mark.parametrize("scope_id", ["scope:proposal:a", "scope%", "scope*", ""])
def test_functional_scope_ids_cannot_change_stage_selection(scope_id):
    request = _hierarchy_packet()
    value = functional_result(request)
    value["scopes"][-1]["id"] = scope_id
    with pytest.raises(SemanticAnalysisError, match="identities|pattern"):
        validate_functional(value, request)


def test_child_composition_keeps_uncertainty_instead_of_inventing_compatibility():
    hierarchy = functional_result(_hierarchy_packet())
    request = {
        "analysis_kind": "fresh_proposal",
        "functional_stage": "proposal",
        "protocol_version": "fresh-eyes-recipe-v2",
        "proposal_slot": "a",
        "functional_scope": functional_scope_packet(hierarchy, "retrieval"),
        "parent_alternatives": [{"id": "alternative:proposed-parent"}],
    }
    result = functional_result(request)
    result["compatible_parent_alternative_ids"] = []
    with pytest.raises(SemanticAnalysisError, match="composition"):
        validate_functional(result, request)
    result["design"]["unknowns"] = ["Parent composition needs a behavioral compatibility check"]
    assert validate_functional(result, request).value == result


def test_scope_revision_changes_only_when_relevant_functionality_changes():
    brief = functional_result(_hierarchy_packet())
    before = functional_scope_packet(brief, "retrieval")
    changed = deepcopy(brief)
    changed["scopes"].append(
        {**changed["scopes"][1], "id": "unrelated", "purpose": "Other behavior"}
    )
    assert functional_scope_packet(changed, "retrieval")["revision"] == before["revision"]
    changed["scopes"][2]["constraints"].append("Preserve cancellation")
    assert functional_scope_packet(changed, "retrieval")["revision"] != before["revision"]


def _hierarchy_packet():
    return {
        "functional_stage": "hierarchy",
        "protocol_version": "fresh-eyes-recipe-v2",
        "analysis_kind": "fresh_adjudication",
        "capability_projection": capability_projection(
            {"purpose": "Explain behavior", "observable_capabilities": ["Answer questions"]}
        ),
    }


def _comparison_packet():
    scope = functional_scope_packet(functional_result(_hierarchy_packet()), "product")
    request = {
        "analysis_kind": "fresh_comparison",
        "protocol_version": "fresh-eyes-recipe-v2",
        "functional_stage": "comparison",
        "functional_scope": scope,
    }
    request["alternatives"] = [
        {
            "id": f"alternative:{slot}",
            **functional_result({**request, "functional_stage": "proposal", "proposal_slot": slot}),
        }
        for slot in "abc"
    ]
    return request
