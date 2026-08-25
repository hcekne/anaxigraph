"""Plain-language pattern evaluation contract for people and coding agents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PATTERN_LANGUAGE_VERSION = "pattern-explanation-v1"


def pattern_explanation(
    evaluation: Mapping[str, Any],
    review: Mapping[str, Any],
    target: Mapping[str, Any],
    pattern: Mapping[str, Any],
) -> dict[str, Any]:
    """Explain one finalized pattern decision without making the scores the story."""

    name = str(pattern.get("name") or pattern.get("key") or "this pattern")
    target_name = _target_name(target)
    recommendation = str(evaluation.get("recommendation") or "insufficient_evidence")
    presence = str(evaluation.get("presence") or "uncertain")
    return {
        "version": PATTERN_LANGUAGE_VERSION,
        "conclusion": _conclusion(name, target_name, recommendation),
        "what_anaxigraph_saw": [
            _presence_sentence(name, target_name, presence),
            *_strings(evaluation.get("evidence"), limit=5),
        ],
        "why_it_may_matter": _reason(evaluation),
        "what_to_do": _action(name, target_name, recommendation),
        "reasons_not_to_change_the_code": _reasons_for_caution(evaluation, recommendation),
        "how_to_check": _verification(evaluation, target_name, recommendation),
        "score_meanings": _score_meanings(evaluation.get("scores"), name),
        "independent_review": _review_sentence(review),
    }


def _target_name(target: Mapping[str, Any]) -> str:
    return str(
        target.get("path")
        or target.get("qualified_name")
        or target.get("label")
        or target.get("key")
        or "this code"
    )


def _conclusion(name: str, target: str, recommendation: str) -> str:
    return {
        "retain": f"Keep {name} in {target}; it already appears to fit this code.",
        "introduce": f"Consider adding {name} to {target}.",
        "improve_conformance": (
            f"{target} partly follows {name}; make the existing design more consistent before "
            "adding another abstraction."
        ),
        "replace": f"Consider replacing the current approach in {target} with {name}.",
        "avoid": f"Do not add {name} to {target} unless the evidence changes.",
        "no_action": f"AnaxiGraph does not recommend a pattern change in {target}.",
        "insufficient_evidence": (
            f"There is not enough evidence to recommend using {name} in {target}."
        ),
    }.get(recommendation, f"Review whether {name} belongs in {target}.")


def _presence_sentence(name: str, target: str, presence: str) -> str:
    return {
        "present": f"{target} already shows the main parts of {name}.",
        "partial": f"{target} shows some, but not all, of {name}.",
        "absent": f"AnaxiGraph did not find the main parts of {name} in {target}.",
        "uncertain": f"The available evidence cannot show whether {target} already uses {name}.",
    }.get(presence, f"The recorded pattern state for {target} is {presence}.")


def _reason(evaluation: Mapping[str, Any]) -> str:
    rationale = str(evaluation.get("rationale") or "").strip()
    summary = str(evaluation.get("summary") or "").strip()
    return (
        rationale
        or summary
        or (
            "The available code, dependency, history, and semantic evidence made this pattern worth "
            "checking."
        )
    )


def _action(name: str, target: str, recommendation: str) -> str:
    return {
        "retain": (
            f"Keep the current {name} structure in {target}. Preserve its public behavior and "
            "tests when this code changes."
        ),
        "introduce": (
            f"Sketch the smallest way {name} could solve the observed problem in {target}. Add it "
            "only if it removes more complexity than it creates."
        ),
        "improve_conformance": (
            f"Name the parts of {name} that {target} already uses, then fix the smallest confusing "
            "or inconsistent part without building a second system beside it."
        ),
        "replace": (
            f"Compare the current approach with {name}, preserve callers and stored data, and "
            "replace one safe boundary at a time."
        ),
        "avoid": (
            f"Leave {name} out of {target}. Use the simplest local design that meets the current "
            "need."
        ),
        "no_action": "Leave the structure alone and keep its important behavior covered by tests.",
        "insufficient_evidence": (
            "Do not refactor from this result. Gather the missing evidence or wait until a real "
            "change makes the design question concrete."
        ),
    }.get(recommendation, "Read the evidence and make only a small, testable design change.")


def _reasons_for_caution(evaluation: Mapping[str, Any], recommendation: str) -> list[str]:
    reasons = _unique(
        [
            *_strings(evaluation.get("counter_evidence"), limit=5),
            *_strings(evaluation.get("risks"), limit=5),
            *_strings(evaluation.get("invalidation_conditions"), limit=5),
        ],
        limit=8,
    )
    if reasons:
        return reasons
    if recommendation in {"retain", "avoid", "no_action", "insufficient_evidence"}:
        return ["The current recommendation does not require a structural code change."]
    return [
        "Do not make the change if it adds more concepts, files, or moving parts than the problem needs."
    ]


def _verification(evaluation: Mapping[str, Any], target: str, recommendation: str) -> list[str]:
    invariants = _strings(evaluation.get("invariants"), limit=5)
    prerequisites = _strings(evaluation.get("prerequisites"), limit=3)
    steps = _unique([*prerequisites, *invariants], limit=6)
    if recommendation not in {"retain", "avoid", "no_action", "insufficient_evidence"}:
        steps.append(
            f"Run focused tests for {target}, scan the repository again, and compare the pattern result."
        )
    elif not steps:
        steps.append(f"Keep focused tests for {target} passing as the code changes.")
    return steps


def _score_meanings(scores: Any, pattern_name: str) -> list[dict[str, Any]]:
    values = _score_values(scores)
    return [
        _meaning(
            "Problem and fit",
            {
                "problem_match": values["applicability"],
                "pattern_fit": values["suitability"],
            },
            (
                f"Evidence that this problem exists is {_strength(values['applicability'])}, and "
                f"{pattern_name}'s fit for this code is {_strength(values['suitability'])}."
            ),
        ),
        _meaning(
            "What already exists",
            {"current_match": values["conformance"]},
            f"The code's current match to the pattern is {_strength(values['conformance'])}.",
        ),
        _meaning(
            "Value and timing",
            {
                "value_of_change": values["opportunity"],
                "expected_benefit": values["benefit"],
                "urgency": values["urgency"],
            },
            (
                f"Evidence that a change would help is {_strength(values['opportunity'])}; the "
                f"expected benefit is {_strength(values['benefit'])} and the urgency is "
                f"{_level(values['urgency'])}."
            ),
        ),
        *_change_score_meanings(values),
    ]


def _change_score_meanings(values: Mapping[str, int]) -> list[dict[str, Any]]:
    return [
        _meaning(
            "Difficulty of changing it",
            {
                "execution_safety": values["execution_safety"],
                "migration_cost": values["migration_cost"],
            },
            (
                f"The change {_safety(values['execution_safety'])}. The work and disruption "
                f"needed to move from the current design appear {_level(values['migration_cost'])}."
            ),
        ),
        _meaning(
            "Strength of evidence",
            {"evidence_strength": values["confidence"]},
            (
                f"The evidence supporting this evaluation is {_strength(values['confidence'])}; "
                "the number measures support for the conclusion, not code quality."
            ),
        ),
    ]


def _score_values(scores: Any) -> dict[str, int]:
    source = scores if isinstance(scores, Mapping) else {}
    names = (
        "applicability",
        "suitability",
        "conformance",
        "opportunity",
        "confidence",
        "benefit",
        "urgency",
        "execution_safety",
        "migration_cost",
    )
    return {name: _score(source.get(name)) for name in names}


def _score(value: Any) -> int:
    raw = value.get("value") if isinstance(value, Mapping) else value
    try:
        return max(0, min(100, int(raw or 0)))
    except (TypeError, ValueError):
        return 0


def _meaning(label: str, scores: dict[str, int], meaning: str) -> dict[str, Any]:
    return {"label": label, "scores": scores, "meaning": meaning}


def _strength(value: int) -> str:
    if value >= 70:
        return "strong"
    if value >= 40:
        return "mixed"
    return "weak"


def _level(value: int) -> str:
    if value >= 70:
        return "high"
    if value >= 40:
        return "moderate"
    return "low"


def _safety(value: int) -> str:
    if value >= 70:
        return "appears relatively safe to make in small steps"
    if value >= 40:
        return "has a mix of safe and risky parts"
    return "appears risky and needs stronger safeguards before work begins"


def _review_sentence(review: Mapping[str, Any]) -> str:
    verdict = str(review.get("verdict") or "complete")
    prefix = {
        "approve": "A second agent checked the evaluation and did not require a correction.",
        "revise": "A second agent corrected the evaluation before this result was saved.",
        "retain_competing": (
            "A second agent found another reasonable explanation, so the disagreement is preserved."
        ),
    }.get(verdict, "A second agent completed an independent check of this evaluation.")
    summary = str(review.get("summary") or "").strip()
    return f"{prefix} {summary}".strip()


def _strings(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item).strip() for item in value[:limit] if str(item).strip()]


def _unique(values: Sequence[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
        if len(result) == limit:
            break
    return result
