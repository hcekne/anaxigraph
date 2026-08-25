"""Aggregate candidate, rating, confidence, and critique calibration metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from anaxigraph.pattern_calibration_models import PatternCalibrationManifest

PATTERN_CALIBRATION_REPORT_VERSION = "pattern-calibration-report-v1"


def calibration_report(
    manifest: PatternCalibrationManifest,
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate = _candidate_metrics(outcomes)
    ratings = _rating_metrics(outcomes)
    complete = all(item["complete"] for item in outcomes)
    results = _threshold_results(manifest, candidate, ratings, complete)
    passed = all(results.values())
    return {
        "contract_version": PATTERN_CALIBRATION_REPORT_VERSION,
        "manifest": {
            "name": manifest.name,
            "fingerprint": manifest.fingerprint,
            "cases": len(manifest.cases),
        },
        "contracts": _contracts(manifest),
        "status": "pass" if passed else "incomplete" if not complete else "fail",
        "passed": passed,
        "complete": complete,
        "thresholds": {**_thresholds(manifest), "results": results},
        "candidate": candidate,
        "ratings": ratings,
        "critique": _critique_metrics(outcomes),
        "by_category": _category_metrics(outcomes),
        "provenance": _provenance(outcomes),
        "failures": [_failure(item) for item in outcomes if not item["passed"]],
    }


def _contracts(manifest: PatternCalibrationManifest) -> dict[str, str]:
    return {
        "calibration": manifest.contract_version,
        "catalog": manifest.catalog_version,
        "scores": manifest.score_contract_version,
        "review": manifest.review_contract_version,
    }


def _thresholds(manifest: PatternCalibrationManifest) -> dict[str, float | bool]:
    values = manifest.thresholds
    return {
        "candidate_precision": values.candidate_precision,
        "candidate_recall": values.candidate_recall,
        "rating_pass_rate": values.rating_pass_rate,
        "maximum_confidence_brier": values.maximum_confidence_brier,
        "require_complete": values.require_complete,
    }


def _candidate_metrics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(item["selected"] and item["expected_relevant"] for item in outcomes)
    fp = sum(item["selected"] and not item["expected_relevant"] for item in outcomes)
    tn = sum(not item["selected"] and not item["expected_relevant"] for item in outcomes)
    fn = sum(not item["selected"] and item["expected_relevant"] for item in outcomes)
    causes = Counter(
        item["false_positive_cause"]
        for item in outcomes
        if item["selected"] and not item["expected_relevant"]
    )
    return {
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "accuracy": _ratio(tp + tn, len(outcomes)),
        "false_positive_causes": dict(sorted(causes.items())),
    }


def _rating_metrics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    expected = [item for item in outcomes if item["rating_expected"]]
    checks = [check for item in expected for check in item["checks"]]
    evaluated = [item for item in expected if item["rating_passed"] is not None]
    passed = sum(item["rating_passed"] is True for item in expected)
    brier = [
        ((item["confidence"] or 0) / 100 - float(item["rating_passed"] is True)) ** 2
        for item in evaluated
    ]
    score_distances = [
        int(check["distance"])
        for check in checks
        if check["metric"] not in {"presence", "recommendation", "review_verdict"}
    ]
    return {
        "expected": len(expected),
        "evaluated": len(evaluated),
        "passed": passed,
        "pass_rate": _ratio(passed, len(expected)),
        "checks": len(checks),
        "checks_passed": sum(bool(check["passed"]) for check in checks),
        "mean_score_range_error": _mean(score_distances),
        "confidence_brier": _mean(brier),
    }


def _critique_metrics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = [item for item in outcomes if item["review_verdict"]]
    verdicts = Counter(item["review_verdict"] for item in reviewed)
    issue_kinds = Counter(
        str(issue.get("kind") or "unknown")
        for item in reviewed
        for issue in item["review_issues"]
        if isinstance(issue, dict)
    )
    disagreement = sum(
        item["review_verdict"] != "approve" or bool(item["review_issues"]) for item in reviewed
    )
    return {
        "reviewed": len(reviewed),
        "disagreement": disagreement,
        "disagreement_rate": _ratio(disagreement, len(reviewed)),
        "verdicts": dict(sorted(verdicts.items())),
        "issue_kinds": dict(sorted(issue_kinds.items())),
    }


def _category_metrics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in outcomes:
        grouped[item["category"]].append(item)
    return {
        category: {
            "cases": len(items),
            "candidate_correct": sum(item["candidate_correct"] for item in items),
            "ratings_passed": sum(item["rating_passed"] is True for item in items),
            "complete": sum(item["complete"] for item in items),
        }
        for category, items in sorted(grouped.items())
    }


def _provenance(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    models = Counter()
    prompts = Counter()
    snapshots = set()
    for item in outcomes:
        provenance = item["provenance"]
        if provenance:
            key = (
                f"{provenance.get('provider') or 'unknown'}:{provenance.get('model') or 'unknown'}"
            )
            models[key] += 1
            prompts[str(provenance.get("prompt_version") or "unknown")] += 1
        snapshots.update(item["snapshots"])
    return {
        "models": dict(sorted(models.items())),
        "prompt_versions": dict(sorted(prompts.items())),
        "snapshot_ids": sorted(snapshots),
    }


def _threshold_results(
    manifest: PatternCalibrationManifest,
    candidate: dict[str, Any],
    ratings: dict[str, Any],
    complete: bool,
) -> dict[str, bool]:
    values = manifest.thresholds
    return {
        "candidate_precision": _minimum(candidate["precision"], values.candidate_precision),
        "candidate_recall": _minimum(candidate["recall"], values.candidate_recall),
        "rating_pass_rate": _minimum(ratings["pass_rate"], values.rating_pass_rate),
        "maximum_confidence_brier": _maximum(
            ratings["confidence_brier"], values.maximum_confidence_brier
        ),
        "complete": complete or not values.require_complete,
    }


def _minimum(actual: float | None, expected: float) -> bool:
    return expected == 0 if actual is None else actual >= expected


def _maximum(actual: float | None, expected: float) -> bool:
    return actual is None or actual <= expected


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _mean(values: list[float] | list[int]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _failure(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "id",
            "category",
            "expected_relevant",
            "selected",
            "candidate_reason",
            "rating_passed",
            "checks",
            "complete",
        )
    }
