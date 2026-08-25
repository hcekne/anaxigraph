"""Plain-language architecture finding contract for people and coding agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from anaxigraph.finding_language_legacy import legacy_replacement

FINDING_LANGUAGE_VERSION = "plain-language-v1"

_CHECK_LABELS = {
    "module_complexity": "Large file",
    "long_function": "Long function",
    "symbol_complexity": "Many decisions in one function",
    "high_fan_out": "Module uses many other modules",
    "high_fan_in": "Many modules use this module",
    "dependency_cycle": "Modules depend on one another in a loop",
    "architecture_violation": "Project boundary crossed",
    "architecture_drift": "File does not match its declared area",
    "weak_test_coverage": "Tests miss part of a file",
    "possible_dead_code": "File may no longer be used",
}


def normalize_finding_copy(finding: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade known legacy detector wording without rewriting stored evidence."""

    item = dict(finding)
    replacement = legacy_replacement(item)
    if replacement is not None:
        item.update(replacement)
    return item


def plain_language_contract(
    finding: Mapping[str, Any],
    *,
    priority_score: int,
    priority_label: str,
    priority_reasons: list[str],
    false_positive_conditions: list[str],
) -> dict[str, Any]:
    """Return one explicit explanation shared by REST, MCP, CLI, and dashboard clients."""

    confidence = max(0.0, min(1.0, float(finding.get("confidence") or 0)))
    source = str(finding.get("source") or "deterministic")
    finding_type = str(finding.get("finding_type") or "observation")
    return {
        "version": FINDING_LANGUAGE_VERSION,
        "what": str(finding.get("summary") or "AnaxiGraph found something to inspect."),
        "why_it_matters": str(
            finding.get("explanation")
            or "This may make the code harder to understand, test, or change safely."
        ),
        "next_step": str(
            finding.get("recommended_action")
            or "Read the affected code and make the smallest change that improves clarity."
        ),
        "facts": evidence_sentences(finding),
        "check": {
            "id": finding_type,
            "label": _CHECK_LABELS.get(finding_type, _humanize(finding_type)),
        },
        "level": {
            "id": str(finding.get("severity") or "info"),
            "meaning": _severity_meaning(str(finding.get("severity") or "info")),
        },
        "confidence": {
            "value": confidence,
            "meaning": _confidence_meaning(confidence, source),
        },
        "source": {"id": source, "meaning": _source_meaning(source)},
        "priority": {
            "score": priority_score,
            "label": priority_label,
            "meaning": (
                f"A queue score of {priority_score} out of 100 puts this in the "
                f"{priority_label.lower()}-priority group. The score only decides what appears "
                "first; it is not a grade for the code."
            ),
            "reasons": priority_reasons,
        },
        "when_no_change_may_be_needed": false_positive_conditions,
    }


def evidence_sentences(finding: Mapping[str, Any]) -> list[str]:
    """Translate lossless detector data into short statements without hiding the raw values."""

    raw = [str(value) for value in finding.get("evidence") or ()]
    values = _evidence_values(raw)
    finding_type = str(finding.get("finding_type") or "")
    facts = _known_facts(finding_type, values, finding)
    if facts:
        return facts
    return [_generic_fact(value) for value in raw[:8]]


def _generic_fact(value: str) -> str:
    if "=" not in value:
        return f"The check recorded: {value}."
    key, recorded = value.split("=", 1)
    label = _humanize(key).lower()
    return f"The check recorded {label} as {recorded}."


def _known_facts(
    finding_type: str,
    values: dict[str, str],
    finding: Mapping[str, Any],
) -> list[str]:
    builder = _FACT_BUILDERS.get(finding_type)
    return builder(values, finding) if builder is not None else []


def _module_facts(values: Mapping[str, str], _finding: Mapping[str, Any]) -> list[str]:
    lines = values.get("lines_of_code")
    return _measurement("The file contains", lines, "lines of code", values) if lines else []


def _function_facts(values: Mapping[str, str], _finding: Mapping[str, Any]) -> list[str]:
    facts = []
    if symbol := values.get("symbol"):
        facts.append(f"The measured function or method is {symbol}.")
    if logical := values.get("logical_lines"):
        facts.extend(_measurement("Its logic uses", logical, "lines", values))
    if source_lines := values.get("source_lines") or values.get("lines"):
        facts.append(f"It appears on source lines {source_lines}.")
    return facts


def _complexity_facts(values: Mapping[str, str], _finding: Mapping[str, Any]) -> list[str]:
    score = values.get("estimated_cyclomatic_complexity") or values.get("decision_score")
    if not score:
        return []
    return _measurement("The branch count gives it a decision score of", score, "", values)


def _fan_out_facts(values: Mapping[str, str], finding: Mapping[str, Any]) -> list[str]:
    return _dependency_facts(
        values, finding, key="outgoing_dependencies", subject="The module uses"
    )


def _fan_in_facts(values: Mapping[str, str], finding: Mapping[str, Any]) -> list[str]:
    return _dependency_facts(
        values, finding, key="incoming_dependencies", subject="Other modules use"
    )


def _dependency_facts(
    values: Mapping[str, str],
    _finding: Mapping[str, Any],
    *,
    key: str,
    subject: str,
) -> list[str]:
    count = values.get(key)
    return _measurement(subject, count, "directly", values) if count else []


def _cycle_facts(_values: Mapping[str, str], finding: Mapping[str, Any]) -> list[str]:
    paths = [str(path) for path in finding.get("affected_artifacts") or ()]
    return [f"The dependency loop contains {', '.join(paths)}."] if paths else []


def _boundary_facts(_values: Mapping[str, str], finding: Mapping[str, Any]) -> list[str]:
    paths = [str(path) for path in finding.get("affected_artifacts") or ()]
    return [f"{paths[0]} directly refers to {paths[1]}."] if len(paths) >= 2 else []


def _drift_facts(values: Mapping[str, str], _finding: Mapping[str, Any]) -> list[str]:
    declared = values.get("declared_group")
    inferred = values.get("inferred_group")
    if not declared or not inferred:
        return []
    return [
        f"The project places this file in {declared}.",
        f"Its path and dependencies make it behave more like part of {inferred}.",
    ]


def _coverage_facts(values: Mapping[str, str], _finding: Mapping[str, Any]) -> list[str]:
    coverage = values.get("line_coverage")
    return (
        _measurement("Tests ran", _percent(coverage), "of this file's lines", values)
        if coverage
        else []
    )


def _measurement(prefix: str, value: str, unit: str, values: Mapping[str, str]) -> list[str]:
    sentence = " ".join(part for part in (prefix, value, unit) if part).strip() + "."
    limit_item = next(
        (
            (key, values[key])
            for key in values
            if key.startswith("review_limit_") or key == "coverage_goal"
        ),
        None,
    )
    if limit_item is None:
        return [sentence]
    key, limit = limit_item
    if key == "coverage_goal":
        return [sentence, f"The project's coverage goal is {_percent(limit)}."]
    limit_unit = {
        "review_limit_lines": " lines",
        "review_limit_dependencies": " modules",
        "review_limit_decision_score": "",
    }.get(key, "")
    return [sentence, f"The project starts a closer review above {limit}{limit_unit}."]


def _dead_code_facts(values: Mapping[str, str], _finding: Mapping[str, Any]) -> list[str]:
    facts = []
    if values.get("incoming_static_relationships") == "0":
        facts.append("No indexed source file points to this file.")
    if days := values.get("days_since_change"):
        facts.append(f"Git history shows no change to it for {days} days.")
    if values.get("detected_entry_points") == "0":
        facts.append("The analyzer did not find it registered as a program entry point.")
    if values.get("detected_registrations") == "0":
        facts.append("The analyzer did not find a framework or runtime registration for it.")
    return facts


def _evidence_values(raw: list[str]) -> dict[str, str]:
    return {key: value for item in raw if "=" in item for key, value in (item.split("=", 1),)}


def _percent(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    return f"{number * 100:.0f}%" if number <= 1 else f"{number:g}%"


def _source_meaning(source: str) -> str:
    if source == "deterministic":
        return (
            "AnaxiGraph measured this directly from source code or repository data. An AI did not "
            "decide that the design is bad."
        )
    if source in {"semantic", "llm", "coding_agent"}:
        return (
            "An AI suggested this from the indexed semantic evidence; verify it against the code."
        )
    return f"The finding came from the {source} detector source."


def _confidence_meaning(confidence: float, source: str) -> str:
    percent = f"{confidence:.0%}"
    if source == "deterministic":
        return (
            f"AnaxiGraph is {percent} confident that it measured the stated condition correctly. "
            "This is not a claim that the design is that likely to be wrong."
        )
    return (
        f"The semantic detector reports {percent} confidence in this interpretation. Treat it as "
        "evidence to check, not as certainty."
    )


def _severity_meaning(severity: str) -> str:
    return {
        "info": "Useful to know about; no change may be needed.",
        "warning": "Worth reviewing soon; it is not proof that anything is broken.",
        "error": "The project treats this as a likely architecture problem.",
        "critical": "The project treats this as urgent because it may block safe changes.",
    }.get(severity, "This level comes from the repository's architecture rule.")


def _humanize(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("_") if part) or "Architecture check"


_FACT_BUILDERS = {
    "module_complexity": _module_facts,
    "long_function": _function_facts,
    "symbol_complexity": _complexity_facts,
    "high_fan_out": _fan_out_facts,
    "high_fan_in": _fan_in_facts,
    "dependency_cycle": _cycle_facts,
    "architecture_violation": _boundary_facts,
    "architecture_drift": _drift_facts,
    "weak_test_coverage": _coverage_facts,
    "possible_dead_code": _dead_code_facts,
}
