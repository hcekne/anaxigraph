"""Upgrade finding copy written by AnaxiGraph versions before the plain-language contract."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _LegacyFinding:
    item: Mapping[str, Any]
    summary: str
    explanation: str
    evidence: dict[str, str]
    path: str


def legacy_replacement(item: Mapping[str, Any]) -> dict[str, str] | None:
    """Return clearer copy only when a row matches an old built-in detector format."""

    finding_type = str(item.get("finding_type") or "")
    upgrader = _UPGRADERS.get(finding_type)
    if upgrader is None:
        return None
    context = _LegacyFinding(
        item=item,
        summary=str(item.get("summary") or ""),
        explanation=str(item.get("explanation") or ""),
        evidence=_evidence_values(item.get("evidence") or ()),
        path=str(next(iter(item.get("affected_artifacts") or ()), "the file")),
    )
    return upgrader(context)


def _module(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) is (\d+) LOC", context.summary)
    if match:
        return _module_copy(context.path, match.group(2), _number(context.explanation))
    current = re.fullmatch(r"(.+) may be doing too many jobs", context.summary)
    if current and context.explanation.startswith("It contains "):
        count = context.evidence.get("lines_of_code") or _number(context.explanation)
        return _module_copy(context.path, count, _number(context.explanation, last=True))
    return None


def _function(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) spans (\d+) logical lines", context.summary)
    if match:
        return _function_copy(match.group(1), match.group(2), _number(context.explanation))
    current = re.fullmatch(r"(.+) takes a lot of code to do one job", context.summary)
    if current and context.explanation.startswith("Its logic uses "):
        return _function_copy(
            current.group(1),
            _number(context.explanation),
            _number(context.explanation, last=True),
        )
    return None


def _complexity(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) has estimated complexity ([\d.]+)", context.summary)
    if match:
        return _complexity_copy(
            match.group(1), match.group(2), _number(context.explanation, last=True)
        )
    current = re.fullmatch(r"(.+) makes many decisions in one function", context.summary)
    if current and context.explanation.startswith("Branches such as "):
        return _complexity_copy(
            current.group(1),
            _number(context.explanation),
            _number(context.explanation, last=True),
        )
    return None


def _dependency(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) has (\d+) (incoming|outgoing) dependencies", context.summary)
    if match:
        return _dependency_copy(
            context.path,
            match.group(2),
            _number(context.explanation),
            match.group(3),
        )
    outgoing = context.summary.endswith(" reaches into many other modules")
    incoming = context.summary.startswith("Many modules rely on ")
    if (outgoing and context.explanation.startswith("It directly uses ")) or (
        incoming and re.match(r"\d+ modules use it directly", context.explanation)
    ):
        direction = "outgoing" if outgoing else "incoming"
        count = context.evidence.get(f"{direction}_dependencies") or _number(context.explanation)
        return _dependency_copy(
            context.path, count, _number(context.explanation, last=True), direction
        )
    return None


def _cycle(context: _LegacyFinding) -> dict[str, str] | None:
    if not context.summary.startswith("Dependency cycle spans "):
        return None
    return _cycle_copy(str(len(context.item.get("affected_artifacts") or ())))


def _boundary(context: _LegacyFinding) -> dict[str, str] | None:
    return (
        _boundary_copy(context.item)
        if context.summary.startswith("Forbidden dependency from ")
        else None
    )


def _drift(context: _LegacyFinding) -> dict[str, str] | None:
    if not context.summary.endswith(" differs from its declared group"):
        return None
    return _drift_copy(context.path, context.evidence)


def _coverage(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) has ([\d.]+)% line coverage", context.summary)
    if match:
        return _coverage_copy(match.group(1), match.group(2), _number(context.explanation))
    current = re.fullmatch(r"Tests may miss behavior in (.+)", context.summary)
    if current and context.explanation.startswith("The imported test report says "):
        return _coverage_copy(
            current.group(1),
            _number(context.explanation),
            _number(context.explanation, last=True),
        )
    return None


def _dead_code(context: _LegacyFinding) -> dict[str, str] | None:
    old_copy = context.summary.endswith(" may be unreachable")
    current_copy = context.summary.endswith(
        " may no longer be used"
    ) and context.explanation.startswith("No indexed code points to this file")
    if not old_copy and not current_copy:
        return None
    return _dead_code_copy(context.path, context.evidence.get("days_since_change") or "many")


def _module_copy(path: str, count: str, limit: str) -> dict[str, str]:
    review_point = _with_unit(limit, "lines")
    return {
        "summary": f"{path} has {count} lines; this project reviews files above {review_point}",
        "explanation": (
            "A large file becomes hard to change when it contains jobs that do not belong "
            "together. Size alone does not mean the file should be split; one clear job may "
            "need a lot of code."
        ),
        "recommended_action": (
            "Name the file's main jobs. If two jobs can change for different reasons, move the "
            "smaller one into a clearly named file. If the file has one clear job, keep it together."
        ),
    }


def _function_copy(name: str, count: str, limit: str) -> dict[str, str]:
    review_point = _with_unit(limit, "lines")
    return {
        "summary": f"{name} uses {count} lines; this project reviews functions above {review_point}",
        "explanation": (
            "A long function becomes hard to follow when it mixes separate jobs or makes a reader "
            "remember too many details at once. Length alone is not a reason to split a clear, "
            "step-by-step function."
        ),
        "recommended_action": (
            "Name each step in the function. If one step has its own clear input and result, move "
            "that step into a named helper and keep tests around both outcomes. Otherwise leave the "
            "steps together."
        ),
    }


def _complexity_copy(name: str, score: str, limit: str) -> dict[str, str]:
    review_point = _clean_number(limit)
    return {
        "summary": (
            f"{name} has a branch score of {score}; this project reviews functions above {review_point}"
        ),
        "explanation": (
            "More branches create more possible outcomes to understand and test. They can still "
            "belong together when they answer one clear question."
        ),
        "recommended_action": (
            "Group the branches by the question they answer. If one group answers a separate "
            "question, move it into a clearly named helper and test both outcomes. If every branch "
            "belongs to one decision, keep it together."
        ),
    }


def _dependency_copy(path: str, count: str, limit: str, direction: str) -> dict[str, str]:
    return (
        _outgoing_copy(path, count, limit)
        if direction == "outgoing"
        else _incoming_copy(path, count, limit)
    )


def _outgoing_copy(path: str, count: str, limit: str) -> dict[str, str]:
    review_point = _with_unit(limit, "direct file links")
    return {
        "summary": (
            f"{path} directly uses {count} other files; this project reviews files above {review_point}"
        ),
        "explanation": (
            "A file that reaches into many parts of the project can mix several jobs and become "
            "hard to test in isolation. This can be exactly right when the file is a coordinator "
            "for one clear workflow."
        ),
        "recommended_action": (
            "Group the direct file links by the job they support. If one group belongs to a separate "
            "job, move that job into a small file with one clear way for callers to use it."
        ),
    }


def _incoming_copy(path: str, count: str, limit: str) -> dict[str, str]:
    review_point = _with_unit(limit, "direct file links")
    return {
        "summary": (
            f"{count} files directly use {path}; this project reviews files above {review_point}"
        ),
        "explanation": (
            "A behavior change here can affect many callers. That is normal when this file "
            "intentionally offers behavior that many callers use and tests cover."
        ),
        "recommended_action": (
            "Find the callers that rely on this file's public behavior and run their tests before "
            "changing it. Split the file only when callers use clearly unrelated parts."
        ),
    }


def _dead_code_copy(path: str, days: str) -> dict[str, str]:
    return {
        "summary": f"{path} may no longer be used",
        "explanation": (
            "Unused code makes a project harder to search and maintain. This file may still be "
            "loaded by configuration, a framework, or code that builds its name at runtime, so "
            "the finding is not permission to delete it."
        ),
        "recommended_action": (
            "Before deleting it, search routes, events, templates, configuration, and runtime "
            "registrations for the file name. Remove it only after tests and a normal application "
            "start still work."
        ),
    }


def _cycle_copy(count: str) -> dict[str, str]:
    return {
        "summary": f"{count} files depend on one another in a loop",
        "explanation": (
            "Following the imports or references eventually leads back to the starting file. A "
            "change in one file can therefore force changes in the others, which makes them "
            "harder to understand and test separately. The loop does not automatically mean the "
            "application is broken."
        ),
        "recommended_action": (
            "Find the smallest link that can point the other way. If both files need the same "
            "behavior, move that behavior into a small file they can both use. Then make the "
            "remaining code links flow in one direction."
        ),
    }


def _boundary_copy(item: Mapping[str, Any]) -> dict[str, str]:
    paths = [str(path) for path in item.get("affected_artifacts") or ()]
    source = paths[0] if paths else "The source file"
    target = paths[1] if len(paths) > 1 else "the file blocked by the project rule"
    explanation = (
        "The project's repository-area rules say these files should not use one another directly. "
        "This code link breaks that rule and makes the intended separation harder to keep."
    )
    old_explanation = str(item.get("explanation") or "").strip()
    if old_explanation and "declared architecture boundary" not in old_explanation:
        explanation += f" Project note: {old_explanation}"
    action = (
        "Change the source file so it reaches the needed behavior through a file the project "
        "rule allows."
    )
    old_action = str(item.get("recommended_action") or "").strip()
    if old_action and old_action != "Depend on an allowed boundary or interface.":
        action += f" Project guidance: {old_action}"
    return {
        "summary": f"{source} uses {target}, which the project rules do not allow",
        "explanation": explanation,
        "recommended_action": action,
    }


def _drift_copy(path: str, evidence: Mapping[str, str]) -> dict[str, str]:
    declared = evidence.get("declared_group") or "its declared area"
    inferred = evidence.get("inferred_group") or "another area"
    return {
        "summary": f"{path} no longer fits its declared area",
        "explanation": (
            f"The project places it in {declared}, but its path and direct code links make it behave "
            f"more like part of {inferred}. Either the map is out of date or the file has started "
            "doing work that belongs elsewhere."
        ),
        "recommended_action": (
            "Choose which description is true. If the file belongs in the declared area, move the "
            "unrelated work or code links out. If it belongs in the suggested area, update its "
            "location or file-placement rule."
        ),
    }


def _coverage_copy(path: str, percent: str, goal: str) -> dict[str, str]:
    coverage_goal = _with_unit(goal, "%", separator="")
    coverage = _clean_number(percent)
    return {
        "summary": f"Tests run {coverage}% of {path}; this project's goal is {coverage_goal}",
        "explanation": (
            "Line coverage cannot tell whether tests are good, but behavior in lines that never "
            "run during tests can break without being noticed."
        ),
        "recommended_action": (
            "Find the decisions and error cases the report did not run. Add small tests that check "
            "their visible behavior instead of tests that only touch extra lines."
        ),
    }


def _evidence_values(raw: Any) -> dict[str, str]:
    return {
        key: value for item in raw if "=" in str(item) for key, value in (str(item).split("=", 1),)
    }


def _number(value: str, *, last: bool = False) -> str:
    matches = re.findall(r"\d+(?:\.\d+)?", value)
    if not matches:
        return "the configured limit"
    return matches[-1] if last else matches[0]


def _with_unit(value: str, unit: str, *, separator: str = " ") -> str:
    return value if value == "the configured limit" else f"{_clean_number(value)}{separator}{unit}"


def _clean_number(value: str) -> str:
    try:
        return f"{float(value):g}"
    except ValueError:
        return value


_Upgrader = Callable[[_LegacyFinding], dict[str, str] | None]
_UPGRADERS: dict[str, _Upgrader] = {
    "module_complexity": _module,
    "long_function": _function,
    "symbol_complexity": _complexity,
    "high_fan_out": _dependency,
    "high_fan_in": _dependency,
    "dependency_cycle": _cycle,
    "architecture_violation": _boundary,
    "architecture_drift": _drift,
    "weak_test_coverage": _coverage,
    "possible_dead_code": _dead_code,
}
