from __future__ import annotations

import pytest
from semantic_support import _agent_dossier

from anaxigraph.agent_decision import build_architecture_decision
from anaxigraph.agent_decision_payload import compact_architecture_decision
from anaxigraph.architecture_guidance import compact_guidance_projection, guidance_projection
from anaxigraph.reassessment_advice import reassessment_advice
from anaxigraph.semantic_contract import SemanticAnalysisError, validated_result
from anaxigraph.semantic_freshness import legacy_input_matches, semantic_digest
from anaxigraph.semantic_graph import _intent_fingerprint
from anaxigraph.semantic_taxonomy_contract import validated_agent_semantic_response
from anaxigraph.understandability import UNDERSTANDABILITY_VERSION, understandability_advice


def reader_task(**changes):
    return {
        "key": "change-calculation",
        "task": "Change the calculation while preserving its caller contract.",
        "status": "obstructed",
        "knowledge_sources": ["names", "interfaces", "tests"],
        "evidence": ["pkg/core.py::Calculator.calculate", "tests/test_core.py"],
        "obstacle": "The argument name does not identify which quantity the caller supplies.",
        "smallest_change": "Give the internal calculation argument a domain name; preserve public callers.",
        "expected_benefit": "A reader can identify the quantity without reconstructing every caller.",
        "migration_cost": "low",
        "counter_evidence": ["Keep keyword argument compatibility for existing callers."],
        "verification": "Run the calculation tests, including keyword callers and invalid inputs.",
        "confidence": 0.85,
        **changes,
    }


def assessment(*tasks):
    return {"contract_version": UNDERSTANDABILITY_VERSION, "tasks": list(tasks)}


def module(*tasks, path="pkg/core.py", status="current"):
    return {
        "path": path,
        "semantic": {"status": status, "understandability": assessment(*tasks)},
    }


def decision(files):
    return build_architecture_decision(
        snapshot_id=1, primary_files=files, interfaces=[], tests=[], findings=[], pattern_items=[]
    )


def effects(before, after):
    return reassessment_advice(
        {"module_changes": [{"path": "pkg/core.py", "before": before, "after": after}]},
        patterns=[],
        change_coupling={},
    )


def test_submission_preserves_task_evidence_and_requires_assessment():
    request = {"analysis_kind": "context", "path": "pkg/core.py", "detailed_reviews": True}
    dossier = _agent_dossier(request)
    dossier["understandability"] = assessment(reader_task())
    result = validated_agent_semantic_response(dossier, request)
    assert result.value["understandability"] == dossier["understandability"]
    del dossier["understandability"]
    with pytest.raises(SemanticAnalysisError, match="understandability"):
        validated_agent_semantic_response(dossier, request)
    legacy = validated_result(dossier, input_tokens=0, output_tokens=0)
    assert "understandability" not in legacy.value


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "perfect"},
        {"task": " "},
        {"key": " "},
        {"evidence": []},
        {"evidence": [" "]},
        {"counter_evidence": [" "]},
        {"knowledge_sources": []},
        {"verification": ""},
        {"smallest_change": ""},
        {"confidence": float("nan")},
        {"extra": "unsupported"},
    ],
)
def test_invalid_task_cannot_become_advice(changes):
    with pytest.raises(SemanticAnalysisError, match="understandability"):
        validated_result(
            {"summary": "Example", "understandability": assessment(reader_task(**changes))},
            input_tokens=0,
            output_tokens=0,
        )


def test_duplicate_task_keys_and_oversized_assessments_are_rejected():
    for tasks in ([reader_task(), reader_task()], [reader_task(key=str(i)) for i in range(4)]):
        with pytest.raises(SemanticAnalysisError, match="understandability"):
            validated_result(
                {"summary": "Example", "understandability": assessment(*tasks)},
                input_tokens=0,
                output_tokens=0,
            )


@pytest.mark.parametrize("status", ["pending_context", "stale", "not_started"])
def test_stale_tasks_are_withheld(status):
    result = understandability_advice([module(reader_task(), status=status)])
    assert result["status"] == "unknown"
    assert result["items"] == []


def test_unknown_and_legacy_assessments_never_mean_clear():
    for item in (
        module(),
        {"path": "legacy.py", "semantic": {"status": "current"}},
        module(reader_task(status="unknown", evidence=[])),
    ):
        assert understandability_advice([item])["status"] == "unknown"
    item = module(reader_task())
    item["semantic"]["understandability"]["contract_version"] = "older-policy"
    assert understandability_advice([item])["items"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "clear"},
        {"status": "unknown"},
        {"confidence": 0.4},
        {"migration_cost": "high"},
        {"migration_cost": "unknown"},
        {"counter_evidence": []},
    ],
)
def test_unjustified_or_expensive_changes_are_not_actionable(changes):
    assert not understandability_advice([module(reader_task(**changes))])["items"][0]["actionable"]


def test_task_relevance_and_cost_order_advice_without_a_quality_grade():
    files = [
        module(reader_task(task="Find serialization code.", migration_cost="medium"), path="a.py"),
        module(reader_task(), path="b.py"),
        module(reader_task(), path="c.py"),
    ]
    result = understandability_advice(files, "Change the calculation")
    assert [item["path"] for item in result["items"]] == ["b.py", "c.py", "a.py"]
    assert "score" not in result


def test_guidance_chooses_reader_improvement_at_its_actual_path():
    files = [module(path="unrelated.py"), module(reader_task())]
    files[1]["incoming_paths"] = ["reader.py"]
    files[1]["outgoing_paths"] = ["calculation.py"]
    plan = decision(files)
    result = guidance_projection(
        {"architecture_decision": plan, "primary_files": files},
        intent="improve",
        focus="",
        charter={},
    )
    advice = result["recommendation"]
    assert advice["action"] == "refactor"
    assert advice["starting_point"] == "pkg/core.py"
    assert advice["summary"] == reader_task()["smallest_change"]
    assert advice["verification"] == reader_task()["verification"]
    assert advice["reasons_not_to_change"] == reader_task()["counter_evidence"]
    assert result["impact_summary"]["target"] == "pkg/core.py"
    assert result["impact_summary"]["direct_callers"] == ["reader.py"]
    assert result["impact_summary"]["dependencies"] == ["calculation.py"]
    compact_guidance_projection(result)
    recommendation = result["recommendation"]
    assert recommendation["reader_task"]["evidence"]
    assert recommendation["reasons_not_to_change"]
    assert recommendation["verification"] == reader_task()["verification"]
    assert result["impact_summary"]["target"] == "pkg/core.py"
    compact = compact_architecture_decision(plan)["understandability"]
    assert compact["items"][0]["evidence"]
    assert compact["items"][0]["counter_evidence"]
    assert compact["items"][0]["verification"]


@pytest.mark.parametrize("intent", ["build", "improve"])
def test_build_placement_and_boundary_violations_keep_their_priority(intent):
    files = [module(reader_task())]
    context = {
        "architecture_decision": decision(files),
        "primary_files": files,
        "known_findings": [{"finding_type": "architecture_violation"}],
    }
    result = guidance_projection(context, intent=intent, focus="", charter={})
    assert "reader_task" not in result["recommendation"]


@pytest.mark.parametrize(
    ("old", "new", "classification"),
    [
        ("obstructed", "clear", "improved"),
        ("clear", "obstructed", "worsened"),
    ],
)
def test_reassessment_compares_the_same_task_and_labels_inference(old, new, classification):
    result = effects(module(reader_task(status=old)), module(reader_task(status=new)))
    item = next(item for item in result["effects"] if item["category"] == "understandability")
    assert item["classification"] == classification
    assert "not measured reader performance" in item["confidence"]["basis"]
    assert {value["detail"].split(":", 1)[0] for value in item["evidence"]} == {"before", "after"}


@pytest.mark.parametrize(
    "after",
    [
        module(),
        module(reader_task(status="clear", task="A different task.")),
        module(reader_task(status="clear", confidence=0.1)),
        module(reader_task(status="clear"), status="pending_context"),
    ],
)
def test_missing_or_incomparable_task_is_not_an_improvement(after):
    result = effects(module(reader_task()), after)
    assert result["counts"]["improvements"] == 0
    assert result["coverage"]["understandability"] == "insufficient_evidence"


def test_legacy_hash_cannot_bypass_the_new_policy():
    evidence = {"path": "old.py"}
    old = {
        "schema_version": "module-dossier-v4",
        "prompt_version": "v1",
        "provider": "agent",
        "model": "",
    }
    old["input_hash"] = semantic_digest(
        {
            "schema": old["schema_version"],
            "prompt": "v1",
            "provider": "agent",
            "model": "",
            **evidence,
        }
    )
    assert not legacy_input_matches(old, evidence, prompt_version="v1")


def test_reader_assessment_does_not_change_module_responsibility_identity():
    description = {"responsibilities": ["Calculate order totals."]}
    before = {**description, "understandability": assessment(reader_task())}
    after = {**description, "understandability": assessment(reader_task(status="clear"))}
    assert _intent_fingerprint(before) == _intent_fingerprint(after)


def test_matching_clear_tasks_are_retained_without_claiming_an_improvement():
    result = effects(module(reader_task(status="clear")), module(reader_task(status="clear")))
    item = next(item for item in result["effects"] if item["category"] == "understandability")
    assert item["classification"] == "coherent_no_change"
    assert result["counts"]["improvements"] == 0
