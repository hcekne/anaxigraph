from __future__ import annotations

import pytest

from anaxigraph.agent_decision import build_architecture_decision
from anaxigraph.agent_decision_verification import ARCHITECTURE_BASELINE_VERSION


def _module(
    *,
    recommendation="keep",
    counter=None,
    dead_code=None,
    structural_hash="structural-1",
    fan_in=4,
):
    return {
        "path": "src/service.py",
        "structural_hash": structural_hash,
        "fan_in": fan_in,
        "fan_out": 3,
        "declared_group": "services",
        "semantic": {
            "status": "current",
            "architecture_role": "Owns service orchestration.",
            "placement_guidance": "Add service behavior behind Service.run.",
            "extension_points": ["Service.run"],
            "public_contracts": ["Service.run keeps its result contract."],
            "invariants": ["Service.run returns a stable result shape."],
            "testing_guidance": ["Exercise Service.run through its public contract."],
            "risks": ["Changing result shape breaks callers."],
            "similar_modules": ["src/peer_service.py"],
            "consolidation_assessment": {
                "recommendation": recommendation,
                "score": 82,
                "rationale": "The modules have distinct ownership.",
                "candidates": ["src/peer_service.py"],
                "evidence": ["Responsibilities overlap."],
                "counter_evidence": counter or [],
            },
            "dead_code_candidates": dead_code or [],
        },
    }


def _pattern(*, opportunity=20, conformance=84, recommendation="retain"):
    return {
        "target": {"path": "src/service.py"},
        "pattern": {"key": "cohesive-module", "name": "Cohesive Module"},
        "presence": "present",
        "recommendation": recommendation,
        "rationale": "The responsibility and public contract align.",
        "scores": {
            "suitability": 90,
            "conformance": conformance,
            "opportunity": opportunity,
            "confidence": 88,
        },
        "plain_language": {
            "version": "pattern-explanation-v2",
            "conclusion": "Keep Cohesive Module in src/service.py; it fits this code.",
            "what_anaxigraph_saw": [
                "src/service.py already shows the main parts of Cohesive Module."
            ],
            "why_it_may_matter": "One clear responsibility and public contract stay together.",
            "what_to_do": "Keep this structure and preserve its public behavior.",
            "reasons_not_to_change_the_code": [
                "Splitting the module would separate code that changes together."
            ],
            "how_to_check": ["Keep existing callers and focused tests passing."],
            "independent_review": "A separate AI pass checked the result.",
        },
        "details": {
            "local_precedents": ["src/peer_service.py"],
            "risks": ["Do not broaden the contract."],
            "invariants": ["Existing callers keep working."],
        },
        "review": {"verdict": "approve", "confidence": 91},
        "provenance": {
            "provider": "agent",
            "model": "",
            "executor_model": "runtime-model",
            "prompt_version": "pattern-review-v1",
        },
    }


def test_architecture_decision_combines_placement_patterns_and_balanced_consolidation():
    module = _module(counter=["The public contracts intentionally differ."])

    result = build_architecture_decision(
        snapshot_id=9,
        primary_files=[module],
        interfaces=[{"path": "src/service.py", "name": "Service", "symbol_type": "class"}],
        tests=["tests/test_service.py"],
        findings=[{"id": 3, "stable_key": "finding-3"}],
        pattern_items=[_pattern()],
    )

    assert result["status"] == "semantic_and_reviewed"
    assert result["plain_language"]["version"] == "architecture-handoff-explanation-v2"
    assert "up-to-date AI descriptions" in result["plain_language"]["conclusion"]
    assert result["placement"]["preferred_path"] == "src/service.py"
    assert result["placement"]["local_precedents"] == ["src/peer_service.py"]
    assert result["placement"]["plain_language"]["conclusion"] == (
        "Start this change in src/service.py."
    )
    constraints = result["change_constraints"]
    assert constraints["status"] == "semantic"
    assert constraints["items"][0]["invariants"]
    assert constraints["items"][0]["plain_language"]["what_must_stay_true"]
    assert constraints["plain_language"]["conclusion"].startswith("Keep the listed behavior true")
    reviewed = result["patterns"]["items"][0]
    assert reviewed["role"] == "reuse"
    assert reviewed["plain_language"]["version"] == "pattern-explanation-v2"
    assert reviewed["plain_language"]["conclusion"].startswith("Keep Cohesive Module")
    assert reviewed["plain_language"]["reasons_not_to_change_the_code"]
    assert reviewed["review"] == {"verdict": "approve", "confidence": 91}
    assert reviewed["provenance"]["executor_model"] == "runtime-model"
    guide = result["patterns"]["reading_guide"]
    assert guide["ratings"]["conformance"].startswith("How much")
    assert "not code-quality grades" in guide["numbers"]
    assert result["consolidation"][0]["status"] == "keep_separate"
    assert result["consolidation"][0]["counter_evidence"]
    consolidation = result["consolidation"][0]["plain_language"]
    assert consolidation["version"] == "consolidation-explanation-v1"
    assert consolidation["conclusion"].startswith("Keep src/service.py separate")
    assert "not a code-quality grade" in consolidation["evidence_strength"]["meaning"]
    assert result["consolidation"][0]["context"]["change_coupling"]["status"] == "unavailable"
    baseline = result["verification"]["post_change_baseline"]
    assert baseline["contract_version"] == ARCHITECTURE_BASELINE_VERSION
    assert baseline["snapshot_id"] == 9
    assert baseline["finding_keys"] == ["finding-3"]
    assert result["verification"]["focused_test_paths"] == ["tests/test_service.py"]
    assert result["verification"]["semantic_test_guidance"][0]["guidance"]
    assert "has not compared a newer scan" in result["verification"]["plain_language"]["conclusion"]


def test_architecture_decision_suppresses_uncorroborated_dead_code_and_weak_merge_advice():
    candidate = {
        "path_or_symbol": "src/service.py:legacy_adapter",
        "confidence": 0.8,
        "rationale": "No static callers were observed.",
        "reachability_evidence": ["incoming references=0"],
        "counter_evidence": ["May be loaded from configuration."],
        "verification": "Inspect configured adapter names.",
    }
    module = _module(recommendation="merge", dead_code=[candidate])

    result = build_architecture_decision(
        snapshot_id=10,
        primary_files=[module],
        interfaces=[],
        tests=[],
        findings=[],
        pattern_items=[_pattern(opportunity=70, recommendation="improve_conformance")],
    )

    assert result["consolidation"][0]["status"] == "review"
    dead_code = result["dead_code"]
    assert dead_code["safe_removal_count"] == 0
    assert dead_code["items"][0]["status"] == "suppressed"
    assert dead_code["items"][0]["safe_to_remove"] is False
    assert "deterministic reachability" in dead_code["items"][0]["suppression_reasons"][0]
    assert dead_code["plain_language"]["summary"].startswith("AnaxiGraph found 1 item")
    explanation = dead_code["items"][0]["plain_language"]
    assert explanation["conclusion"].startswith("Do not delete")
    assert "does not authorize deletion" in explanation["deletion_rule"]


def test_module_dead_code_finding_does_not_corroborate_symbol_candidate():
    candidate = {
        "path_or_symbol": "src/service.py:legacy_adapter",
        "confidence": 0.8,
        "rationale": "No static callers were observed.",
        "reachability_evidence": ["incoming references=0"],
        "counter_evidence": [],
        "verification": "Inspect dynamic adapter lookups.",
    }
    finding = {
        "id": 4,
        "finding_type": "possible_dead_code",
        "affected_artifacts": ["src/service.py"],
        "evidence": ["incoming_static_relationships=0"],
    }

    result = build_architecture_decision(
        snapshot_id=11,
        primary_files=[_module(dead_code=[candidate])],
        interfaces=[],
        tests=[],
        findings=[finding],
        pattern_items=[],
    )

    items = result["dead_code"]["items"]
    assert items[0]["path_or_symbol"].endswith(":legacy_adapter")
    assert items[0]["status"] == "suppressed"
    assert items[1]["path_or_symbol"] == "src/service.py"
    assert items[1]["status"] == "deterministic_candidate"


def test_architecture_decision_compares_a_previous_baseline_after_a_rescan():
    previous = build_architecture_decision(
        snapshot_id=20,
        primary_files=[_module()],
        interfaces=[],
        tests=["tests/test_service.py"],
        findings=[{"stable_key": "finding-old"}],
        pattern_items=[_pattern()],
        repository_identity="https://example.test/repository.git",
        goal="Simplify the service boundary",
    )["verification"]["post_change_baseline"]

    result = build_architecture_decision(
        snapshot_id=21,
        primary_files=[_module(structural_hash="structural-2", fan_in=5)],
        interfaces=[],
        tests=["tests/test_service.py"],
        findings=[{"stable_key": "finding-new"}],
        pattern_items=[_pattern(opportunity=10, conformance=90)],
        repository_identity="https://example.test/repository.git",
        goal="Simplify the service boundary",
        verification_baseline=previous,
    )

    comparison = result["verification"]["post_change_comparison"]
    assert comparison["status"] == "changed"
    assert comparison["baseline_snapshot_id"] == 20
    assert comparison["current_snapshot_id"] == 21
    assert "observed" in comparison["summary"]
    module_change = comparison["changes"]["modules"]["changed"][0]
    assert module_change["path"] == "src/service.py"
    assert module_change["source_structure_changed"] is True
    assert module_change["fan_in"]["change"] == 1
    assert comparison["changes"]["findings"] == {
        "newly_reported": ["finding-new"],
        "no_longer_reported": ["finding-old"],
    }
    score_changes = comparison["changes"]["patterns"]["changed"][0]["score_changes"]
    assert score_changes["conformance"]["change"] == 6
    assert score_changes["opportunity"]["change"] == -10
    assert "does not call the change better or worse" in comparison["interpretation"]
    assert comparison["plain_language"]["version"] == "architecture-verification-explanation-v2"
    assert comparison["plain_language"]["what_anaxigraph_saw"] == [
        "AnaxiGraph found 1 file record that changed.",
        "AnaxiGraph found 2 findings that changed.",
        "AnaxiGraph found 1 AI-checked pattern result that changed.",
    ]


def test_architecture_decision_requires_a_new_snapshot_and_matching_goal_for_comparison():
    previous = build_architecture_decision(
        snapshot_id=30,
        primary_files=[_module()],
        interfaces=[],
        tests=[],
        findings=[],
        pattern_items=[],
        repository_identity="repository-a",
        goal="Change the service",
    )["verification"]["post_change_baseline"]

    same_snapshot = build_architecture_decision(
        snapshot_id=30,
        primary_files=[_module()],
        interfaces=[],
        tests=[],
        findings=[],
        pattern_items=[],
        repository_identity="repository-a",
        goal="Change the service",
        verification_baseline=previous,
    )["verification"]["post_change_comparison"]
    assert same_snapshot["status"] == "rescan_required"
    assert "Run a scan" in same_snapshot["summary"]

    different_goal = build_architecture_decision(
        snapshot_id=31,
        primary_files=[_module()],
        interfaces=[],
        tests=[],
        findings=[],
        pattern_items=[],
        repository_identity="repository-a",
        goal="Delete the service",
        verification_baseline=previous,
    )["verification"]["post_change_comparison"]
    assert different_goal["status"] == "incomparable"
    assert "different coding goal" in different_goal["summary"]


def test_architecture_decision_rejects_an_unknown_baseline_contract():
    with pytest.raises(ValueError, match="Unsupported previous verification baseline version"):
        build_architecture_decision(
            snapshot_id=40,
            primary_files=[_module()],
            interfaces=[],
            tests=[],
            findings=[],
            pattern_items=[],
            verification_baseline={
                "contract_version": "architecture-verification-baseline-v99",
                "snapshot_id": 39,
                "modules": [],
                "finding_keys": [],
                "patterns": [],
            },
        )
