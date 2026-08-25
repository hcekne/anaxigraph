"""Plain-language architecture finding contract for people and coding agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from anaxigraph.finding_language_legacy import legacy_replacement
from anaxigraph.semantic_file_language import explain_specialist_terms

FINDING_LANGUAGE_VERSION = "plain-language-v2"

_CHECK_LABELS = {
    "module_complexity": "File has many lines",
    "long_function": "Function has many lines",
    "symbol_complexity": "Function has many branches",
    "high_fan_out": "File directly uses many other files",
    "high_fan_in": "Many files directly use this file",
    "dependency_cycle": "Files depend on one another in a loop",
    "architecture_violation": "A direct code link breaks a project rule",
    "architecture_drift": "File does not match its declared area",
    "weak_test_coverage": "Tests miss part of a file",
    "possible_dead_code": "File may no longer be used",
}

_COMMON_CAVEATS = {
    "long_function": [
        "The function tells one clear, step-by-step story even though it is long.",
        "Splitting it would make the order of the steps harder to see.",
    ],
    "symbol_complexity": [
        "Every branch answers part of one clear business question.",
        "Focused tests cover each important outcome, and splitting the logic would hide the story.",
    ],
    "module_complexity": [
        "The file has one clear job even though that job needs a lot of code.",
        "Splitting it would force closely related code to jump between files.",
    ],
    "high_fan_out": [
        "The file intentionally coordinates the listed files for one clear workflow.",
        "Every direct code link supports the same job rather than a separate responsibility.",
    ],
    "high_fan_in": [
        "The file intentionally offers behavior that many callers are expected to use.",
        "Tests cover that caller-visible behavior, and it changes rarely.",
    ],
    "architecture_drift": [
        "The path-based guess placed the file in the wrong architecture area.",
        "The declared area intentionally owns the dependency that caused the different guess.",
    ],
    "architecture_violation": [
        "The repository rule is out of date or was written too broadly.",
        "The code link exists only for building or type checking, or points to the wrong file.",
    ],
}


def normalize_finding_copy(finding: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade known legacy detector wording without rewriting stored evidence."""

    item = dict(finding)
    replacement = legacy_replacement(item)
    if replacement is not None:
        item.update(replacement)
    return item


def finding_caveats(finding_type: str) -> list[str]:
    """Explain, in ordinary language, when the measured condition may be intentional."""

    if "dead" in finding_type or "unused" in finding_type:
        return [
            "Settings, a framework, generated code, or code that builds a name while running uses it.",
            "The analyzer could not see code that registers it when the application starts or "
            "runs, or another link created while running.",
        ]
    if "cycle" in finding_type:
        return [
            "The loop exists only for building or type checking and does not connect runtime behavior.",
            "An unclear import was linked to the wrong module.",
        ]
    if "coverage" in finding_type:
        return [
            "The coverage report is old or does not include the relevant test run.",
            "The uncovered lines are generated, unreachable, or contain no behavior worth testing.",
        ]
    return list(
        _COMMON_CAVEATS.get(
            finding_type,
            [
                "The repository intentionally allows this structure.",
                "Missing or unclear code-link data changes what the finding means.",
            ],
        )
    )


def plain_language_contract(
    finding: Mapping[str, Any],
    *,
    priority_score: int,
    priority_label: str,
    priority_reasons: list[str],
    false_positive_conditions: list[str],
) -> dict[str, Any]:
    """Return one explicit explanation shared by REST, MCP, CLI, and dashboard clients."""

    return {
        "version": FINDING_LANGUAGE_VERSION,
        "what": explain_specialist_terms(
            finding.get("summary") or "AnaxiGraph found something to inspect."
        ),
        "why_it_matters": explain_specialist_terms(
            finding.get("explanation")
            or "This may make the code harder to understand, test, or change safely."
        ),
        "next_step": explain_specialist_terms(
            finding.get("recommended_action")
            or "Read the affected code and make the smallest change that improves clarity."
        ),
        "facts": evidence_sentences(finding),
        "how_to_check": (
            "Run the focused tests, scan the repository again, and compare this finding with the "
            "new result. A changed count is evidence; it does not by itself prove the design is better."
        ),
        **_machine_context(finding, priority_score, priority_label, priority_reasons),
        "when_no_change_may_be_needed": [
            explain_specialist_terms(item) for item in false_positive_conditions
        ],
    }


def _machine_context(
    finding: Mapping[str, Any], score: int, label: str, reasons: list[str]
) -> dict[str, Any]:
    confidence = max(0.0, min(1.0, float(finding.get("confidence") or 0)))
    source = str(finding.get("source") or "deterministic")
    finding_type = str(finding.get("finding_type") or "observation")
    severity = str(finding.get("severity") or "info")
    status = str(finding.get("status") or "new")
    return {
        "status": {"id": status, "meaning": _status_meaning(status)},
        "check": {
            "id": finding_type,
            "label": _CHECK_LABELS.get(finding_type, _humanize(finding_type)),
        },
        "level": {"id": severity, "meaning": _severity_meaning(severity)},
        "confidence": {
            "value": confidence,
            "meaning": _confidence_meaning(confidence, source),
        },
        "source": {"id": source, "meaning": _source_meaning(source)},
        "priority": {
            "score": score,
            "label": label,
            "guidance": _priority_guidance(label),
            "meaning": (
                f"The sorting score is {score} out of 100. It only decides which finding "
                "AnaxiGraph shows first; it is not a grade for the code."
            ),
            "reasons": reasons,
        },
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
        readable = explain_specialist_terms(value).rstrip(".")
        return f"AnaxiGraph recorded this evidence: {readable}."
    key, recorded = value.split("=", 1)
    label = _humanize(key).lower()
    return f"AnaxiGraph measured {label} as {recorded}."


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
    facts = [
        f"This function has a branch score of {score}.",
        (
            "The score starts at 1 and rises for each if-statement, loop, case, exception handler, "
            "or combined condition."
        ),
    ]
    limit = values.get("review_limit_decision_score")
    if limit:
        facts.append(f"This project asks for a closer look when the branch score is above {limit}.")
    return facts


def _fan_out_facts(values: Mapping[str, str], finding: Mapping[str, Any]) -> list[str]:
    return _dependency_facts(values, finding, key="outgoing_dependencies", incoming=False)


def _fan_in_facts(values: Mapping[str, str], finding: Mapping[str, Any]) -> list[str]:
    return _dependency_facts(values, finding, key="incoming_dependencies", incoming=True)


def _dependency_facts(
    values: Mapping[str, str],
    _finding: Mapping[str, Any],
    *,
    key: str,
    incoming: bool,
) -> list[str]:
    count = values.get(key)
    if not count:
        return []
    facts = [
        f"This file is directly used by {count} other files."
        if incoming
        else f"This file directly uses {count} other files."
    ]
    if limit := values.get("review_limit_dependencies"):
        facts.append(f"This project asks for a closer look above {limit} direct file links.")
    return facts


def _cycle_facts(_values: Mapping[str, str], finding: Mapping[str, Any]) -> list[str]:
    paths = [str(path) for path in finding.get("affected_artifacts") or ()]
    return [f"The loop of files that use one another contains {', '.join(paths)}."] if paths else []


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
        f"Its path and direct code links make it behave more like part of {inferred}.",
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
        "review_limit_dependencies": " direct file links",
        "review_limit_decision_score": "",
    }.get(key, "")
    return [sentence, f"This project asks for a closer look above {limit}{limit_unit}."]


def _dead_code_facts(values: Mapping[str, str], _finding: Mapping[str, Any]) -> list[str]:
    facts = []
    if values.get("incoming_static_relationships") == "0":
        facts.append("No indexed source file points to this file.")
    if days := values.get("days_since_change"):
        facts.append(f"Git history shows no change to it for {days} days.")
    if values.get("detected_entry_points") == "0":
        facts.append("The analyzer did not find it registered as a program entry point.")
    if values.get("detected_registrations") == "0":
        facts.append(
            "The analyzer did not find framework setup or code that registers it when the "
            "application starts or runs."
        )
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
            "AnaxiGraph counted or traced this directly in repository data. It describes what "
            "exists; it does not decide whether the design is good or bad."
        )
    if source in {"semantic", "llm", "coding_agent"}:
        return "An AI suggested this from saved descriptions of what the code does; verify it against the code."
    return f"AnaxiGraph received this finding from the source named {source}."


def _confidence_meaning(confidence: float, source: str) -> str:
    percent = f"{confidence:.0%}"
    if source == "deterministic":
        return (
            f"AnaxiGraph is {percent} confident that it measured the stated condition correctly. "
            "This is not a claim that the design is that likely to be wrong."
        )
    return (
        f"The AI reports {percent} confidence in this explanation. Treat it as an idea to check "
        "against the code, not as a fact."
    )


def _severity_meaning(severity: str) -> str:
    return {
        "info": "Keep this in mind; no code change may be needed.",
        "warning": "Look at this when working in the affected code; nothing is proven broken.",
        "error": "The project's own rule says this is probably an architecture problem.",
        "critical": "The project's own rule says to check this before making more changes.",
    }.get(severity, "The repository supplied this level for the finding.")


def _status_meaning(status: str) -> str:
    return {
        "new": "No decision has been recorded for this finding yet.",
        "acknowledged": "This has been reviewed, but no final decision has been recorded.",
        "planned": "This finding has been selected for agent work.",
        "accepted": "The current design has been accepted for now; later scans still monitor it.",
        "dismissed": "This finding was judged not useful for the current design.",
        "resolved": "A later scan no longer found the same condition.",
        "regressed": "The condition disappeared in an earlier scan and has now returned.",
    }.get(status, "The repository supplied this workflow state.")


def _priority_guidance(label: str) -> str:
    return {
        "Urgent": "Check this before the other findings.",
        "High": "Check this soon.",
        "Medium": "Check this when you work in this part of the code.",
        "Low": "Keep this as background information; it may not need a change.",
    }.get(label, "Use the explanation to decide when this deserves attention.")


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
