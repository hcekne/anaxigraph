from __future__ import annotations

from anaxigraph.agent_decision_handoff_language import (
    ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
    VERIFICATION_LANGUAGE_VERSION,
    comparison_explanation,
    constraint_item_explanation,
    constraints_explanation,
    decision_explanation,
    placement_explanation,
    semantic_file_explanation,
    verification_explanation,
)


def test_machine_decision_status_becomes_a_direct_evidence_summary():
    result = decision_explanation(
        "semantic_and_reviewed",
        selected_modules=2,
        semantic_modules=2,
        reviewed_patterns=3,
    )

    assert result["version"] == ARCHITECTURE_HANDOFF_LANGUAGE_VERSION
    assert result["conclusion"].startswith("This recommendation uses current module meaning")
    assert result["what_anaxigraph_used"] == [
        "2 module(s) were selected for the coding goal.",
        "2 selected module(s) had current semantic understanding.",
        "3 independently reviewed pattern evaluation(s) were included.",
    ]
    assert "not permission to edit beyond" in result["limits"][0]


def test_placement_explanation_says_where_to_start_and_when_to_rescope():
    result = placement_explanation(
        {
            "preferred_path": "src/service.py",
            "guidance": "Add service behavior behind Service.run.",
            "architecture_role": "Owns service orchestration.",
            "local_precedents": ["src/peer_service.py"],
        }
    )

    assert result["conclusion"] == "Start this change in src/service.py."
    assert result["what_to_do"] == "Add service behavior behind Service.run."
    assert result["examples_to_follow"] == ["src/peer_service.py"]
    assert "instead of widening it silently" in result["how_to_check"][1]


def test_constraints_explain_behavior_to_preserve_without_claiming_missing_means_none():
    item = {
        "path": "src/service.py",
        "public_contracts": ["Service.run keeps its result shape."],
        "invariants": ["Every configured provider remains selectable."],
        "risks": ["Changing the result shape breaks callers."],
    }
    explanation = constraint_item_explanation(item)

    assert explanation["conclusion"].startswith("Keep the recorded behavior")
    assert explanation["what_must_stay_true"] == [
        "Service.run keeps its result shape.",
        "Every configured provider remains selectable.",
    ]
    missing = constraints_explanation([])
    assert "Do not assume there are no constraints" in missing["what_to_do"]


def test_verification_explanation_turns_the_baseline_protocol_into_steps():
    result = verification_explanation(
        {
            "focused_test_paths": ["tests/test_service.py"],
            "post_change_baseline": {"snapshot_id": 9},
        }
    )

    assert result["version"] == VERIFICATION_LANGUAGE_VERSION
    assert "has not compared a new scan yet" in result["conclusion"]
    assert result["what_to_do"][0] == "Run the focused tests: tests/test_service.py."
    assert "anaxigraph update" in result["what_to_do"][1]
    assert "does not by itself prove" in result["what_it_cannot_prove"]


def test_comparison_explanation_does_not_call_no_rescan_an_unchanged_result():
    result = comparison_explanation(
        {
            "status": "rescan_required",
            "summary": "Both packets use snapshot 9. Run a scan.",
            "changes": {
                "modules": {"newly_tracked": [], "no_longer_tracked": [], "changed": []},
                "findings": {"newly_reported": [], "no_longer_reported": []},
                "patterns": {"newly_reported": [], "no_longer_reported": [], "changed": []},
            },
            "interpretation": "No post-change evidence exists yet.",
        }
    )

    assert result["what_anaxigraph_saw"] == [
        "No newer snapshot was available, so no post-change comparison was possible."
    ]
    assert result["what_to_do"].startswith("Run a new scan")


def test_semantic_file_explanation_labels_raw_advice_as_input_not_authorization():
    result = semantic_file_explanation(
        "src/service.py",
        {
            "status": "current",
            "confidence": 0.86,
            "architecture_role": "Owns service orchestration.",
            "placement_guidance": "Add service behavior behind Service.run.",
        },
    )

    assert result["version"] == "semantic-file-explanation-v1"
    assert result["conclusion"] == ("AnaxiGraph has a current AI interpretation of src/service.py.")
    assert result["evidence_strength"] == {
        "value": 0.86,
        "meaning": (
            "Support for this AI interpretation is strong. This measures its evidence, not the "
            "quality of the code."
        ),
    }
    assert "early AI notes, not instructions" in result["how_to_use_the_raw_fields"]
    assert "checks those notes against repository evidence" in result["how_to_use_the_raw_fields"]
    assert "architecture_decision" in result["how_to_use_the_raw_fields"]
