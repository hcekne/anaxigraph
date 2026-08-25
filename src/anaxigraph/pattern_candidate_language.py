"""Plain-language explanations for deterministic pattern candidate selection."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

PATTERN_CANDIDATE_LANGUAGE_VERSION = "pattern-candidate-explanation-v1"
PATTERN_CANDIDATE_DETAIL_LANGUAGE_VERSION = "pattern-candidate-detail-explanation-v1"

_SELECTION_REASON_COPY = {
    "problem_signal": "The code shows a problem that this pattern is designed to address.",
    "supporting_evidence": "Other repository evidence also supports checking this pattern here.",
    "semantic_question": (
        "The deterministic evidence leaves an important design question that an agent can answer."
    ),
}

_FEATURE_SOURCES = {
    "code": "the code's",
    "syntax": "the parsed code's",
    "semantic": "the AI description's",
    "graph": "the dependency map's",
    "history": "the Git history's",
    "interface": "the code interface's",
    "interfaces": "the code interface's",
    "runtime": "the running system's",
    "test": "the tests'",
    "documentation": "the documentation's",
    "modules": "the module collection's",
    "types": "the type collection's",
    "symbols": "the symbol collection's",
    "symbol": "the symbol collection's",
    "side_effects": "the side-effect analysis's",
}

_FEATURE_TERMS = {
    "fan in": "incoming connections",
    "fan out": "outgoing connections",
    "logical lines": "executable lines",
    "change count": "number of recent changes",
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


def candidate_signal_explanation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Explain one catalog check without requiring knowledge of its machine fields."""

    feature = _plain_feature(str(value.get("feature") or "repository evidence"))
    outcome = str(value.get("outcome") or "unknown")
    confidence = _confidence_percent(value.get("confidence"))
    return {
        "version": PATTERN_CANDIDATE_DETAIL_LANGUAGE_VERSION,
        "what_was_checked": _signal_check(feature, str(value.get("operator") or ""), value),
        "what_was_found": _signal_result(feature, outcome, value.get("actual")),
        "how_it_affected_selection": _signal_effect(
            str(value.get("role") or "supporting"), outcome
        ),
        "evidence_strength": {
            "value": confidence,
            "meaning": (
                f"Support for this observation is {_strength(confidence)} ({confidence} out of "
                "100). This measures evidence for the observation, not code quality or pattern "
                "quality."
            ),
        },
    }


def candidate_capability_explanation(value: Mapping[str, Any]) -> dict[str, Any]:
    """Explain whether analyzers supplied enough detail for one catalog check."""

    fact = _plain_label(str(value.get("fact") or "required code information"))
    minimum = str(value.get("minimum") or "unknown")
    best = str(value.get("best_level") or "unavailable")
    percent = round(_ratio(value.get("ratio")) * 100)
    complete = bool(value.get("complete"))
    return {
        "version": PATTERN_CANDIDATE_DETAIL_LANGUAGE_VERSION,
        "conclusion": (
            f"The available analyzers supplied enough {fact} detail for this check."
            if complete
            else f"The available analyzers did not supply enough {fact} detail for every part of this check."
        ),
        "required_detail": _required_detail(fact, minimum),
        "available_detail": _available_detail(percent, best),
        "how_to_use_this": (
            "This evidence was complete enough to use in candidate selection."
            if complete
            else "Treat conclusions that depend on this information as incomplete."
        ),
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
    feature = _plain_feature(str(value.get("feature") or "repository evidence"))
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


def _signal_check(feature: str, operator: str, value: Mapping[str, Any]) -> str:
    expected = _plain_value(value.get("expected"))
    checks = {
        "available": f"whether usable {feature} evidence was available",
        "unavailable": f"whether {feature} evidence was unavailable",
        "exists": f"whether {feature} existed",
        "contains": f"whether {feature} included {expected}",
        "count_gte": f"whether {feature} contained at least {expected} recorded items",
        "count_lte": f"whether {feature} contained at most {expected} recorded items",
        "eq": f"whether {feature} equaled {expected}",
        "neq": f"whether {feature} differed from {expected}",
        "gt": f"whether {feature} was greater than {expected}",
        "gte": f"whether {feature} was at least {expected}",
        "lt": f"whether {feature} was less than {expected}",
        "lte": f"whether {feature} was at most {expected}",
    }
    check = checks.get(operator) or f"whether {feature} met this pattern's evidence rule"
    return f"AnaxiGraph checked {check}."


def _signal_result(feature: str, outcome: str, actual: Any) -> str:
    found = _plain_value(actual)
    if outcome == "unknown":
        return f"AnaxiGraph had no usable value for {feature}, so this check remains unknown."
    result = "met" if outcome == "matched" else "did not meet"
    recorded = f" It recorded the value as {found}." if found else ""
    return f"The observation {result} the pattern's evidence rule.{recorded}"


def _signal_effect(role: str, outcome: str) -> str:
    if outcome == "unknown":
        return "This unknown observation did not support or oppose selecting the pattern."
    if outcome != "matched":
        return "Because the observation did not match, it did not affect candidate selection."
    return {
        "problem": "This suggests the code has a problem that the pattern may address.",
        "supporting": "This supports checking the pattern for this code.",
        "counter": "This points against using the pattern for this code.",
    }.get(role, "This observation affected candidate selection.")


def _confidence_percent(value: Any) -> int:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if number <= 1:
        number *= 100
    return max(0, min(100, round(number)))


def _ratio(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _strength(value: int) -> str:
    if value >= 70:
        return "strong"
    if value >= 40:
        return "mixed"
    return "weak"


def _required_detail(fact: str, level: str) -> str:
    return {
        "heuristic": f"This check needs at least a rough estimate about {fact}.",
        "lexical": f"This check needs names or code tokens that reveal {fact}.",
        "structural": f"This check needs parsed code structure that reveals {fact}.",
        "deep": f"This check needs detailed parsed relationships about {fact}.",
    }.get(level, f"This pattern check needs at least {_plain_label(level)} detail about {fact}.")


def _available_detail(percent: int, level: str) -> str:
    best = {
        "unavailable": "No analyzer could provide usable information.",
        "heuristic": "The best available information was a rough estimate.",
        "lexical": "The best available information came from names and code tokens.",
        "structural": "The best available information came from parsed code structure.",
        "deep": "The best available information included detailed parsed relationships.",
    }.get(level, f"The best available detail level was {_plain_label(level)}.")
    return f"{percent}% of the relevant analyzers could provide the required detail. {best}"


def _missing_summary(item: Mapping[str, Any]) -> list[str]:
    missing = [
        f"AnaxiGraph has no usable information about {_plain_feature(value)} for this target."
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
        return f"The analyzer reported an evidence gap: {_plain_feature(value)}."
    fields = match.groupdict()
    return (
        f"This check needs at least {fields['minimum']} detail for {_plain_feature(fields['fact'])}, "
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


def _plain_feature(value: str) -> str:
    source, separator, name = value.partition(".")
    if not separator:
        return _plain_label(value)
    term = _plain_label(name)
    term = _FEATURE_TERMS.get(term, term)
    prefix = _FEATURE_SOURCES.get(source)
    return f"{prefix} {term}" if prefix else _plain_label(value)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item).strip() for item in value[:20] if str(item).strip()]


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))[:20]
