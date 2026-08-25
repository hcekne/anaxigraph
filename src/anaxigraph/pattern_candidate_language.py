"""Plain-language explanations for pattern candidates selected from repeatable code checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

PATTERN_CANDIDATE_LANGUAGE_VERSION = "pattern-candidate-explanation-v2"
PATTERN_CANDIDATE_DETAIL_LANGUAGE_VERSION = "pattern-candidate-detail-explanation-v2"

_SELECTION_REASON_COPY = {
    "problem_signal": "The code shows a problem that this pattern is designed to address.",
    "supporting_evidence": "Other repository evidence also supports checking this pattern here.",
    "semantic_question": (
        "The direct code checks leave an important design question that an AI can answer."
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
    "modules": "the file collection's",
    "types": "the type collection's",
    "symbols": "the collection of named code parts'",
    "symbol": "the collection of named code parts'",
    "side_effects": "the side-effect analysis's",
}

_FEATURE_TERMS = {
    "complexity": "decision-branch count",
    "fan in": "direct links from other files",
    "fan out": "direct links to other files",
    "logical lines": "executable lines",
    "change count": "number of recent changes",
    "provider boundary": "shared caller-facing interface for providers",
    "single implementation": "only one implementation",
    "inheritance": "class inheritance",
    "dossier": "saved AI description of what the code does",
    "semantic dossier": "saved AI description of what the code does",
}


def candidate_explanation(
    item: Mapping[str, Any],
    pattern_name: str,
    observations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Explain why one code/pattern pair did or did not receive an AI task."""

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

    fact = _plain_feature(str(value.get("fact") or "required code information"))
    minimum = str(value.get("minimum") or "unknown")
    best = str(value.get("best_level") or "unavailable")
    percent = round(_ratio(value.get("ratio")) * 100)
    complete = bool(value.get("complete"))
    return {
        "version": PATTERN_CANDIDATE_DETAIL_LANGUAGE_VERSION,
        "conclusion": (
            f"AnaxiGraph's code readers supplied enough information about {fact} for this check."
            if complete
            else f"AnaxiGraph's code readers did not supply enough information about {fact} for every part of this check."
        ),
        "required_detail": _required_detail(fact, minimum),
        "available_detail": _available_detail(percent, best),
        "how_to_use_this": (
            "This information was complete enough to use when selecting possible pattern matches."
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
        return f"AnaxiGraph selected {pattern} for {target} for a full AI pattern check."
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
            "limited set of AI pattern checks."
        ),
        "sparse_plan_bound": (
            f"{pattern} qualified for {target}, but higher-ranked work filled the available AI tasks."
        ),
        "plan_not_ready": (
            f"{pattern} qualifies for {target}, but AnaxiGraph has not finished choosing the AI tasks yet."
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
        return [
            "AnaxiGraph checked this possible match because the pattern library lists evidence against it."
        ]
    return ["The pattern applies at this code level, so AnaxiGraph checked the available evidence."]


def _reason_sentence(reason: str) -> str:
    return {
        "selected": (
            "The code and pattern passed the checks AnaxiGraph can do without AI and fit within "
            "the configured number of AI tasks."
        ),
        "no_positive_evidence": (
            "No problem signal or supporting signal matched. This is not evidence that the pattern "
            "is bad; it means there is no reason to spend an AI pattern check on it here."
        ),
        "counter_evidence": (
            "Evidence against the pattern matched, while no stronger positive evidence justified a review."
        ),
        "below_priority": (
            "Some evidence matched, but AnaxiGraph ranked other possible pattern matches higher."
        ),
        "sparse_plan_bound": (
            "The possible match passed the minimum score, but AnaxiGraph keeps only the strongest "
            "configured number instead of asking AI to check every pattern against every piece of code."
        ),
        "plan_not_ready": (
            "The possible match passed direct code checks, but selection is not final until "
            "AnaxiGraph finishes choosing the AI tasks."
        ),
    }.get(reason, "The current settings did not place this possible match in AI work.")


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
    measured = f"AnaxiGraph recorded {feature}{f' as {actual}' if actual else ''}."
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
    check = (
        checks.get(operator) or f"whether {feature} met the condition listed in the pattern library"
    )
    return f"AnaxiGraph checked {check}."


def _signal_result(feature: str, outcome: str, actual: Any) -> str:
    found = _plain_value(actual)
    if outcome == "unknown":
        return f"AnaxiGraph had no usable value for {feature}, so this check remains unknown."
    result = "passed" if outcome == "matched" else "did not pass"
    recorded = f" It recorded the value as {found}." if found else ""
    return f"The recorded value {result} this pattern-library check.{recorded}"


def _signal_effect(role: str, outcome: str) -> str:
    if outcome == "unknown":
        return "This unknown observation did not support or oppose selecting the pattern."
    if outcome != "matched":
        return "Because the observation did not match, it did not affect whether an AI check was created."
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
        "summary": f"This check needs a short explanation of what the code does to understand {fact}.",
        "heuristic": f"This check needs at least a rough estimate about {fact}.",
        "lexical": f"This check needs names or code words that reveal {fact}.",
        "structural": f"This check needs parsed code structure that reveals {fact}.",
        "deep": f"This check needs detailed parsed relationships about {fact}.",
    }.get(
        level,
        f"This pattern check needs the '{_plain_label(level)}' amount of information about {fact}.",
    )


def _available_detail(percent: int, level: str) -> str:
    best = {
        "unavailable": "AnaxiGraph's code readers could not provide usable information.",
        "heuristic": "The best available information was a rough estimate.",
        "lexical": "The best available information came from names and code words.",
        "structural": "The best available information came from parsed code structure.",
        "deep": "The best available information included detailed parsed relationships.",
    }.get(level, f"The best available information was labeled '{_plain_label(level)}'.")
    return f"AnaxiGraph had the required information for {percent}% of the relevant code. {best}"


def _missing_summary(item: Mapping[str, Any]) -> list[str]:
    missing = [
        f"AnaxiGraph has no usable information about {_plain_feature(value)} for this target."
        for value in _strings(item.get("missing_evidence"))
    ]
    gaps = [_plain_gap(value) for value in _strings(item.get("capability_gaps"))]
    values = _unique([*missing, *gaps])
    return values or ["AnaxiGraph had all information required for this code check."]


def _plain_gap(value: str) -> str:
    match = re.fullmatch(
        r"(?P<fact>[^:]+):(?P<minimum>[^ ]+) \((?P<found>\d+)/(?P<total>\d+), best=(?P<best>[^)]+)\)",
        value,
    )
    if match is None:
        return f"AnaxiGraph's code readers were missing this required information: {_plain_feature(value)}."
    fields = match.groupdict()
    return (
        f"This check needs {_detail_requirement(fields['minimum'])} for {_plain_feature(fields['fact'])}, "
        f"but only {fields['found']} of {fields['total']} relevant items met it; the best available "
        f"information was {_detail_description(fields['best'])}."
    )


def _next_step(pattern: str, target: str, reason: str, selected: bool) -> str:
    if selected:
        return (
            f"One AI pass now checks whether {pattern} fits {target}; a separate AI pass checks "
            "that result before AnaxiGraph shows it as complete."
        )
    if reason == "plan_not_ready":
        return "Wait for AnaxiGraph to finish choosing the AI pattern tasks; no human approval is required."
    if reason == "sparse_plan_bound":
        return "No AI pattern task is created unless the repository evidence or task limit changes."
    return (
        "No AI pattern task is created for this possible match. A later repository change can make it eligible "
        "without any manual override."
    )


def _queue_rank(item: Mapping[str, Any]) -> dict[str, Any]:
    reasons = _strings(item.get("selection_reasons"))
    value = _count(item.get("priority")) if reasons else None
    if value is None:
        meaning = "No work-order score was assigned because the evidence did not create a possible pattern match."
    else:
        meaning = (
            f"AnaxiGraph gave this possible match a work-order score of {value} out of 100. The "
            "score only decides which limited AI tasks run first; it is not a code grade, pattern "
            "fit rating, or recommendation."
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
        term = _plain_label(value)
        return _FEATURE_TERMS.get(term, term)
    term = _plain_label(name)
    term = _FEATURE_TERMS.get(term, term)
    prefix = _FEATURE_SOURCES.get(source)
    return f"{prefix} {term}" if prefix else _plain_label(value)


def _detail_requirement(level: str) -> str:
    return {
        "summary": "a short explanation of what the code does",
        "heuristic": "a rough estimate",
        "lexical": "names or code words",
        "structural": "parsed code structure",
        "deep": "detailed parsed relationships",
    }.get(level, f"the '{_plain_label(level)}' amount of information")


def _detail_description(level: str) -> str:
    return {
        "unavailable": "not available",
        "heuristic": "only a rough estimate",
        "lexical": "names and code words",
        "structural": "parsed code structure",
        "deep": "detailed parsed relationships",
    }.get(level, _plain_label(level))


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item).strip() for item in value[:20] if str(item).strip()]


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))[:20]
