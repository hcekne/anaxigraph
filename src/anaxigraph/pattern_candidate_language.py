"""Plain-language explanations for deterministic pattern candidate selection."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

PATTERN_CANDIDATE_LANGUAGE_VERSION = "pattern-candidate-explanation-v1"

_SELECTION_REASON_COPY = {
    "problem_signal": "The code shows a problem that this pattern is designed to address.",
    "supporting_evidence": "Other repository evidence also supports checking this pattern here.",
    "semantic_question": (
        "The deterministic evidence leaves an important design question that an agent can answer."
    ),
}


def candidate_explanation(
    item: Mapping[str, Any],
    pattern_name: str,
    observations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Explain why one target/pattern pair entered or missed the bounded work plan."""

    target = _target_name(item.get("target"))
    reason = str(item.get("reason") or "unknown")
    selected = bool(item.get("selected_for_evaluation"))
    return {
        "version": PATTERN_CANDIDATE_LANGUAGE_VERSION,
        "conclusion": _conclusion(pattern_name, target, reason, selected),
        "why_this_pair_was_considered": _consideration_reasons(item, reason),
        "why_it_was_selected_or_skipped": _reason_sentence(reason),
        "what_anaxigraph_found": _evidence_summary(item, observations),
        "what_anaxigraph_could_not_check": _missing_summary(item),
        "what_happens_next": _next_step(pattern_name, target, reason, selected),
        "queue_rank": _queue_rank(item),
    }


def _target_name(value: Any) -> str:
    target = value if isinstance(value, Mapping) else {}
    return str(
        target.get("path")
        or target.get("qualified_name")
        or target.get("label")
        or target.get("key")
        or "this code"
    )


def _conclusion(pattern: str, target: str, reason: str, selected: bool) -> str:
    if selected:
        return f"AnaxiGraph selected {pattern} for {target} for a full agent evaluation."
    return {
        "no_positive_evidence": (
            f"AnaxiGraph skipped {pattern} for {target} because current evidence does not show "
            "the problem this pattern solves."
        ),
        "counter_evidence": (
            f"AnaxiGraph skipped {pattern} for {target} because the evidence currently points "
            "away from this pattern."
        ),
        "below_priority": (
            f"{pattern} may be relevant to {target}, but it did not rank high enough for the "
            "bounded evaluation queue."
        ),
        "sparse_plan_bound": (
            f"{pattern} qualified for {target}, but more relevant work filled the bounded queue."
        ),
        "plan_not_ready": (
            f"{pattern} qualifies for {target}, but the current evaluation plan is not ready yet."
        ),
    }.get(reason, f"AnaxiGraph did not select {pattern} for {target} in the current plan.")


def _consideration_reasons(item: Mapping[str, Any], reason: str) -> list[str]:
    values = _strings(item.get("selection_reasons"))
    reasons = [_SELECTION_REASON_COPY.get(value, _plain_label(value) + ".") for value in values]
    if reasons:
        return reasons
    if _count(item.get("matched_signal_count")):
        return ["At least one repository observation supports checking this pattern here."]
    if reason == "counter_evidence":
        return ["AnaxiGraph checked this pair because the catalog defines evidence against it."]
    return ["The pattern applies at this code level, so AnaxiGraph checked the available evidence."]


def _reason_sentence(reason: str) -> str:
    return {
        "selected": (
            "The pair passed the checks AnaxiGraph can do without AI and fit within the deliberately "
            "limited work queue."
        ),
        "no_positive_evidence": (
            "No problem signal or supporting signal matched. This is not evidence that the pattern "
            "is bad; it means there is no reason to spend an agent evaluation on it here."
        ),
        "counter_evidence": (
            "Evidence against the pattern matched, while no stronger positive evidence justified a review."
        ),
        "below_priority": (
            "Some evidence matched, but its deterministic queue rank was below the configured cutoff."
        ),
        "sparse_plan_bound": (
            "The pair passed the cutoff, but the queue keeps only the strongest bounded set instead "
            "of evaluating every pattern against every target."
        ),
        "plan_not_ready": (
            "The pair passed deterministic checks, but selection is not final until the current plan is ready."
        ),
    }.get(reason, "The current selection policy did not place this pair in agent work.")


def _evidence_summary(
    item: Mapping[str, Any], observations: Sequence[Mapping[str, Any]]
) -> list[str]:
    details = [_observation_sentence(value) for value in observations[:8]]
    if details:
        return details
    matched = _count(item.get("matched_signal_count"))
    counter = _count(item.get("counter_signal_count"))
    return [
        _count_sentence(
            matched, "supporting observation matched", "supporting observations matched"
        ),
        _count_sentence(
            counter,
            "observation against the pattern matched",
            "observations against the pattern matched",
        ),
    ]


def _observation_sentence(value: Mapping[str, Any]) -> str:
    feature = _plain_label(str(value.get("feature") or "repository evidence"))
    actual = _plain_value(value.get("actual"))
    measured = f"AnaxiGraph found {feature}{f' = {actual}' if actual else ''}."
    role = str(value.get("role") or "supporting")
    consequence = {
        "problem": " This shows a problem that the pattern may address.",
        "supporting": " This supports checking the pattern here.",
        "counter": " This points against using the pattern here.",
    }.get(role, " This affected candidate selection.")
    return measured + consequence


def _plain_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float, str)):
        return str(value)[:100]
    if isinstance(value, (list, tuple, set, dict)):
        return f"{len(value)} recorded value{'s' if len(value) != 1 else ''}"
    return ""


def _missing_summary(item: Mapping[str, Any]) -> list[str]:
    missing = [
        f"AnaxiGraph has no usable {_plain_label(value)} evidence for this target."
        for value in _strings(item.get("missing_evidence"))
    ]
    gaps = [_plain_gap(value) for value in _strings(item.get("capability_gaps"))]
    values = _unique([*missing, *gaps])
    return values or ["No required evidence gap was recorded for this candidate decision."]


def _plain_gap(value: str) -> str:
    match = re.fullmatch(
        r"(?P<fact>[^:]+):(?P<minimum>[^ ]+) \((?P<found>\d+)/(?P<total>\d+), best=(?P<best>[^)]+)\)",
        value,
    )
    if match is None:
        return f"The analyzer reported an evidence gap: {_plain_label(value)}."
    fields = match.groupdict()
    return (
        f"This check needs at least {fields['minimum']} detail for {_plain_label(fields['fact'])}, "
        f"but only {fields['found']} of {fields['total']} relevant items met it; the best available "
        f"detail was {fields['best']}."
    )


def _next_step(pattern: str, target: str, reason: str, selected: bool) -> str:
    if selected:
        return (
            f"An agent now assesses whether {pattern} fits {target}; a second agent critiques that "
            "assessment before it becomes a finalized map result."
        )
    if reason == "plan_not_ready":
        return "Wait for the current sparse plan to finish; no human approval is required."
    if reason == "sparse_plan_bound":
        return "No agent work is created unless repository evidence or the bounded plan changes."
    return (
        "No agent work is created for this pair. A later repository change can make it eligible "
        "without any manual override."
    )


def _queue_rank(item: Mapping[str, Any]) -> dict[str, Any]:
    reasons = _strings(item.get("selection_reasons"))
    value = _count(item.get("priority")) if reasons else None
    if value is None:
        meaning = "No queue rank was assigned because the evidence did not create a candidate."
    else:
        meaning = (
            f"The internal queue rank is {value} out of 100. It only decides which candidates fit "
            "in bounded agent work; it is not a grade, pattern rating, or recommendation."
        )
    return {"value": value, "meaning": meaning}


def _count_sentence(value: int, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}."


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _plain_label(value: str) -> str:
    return " ".join(value.replace(".", " ").replace("_", " ").split()).lower()


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item).strip() for item in value[:20] if str(item).strip()]


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))[:20]
