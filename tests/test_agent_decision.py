from __future__ import annotations

from anaxigraph.agent_decision import build_architecture_decision


def _module(*, recommendation="keep", counter=None, dead_code=None):
    return {
        "path": "src/service.py",
        "structural_hash": "structural-1",
        "fan_in": 4,
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


def _pattern(*, opportunity=20, recommendation="retain"):
    return {
        "target": {"path": "src/service.py"},
        "pattern": {"key": "cohesive-module", "name": "Cohesive Module"},
        "presence": "present",
        "recommendation": recommendation,
        "rationale": "The responsibility and public contract align.",
        "scores": {
            "suitability": 90,
            "conformance": 84,
            "opportunity": opportunity,
            "confidence": 88,
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
    assert result["placement"]["preferred_path"] == "src/service.py"
    assert result["placement"]["local_precedents"] == ["src/peer_service.py"]
    constraints = result["change_constraints"]
    assert constraints["status"] == "semantic"
    assert constraints["items"][0]["invariants"]
    reviewed = result["patterns"]["items"][0]
    assert reviewed["role"] == "reuse"
    assert reviewed["review"] == {"verdict": "approve", "confidence": 91}
    assert reviewed["provenance"]["executor_model"] == "runtime-model"
    assert result["consolidation"][0]["status"] == "keep_separate"
    assert result["consolidation"][0]["counter_evidence"]
    assert result["consolidation"][0]["context"]["change_coupling"]["status"] == "unavailable"
    baseline = result["verification"]["post_change_baseline"]
    assert baseline["snapshot_id"] == 9
    assert baseline["finding_keys"] == ["finding-3"]
    assert result["verification"]["focused_test_paths"] == ["tests/test_service.py"]
    assert result["verification"]["semantic_test_guidance"][0]["guidance"]


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
