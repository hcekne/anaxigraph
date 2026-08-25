from __future__ import annotations

import copy
from pathlib import Path

import pytest

from anaxigraph.pattern_calibration import (
    PatternCalibrationObservation,
    calibrate_patterns,
    evaluate_pattern_calibration,
)
from anaxigraph.pattern_calibration_models import (
    load_pattern_calibration,
    pattern_calibration_manifest,
)
from anaxigraph.pattern_catalog import bundled_pattern_catalog


def _manifest_value():
    return {
        "contract_version": "pattern-calibration-v1",
        "name": "Calibration contract fixture",
        "catalog_version": bundled_pattern_catalog().catalog_version,
        "score_contract_version": "pattern-scores-v1",
        "review_contract_version": "pattern-review-v1",
        "thresholds": {
            "candidate_precision": 0.5,
            "candidate_recall": 0.5,
            "rating_pass_rate": 0.5,
            "maximum_confidence_brier": 0.2,
            "require_complete": True,
        },
        "cases": [
            {
                "id": "true-positive",
                "category": "correct_abstraction",
                "pattern": "strategy",
                "target": "module:src/strategy.py",
                "expected": {
                    "relevant": True,
                    "presence": ["present"],
                    "recommendations": ["retain", "no_action"],
                    "scores": {"conformance": [70, 100], "opportunity": [0, 40]},
                    "review_verdicts": ["approve", "revise"],
                },
            },
            {
                "id": "false-positive",
                "category": "incorrect_abstraction",
                "pattern": "strategy",
                "target": "module:src/simple.py",
                "false_positive_cause": "single_fixed_behavior",
                "expected": {"relevant": False},
            },
            {
                "id": "false-negative",
                "category": "low_cohesion",
                "pattern": "god-module",
                "target": "module:src/mixed.py",
                "expected": {"relevant": True},
            },
            {
                "id": "true-negative",
                "category": "justified_module",
                "pattern": "god-module",
                "target": "module:src/cohesive.py",
                "expected": {"relevant": False},
            },
        ],
    }


def _candidate(selected, reason="selected"):
    return {"selected_for_evaluation": selected, "reason": reason}


def _evaluation(*, conformance=82, opportunity=20, confidence=80, verdict="approve"):
    issues = []
    if verdict == "revise":
        issues = [{"kind": "score_consistency", "severity": "warning"}]
    return {
        "presence": "present",
        "recommendation": "retain",
        "scores": {
            "conformance": conformance,
            "opportunity": opportunity,
            "confidence": confidence,
        },
        "review": {"verdict": verdict},
        "details": {"review_issues": issues},
        "provenance": {
            "provider": "agent",
            "model": "runtime-model",
            "prompt_version": "semantic-v4",
        },
    }


def _observation(case_id, *, selected, evaluation=None, reason="selected", ready=True):
    return PatternCalibrationObservation(
        case_id,
        ready,
        _candidate(selected, reason),
        evaluation,
        (9,),
    )


def test_calibration_reports_candidate_rating_confidence_and_critique_metrics():
    manifest = pattern_calibration_manifest(_manifest_value())
    observations = (
        _observation("true-positive", selected=True, evaluation=_evaluation()),
        _observation("false-positive", selected=True),
        _observation("false-negative", selected=False, reason="sparse_plan_bound"),
        _observation("true-negative", selected=False, reason="no_positive_evidence"),
    )

    report = evaluate_pattern_calibration(manifest, observations)

    assert report["status"] == "pass"
    assert report["candidate"] == {
        "true_positive": 1,
        "false_positive": 1,
        "true_negative": 1,
        "false_negative": 1,
        "precision": 0.5,
        "recall": 0.5,
        "accuracy": 0.5,
        "false_positive_causes": {"single_fixed_behavior": 1},
    }
    assert report["ratings"]["pass_rate"] == 1
    assert report["ratings"]["confidence_brier"] == 0.04
    assert report["critique"]["disagreement_rate"] == 0
    assert report["provenance"]["models"] == {"agent:runtime-model": 1}
    assert {item["id"] for item in report["failures"]} == {
        "false-positive",
        "false-negative",
    }


def test_calibration_fails_bad_ranges_and_retains_critique_disagreement():
    value = _manifest_value()
    value["thresholds"]["rating_pass_rate"] = 1
    value["thresholds"]["maximum_confidence_brier"] = 0.2
    manifest = pattern_calibration_manifest(value)
    observations = (
        _observation(
            "true-positive",
            selected=True,
            evaluation=_evaluation(conformance=30, opportunity=85, confidence=90, verdict="revise"),
        ),
        _observation("false-positive", selected=False, reason="no_positive_evidence"),
        _observation("false-negative", selected=True),
        _observation("true-negative", selected=False, reason="no_positive_evidence"),
    )

    report = evaluate_pattern_calibration(manifest, observations)

    assert report["status"] == "fail"
    assert report["ratings"]["pass_rate"] == 0
    assert report["ratings"]["mean_score_range_error"] == 42.5
    assert report["ratings"]["confidence_brier"] == 0.81
    assert report["critique"]["disagreement_rate"] == 1
    assert report["critique"]["issue_kinds"] == {"score_consistency": 1}


def test_calibration_is_incomplete_until_expected_finalized_ratings_exist():
    manifest = pattern_calibration_manifest(_manifest_value())
    observations = tuple(
        _observation(case.case_id, selected=case.expected_relevant) for case in manifest.cases
    )

    report = evaluate_pattern_calibration(manifest, observations)

    assert report["status"] == "incomplete"
    assert report["complete"] is False
    assert report["ratings"]["evaluated"] == 0


def test_live_calibration_reader_uses_exact_bounded_queries():
    value = _manifest_value()
    value["cases"] = value["cases"][:1]
    value["thresholds"].update(candidate_precision=1, candidate_recall=1, rating_pass_rate=1)
    manifest = pattern_calibration_manifest(value)
    captured = {}

    def candidates(request):
        captured["candidate"] = request
        return {"snapshot_id": 9, "plan_ready": True, "items": [_candidate(True)]}

    def evaluations(request):
        captured["evaluation"] = request
        return {"snapshot_id": 9, "items": [_evaluation()]}

    report = calibrate_patterns(manifest, candidates=candidates, evaluations=evaluations)

    assert report["passed"] is True
    assert captured["candidate"].target == "module:src/strategy.py"
    assert captured["candidate"].selection == "all"
    assert captured["candidate"].limit == 1
    assert captured["evaluation"].include_evidence is True


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(contract_version="pattern-calibration-v2"), "contract_version"),
        (lambda value: value["thresholds"].update(candidate_recall=2), "candidate_recall"),
        (lambda value: value["cases"][0].update(pattern="not-a-card"), "pattern key"),
        (lambda value: value["cases"][0]["expected"].update(scores={"magic": [0, 1]}), "scores"),
        (lambda value: value["cases"].append(copy.deepcopy(value["cases"][0])), "unique"),
    ],
)
def test_calibration_manifest_is_strict_and_versioned(change, message):
    value = _manifest_value()
    change(value)

    with pytest.raises(ValueError, match=message):
        pattern_calibration_manifest(value)


def test_synthetic_and_real_repository_manifests_cover_required_failure_modes():
    root = Path(__file__).parents[1]
    paths = [
        root / "benchmarks/fixtures/pattern-calibration/manifest.json",
        root / "benchmarks/pattern-calibration/anaxigraph.json",
    ]
    expected = {
        "correct_abstraction",
        "incorrect_abstraction",
        "justified_module",
        "low_cohesion",
        "dynamic_dead_code_trap",
        "consolidation_false_positive",
        "migration_cost",
    }

    for path in paths:
        manifest = load_pattern_calibration(path)
        assert {case.category for case in manifest.cases} == expected
        assert len(manifest.cases) == 7
