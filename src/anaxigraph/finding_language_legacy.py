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
    return (
        _module_copy(context.path, match.group(2), _number(context.explanation)) if match else None
    )


def _function(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) spans (\d+) logical lines", context.summary)
    return (
        _function_copy(match.group(1), match.group(2), _number(context.explanation))
        if match
        else None
    )


def _complexity(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) has estimated complexity ([\d.]+)", context.summary)
    return (
        _complexity_copy(match.group(1), match.group(2), _number(context.explanation, last=True))
        if match
        else None
    )


def _dependency(context: _LegacyFinding) -> dict[str, str] | None:
    match = re.fullmatch(r"(.+) has (\d+) (incoming|outgoing) dependencies", context.summary)
    if match is None:
        return None
    return _dependency_copy(
        context.path,
        match.group(2),
        _number(context.explanation),
        match.group(3),
    )


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
    return (
        _coverage_copy(match.group(1), match.group(2), _number(context.explanation))
        if match
        else None
    )


def _dead_code(context: _LegacyFinding) -> dict[str, str] | None:
    if not context.summary.endswith(" may be unreachable"):
        return None
    return _dead_code_copy(context.path, context.evidence.get("days_since_change") or "many")


def _module_copy(path: str, count: str, limit: str) -> dict[str, str]:
    review_point = _with_unit(limit, "lines")
    return {
        "summary": f"{path} may be doing too many jobs",
        "explanation": (
            f"It contains {count} lines of code. This project starts a closer review at "
            f"{review_point}. A large file is not automatically wrong, but unrelated jobs can "
            "become tangled and make changes harder to understand."
        ),
        "recommended_action": (
            "Name the file's main jobs. If two jobs can change for different reasons, move the "
            "smaller one into a clearly named module. If the file has one clear job, keep it together."
        ),
    }


def _function_copy(name: str, count: str, limit: str) -> dict[str, str]:
    return {
        "summary": f"{name} takes a lot of code to do one job",
        "explanation": (
            f"Its logic uses {count} lines. This project starts a closer review at {limit}. A long "
            "function can be clear when every step belongs together, but mixed jobs make later "
            "changes easier to misunderstand."
        ),
        "recommended_action": (
            "Name each step in the function. If one step has its own clear input and result, move "
            "that step into a named helper and keep tests around both outcomes. Otherwise leave the "
            "steps together."
        ),
    }


def _complexity_copy(name: str, score: str, limit: str) -> dict[str, str]:
    return {
        "summary": f"{name} makes many decisions in one function",
        "explanation": (
            f"Branches such as if-statements and loops give it a decision score of {score}. This "
            f"project starts a closer review above {limit}. More decisions mean more cases to "
            "understand and test, but the count alone does not prove the design is wrong."
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
    return {
        "summary": f"{path} reaches into many other modules",
        "explanation": (
            f"It directly uses {count} modules. This project starts a closer review above {limit}. "
            "That can be correct for a coordinator, but it can also mean this file is handling "
            "several jobs at once."
        ),
        "recommended_action": (
            "Group the dependencies by the job they support. If one group belongs to a separate "
            "job, move that job behind a small, clearly named interface."
        ),
    }


def _incoming_copy(path: str, count: str, limit: str) -> dict[str, str]:
    return {
        "summary": f"Many modules rely on {path}",
        "explanation": (
            f"{count} modules use it directly. This project starts a closer review above {limit}. "
            "A behavior change here can reach many places, although that is normal for stable shared code."
        ),
        "recommended_action": (
            "Treat its public behavior as a shared promise. Find its callers and tests before "
            "changing it. Split it only when callers use clearly unrelated parts."
        ),
    }


def _dead_code_copy(path: str, days: str) -> dict[str, str]:
    return {
        "summary": f"{path} may no longer be used",
        "explanation": (
            "No indexed code points to this file, the analyzer found no program entry or runtime "
            f"registration, and Git shows no change for {days} days. Configuration or code that "
            "loads files by name could still use it, so this is not proof that deletion is safe."
        ),
        "recommended_action": (
            "Before deleting it, search routes, events, templates, configuration, and runtime "
            "registrations for the file name. Remove it only after tests and a normal application "
            "start still work."
        ),
    }


def _cycle_copy(count: str) -> dict[str, str]:
    return {
        "summary": f"{count} modules depend on one another in a loop",
        "explanation": (
            "Following the imports or references eventually leads back to the starting module. A "
            "change in one module can therefore force changes in the others, which makes them "
            "harder to understand and test separately. The loop does not automatically mean the "
            "application is broken."
        ),
        "recommended_action": (
            "Find the smallest link that can point the other way. Move the shared idea into a small "
            "interface or module, then make the remaining dependencies flow in one direction."
        ),
    }


def _boundary_copy(item: Mapping[str, Any]) -> dict[str, str]:
    paths = [str(path) for path in item.get("affected_artifacts") or ()]
    source = paths[0] if paths else "The source file"
    target = paths[1] if len(paths) > 1 else "the blocked module"
    explanation = (
        "The repository's architecture rules say these parts should stay separate. Direct use "
        "makes that separation harder to protect."
    )
    old_explanation = str(item.get("explanation") or "").strip()
    if old_explanation and "declared architecture boundary" not in old_explanation:
        explanation += f" Project note: {old_explanation}"
    action = "Change the source file so it reaches the needed behavior through an allowed module."
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
            f"The project places it in {declared}, but its path and dependencies make it behave "
            f"more like part of {inferred}. Either the map is out of date or the file has started "
            "doing work that belongs elsewhere."
        ),
        "recommended_action": (
            "Choose which description is true. If the file belongs in the declared area, move the "
            "unrelated work or dependencies out. If it belongs in the suggested area, update its "
            "location or architecture rule."
        ),
    }


def _coverage_copy(path: str, percent: str, goal: str) -> dict[str, str]:
    coverage_goal = _with_unit(goal, "%", separator="")
    return {
        "summary": f"Tests may miss behavior in {path}",
        "explanation": (
            f"The imported test report says tests ran {percent}% of this file's lines, below the "
            f"project goal of {coverage_goal}. Coverage cannot say whether the tests are good, but "
            "untested branches can break without being noticed."
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
    return value if value == "the configured limit" else f"{value}{separator}{unit}"


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
