"""Measure current pattern intelligence against a bounded calibration manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from anaxigraph.pattern_calibration_metrics import calibration_report
from anaxigraph.pattern_calibration_models import (
    PatternCalibrationCase,
    PatternCalibrationManifest,
)
from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.pattern_query import PatternEvaluationQuery

CandidateReader = Callable[[PatternCandidateQuery], dict[str, Any]]
EvaluationReader = Callable[[PatternEvaluationQuery], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PatternCalibrationObservation:
    case_id: str
    plan_ready: bool
    candidate: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    snapshot_ids: tuple[int, ...]


def calibrate_patterns(
    manifest: PatternCalibrationManifest,
    *,
    candidates: CandidateReader,
    evaluations: EvaluationReader,
) -> dict[str, Any]:
    observations = tuple(
        _observe_case(case, candidates=candidates, evaluations=evaluations)
        for case in manifest.cases
    )
    return evaluate_pattern_calibration(manifest, observations)


def evaluate_pattern_calibration(
    manifest: PatternCalibrationManifest,
    observations: tuple[PatternCalibrationObservation, ...],
) -> dict[str, Any]:
    by_id = {item.case_id: item for item in observations}
    if len(by_id) != len(observations):
        raise ValueError("pattern calibration observation ids must be unique")
    unknown = set(by_id) - {case.case_id for case in manifest.cases}
    if unknown:
        raise ValueError(f"unknown pattern calibration observations: {sorted(unknown)}")
    outcomes = [_case_outcome(case, by_id.get(case.case_id)) for case in manifest.cases]
    return calibration_report(manifest, outcomes)


def _observe_case(
    case: PatternCalibrationCase,
    *,
    candidates: CandidateReader,
    evaluations: EvaluationReader,
) -> PatternCalibrationObservation:
    candidate_result = candidates(
        PatternCandidateQuery(
            pattern=case.pattern,
            target=case.target,
            selection="all",
            limit=1,
            include_evidence=True,
        )
    )
    evaluation_result = evaluations(
        PatternEvaluationQuery(
            pattern=case.pattern,
            target=case.target,
            limit=1,
            include_evidence=True,
        )
    )
    snapshots = {
        int(value)
        for value in (candidate_result.get("snapshot_id"), evaluation_result.get("snapshot_id"))
        if value is not None
    }
    return PatternCalibrationObservation(
        case_id=case.case_id,
        plan_ready=bool(candidate_result.get("plan_ready")),
        candidate=_first_item(candidate_result),
        evaluation=_first_item(evaluation_result),
        snapshot_ids=tuple(sorted(snapshots)),
    )


def _first_item(result: dict[str, Any]) -> dict[str, Any] | None:
    items = result.get("items")
    if not isinstance(items, list) or not items:
        return None
    return items[0] if isinstance(items[0], dict) else None


def _case_outcome(
    case: PatternCalibrationCase,
    observation: PatternCalibrationObservation | None,
) -> dict[str, Any]:
    candidate, evaluation = _observation_values(observation)
    selected = _selected(candidate)
    candidate_correct = selected == case.expected_relevant
    checks, rating_passed = _rating_result(case, evaluation)
    complete = _case_complete(case, observation, evaluation)
    review_verdict, review_issues, provenance = _review_values(evaluation)
    passed = all((candidate_correct, rating_passed is not False, complete))
    return {
        "id": case.case_id,
        "category": case.category,
        "expected_relevant": case.expected_relevant,
        "selected": selected,
        "candidate_correct": candidate_correct,
        "candidate_reason": _candidate_reason(candidate),
        "false_positive_cause": _false_positive_cause(case),
        "rating_expected": case.expects_rating,
        "rating_passed": rating_passed,
        "checks": checks,
        "confidence": _score(evaluation, "confidence"),
        "review_verdict": review_verdict,
        "review_issues": review_issues,
        "provenance": provenance,
        "snapshots": list(observation.snapshot_ids) if observation else [],
        "complete": complete,
        "passed": passed,
    }


def _observation_values(
    observation: PatternCalibrationObservation | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if observation is None:
        return None, None
    return observation.candidate, observation.evaluation


def _selected(candidate: dict[str, Any] | None) -> bool:
    return bool(candidate and candidate.get("selected_for_evaluation"))


def _rating_result(
    case: PatternCalibrationCase,
    evaluation: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], bool | None]:
    if not case.expects_rating:
        return [], None
    checks = _rating_checks(case, evaluation)
    if evaluation is None:
        return checks, None
    return checks, all(item["passed"] for item in checks)


def _case_complete(
    case: PatternCalibrationCase,
    observation: PatternCalibrationObservation | None,
    evaluation: dict[str, Any] | None,
) -> bool:
    if observation is None or not observation.plan_ready:
        return False
    return not case.expects_rating or evaluation is not None


def _review_values(
    evaluation: dict[str, Any] | None,
) -> tuple[str, list[Any], dict[str, Any]]:
    if evaluation is None:
        return "", [], {}
    review = evaluation.get("review", {})
    issues = evaluation.get("details", {}).get("review_issues", [])
    provenance = evaluation.get("provenance", {})
    return (
        str(review.get("verdict") or ""),
        issues if isinstance(issues, list) else [],
        provenance if isinstance(provenance, dict) else {},
    )


def _candidate_reason(candidate: dict[str, Any] | None) -> str:
    return str(candidate.get("reason") or "unknown") if candidate else "not_eligible"


def _false_positive_cause(case: PatternCalibrationCase) -> str:
    return case.false_positive_cause or case.category


def _rating_checks(
    case: PatternCalibrationCase, evaluation: dict[str, Any] | None
) -> list[dict[str, Any]]:
    checks = []
    actual_presence = evaluation.get("presence") if evaluation else None
    if case.presence:
        checks.append(_choice_check("presence", case.presence, actual_presence))
    actual_recommendation = evaluation.get("recommendation") if evaluation else None
    if case.recommendations:
        checks.append(_choice_check("recommendation", case.recommendations, actual_recommendation))
    for expected in case.scores:
        actual = _score(evaluation, expected.dimension)
        distance = _range_distance(actual, expected.minimum, expected.maximum)
        checks.append(
            {
                "metric": expected.dimension,
                "expected": [expected.minimum, expected.maximum],
                "actual": actual,
                "passed": distance == 0,
                "distance": distance,
            }
        )
    if case.review_verdicts:
        verdict = (evaluation or {}).get("review", {}).get("verdict")
        checks.append(_choice_check("review_verdict", case.review_verdicts, verdict))
    return checks


def _choice_check(metric: str, expected: tuple[str, ...], actual: Any) -> dict[str, Any]:
    return {
        "metric": metric,
        "expected": list(expected),
        "actual": actual,
        "passed": actual in expected,
        "distance": 0 if actual in expected else 100,
    }


def _score(evaluation: dict[str, Any] | None, dimension: str) -> int | None:
    value = (evaluation or {}).get("scores", {}).get(dimension)
    return int(value) if isinstance(value, int) else None


def _range_distance(actual: int | None, minimum: int, maximum: int) -> int:
    if actual is None:
        return 100
    if actual < minimum:
        return minimum - actual
    return max(0, actual - maximum)
