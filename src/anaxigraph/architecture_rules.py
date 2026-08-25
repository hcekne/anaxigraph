"""Deterministic architecture rule evaluators and finding construction."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

from anaxigraph.architecture_dead_code import dead_code_findings
from anaxigraph.architecture_models import Finding
from anaxigraph.config import RuleConfig, path_matches


@dataclass(frozen=True, slots=True)
class _RuleContext:
    connection: sqlite3.Connection
    rule: RuleConfig
    repository_id: int
    snapshot_id: int
    files: list[dict[str, Any]]
    symbols: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    relationship_evidence: list[dict[str, Any]]
    file_by_id: dict[int, dict[str, Any]]
    fan_in: Counter[int]
    fan_out: Counter[int]
    cycles: list[set[int]]


def _evaluate_rule(
    connection: sqlite3.Connection,
    *,
    rule: RuleConfig,
    repository_id: int,
    snapshot_id: int,
    files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    relationship_evidence: list[dict[str, Any]],
    file_by_id: dict[int, dict[str, Any]],
    fan_in: Counter[int],
    fan_out: Counter[int],
    cycles: list[set[int]],
) -> list[Finding]:
    context = _RuleContext(
        connection,
        rule,
        repository_id,
        snapshot_id,
        files,
        symbols,
        relationships,
        relationship_evidence,
        file_by_id,
        fan_in,
        fan_out,
        cycles,
    )
    if rule.rule_type == "dead_code":
        return _dead_code(context)
    evaluator = _RULE_EVALUATORS.get(rule.rule_type)
    return evaluator(context) if evaluator else []


def _dead_code(context: _RuleContext) -> list[Finding]:
    return _dead_code_findings(
        context.connection,
        rule=context.rule,
        repository_id=context.repository_id,
        files=context.files,
        fan_in=context.fan_in,
        relationship_evidence=context.relationship_evidence,
    )


def _module_size(context: _RuleContext) -> list[Finding]:
    maximum = _maximum(context.rule)
    result = []
    for item in context.files:
        reviewable = item["artifact_type"] in {"source", "test"} or bool(
            context.rule.params.get("include_reference", False)
        )
        if (
            reviewable
            and _in_rule_scope(item["path"], context.rule)
            and item["lines_of_code"] > maximum
        ):
            result.append(_module_size_finding(context.rule, item, int(maximum)))
    return result


def _module_size_finding(rule: RuleConfig, item: dict[str, Any], maximum: int) -> Finding:
    return _finding(
        rule,
        suffix=item["path"],
        finding_type="module_complexity",
        summary=(
            f"{item['path']} has {item['lines_of_code']} lines; this project reviews files "
            f"above {maximum} lines"
        ),
        explanation=(
            "A large file becomes hard to change when it contains jobs that do not belong "
            "together. Size alone does not mean the file should be split; one clear job may "
            "need a lot of code."
        ),
        paths=(item["path"],),
        evidence=(f"lines_of_code={item['lines_of_code']}",),
        action=(
            "Name the file's main jobs. If two jobs can change for different reasons, move the "
            "smaller one into a clearly named module. If the file has one clear job, keep it together."
        ),
    )


def _function_size(context: _RuleContext) -> list[Finding]:
    maximum = _maximum(context.rule)
    kinds = {"function", "method", "api_endpoint", "event_handler"}
    return [
        _function_size_finding(context.rule, item, int(maximum))
        for item in context.symbols
        if _in_rule_scope(item["path"], context.rule)
        and item["logical_lines"] > maximum
        and item["symbol_type"] in kinds
    ]


def _function_size_finding(rule: RuleConfig, item: dict[str, Any], maximum: int) -> Finding:
    return _finding(
        rule,
        suffix=f"{item['path']}:{item['qualified_name']}",
        finding_type="long_function",
        summary=(
            f"{item['name']} uses {item['logical_lines']} lines; this project reviews functions "
            f"above {maximum} lines"
        ),
        explanation=(
            "A long function becomes hard to follow when it mixes separate jobs or makes a reader "
            "remember too many details at once. Length alone is not a reason to split a clear, "
            "step-by-step function."
        ),
        paths=(item["path"],),
        evidence=(
            f"symbol={item['qualified_name']}",
            f"lines={item['start_line']}-{item['end_line']}",
        ),
        action=(
            "Name each step in the function. If one step has its own clear input and result, move "
            "that step into a named helper and keep tests around both outcomes. Otherwise leave the "
            "steps together."
        ),
    )


def _symbol_complexity(context: _RuleContext) -> list[Finding]:
    maximum = _maximum(context.rule)
    kinds = {"function", "method", "api_endpoint", "event_handler", "react_component"}
    return [
        _symbol_complexity_finding(context.rule, item, maximum)
        for item in context.symbols
        if item["symbol_type"] in kinds
        and _in_rule_scope(item["path"], context.rule)
        and item["complexity"] > maximum
    ]


def _symbol_complexity_finding(rule: RuleConfig, item: dict[str, Any], maximum: float) -> Finding:
    return _finding(
        rule,
        suffix=f"{item['path']}:{item['qualified_name']}",
        finding_type="symbol_complexity",
        summary=(
            f"{item['name']} has a branch score of {item['complexity']:g}; this project reviews "
            f"functions above {maximum:g}"
        ),
        explanation=(
            "More branches create more possible outcomes to understand and test. They can still "
            "belong together when they answer one clear question."
        ),
        paths=(item["path"],),
        evidence=(f"estimated_cyclomatic_complexity={item['complexity']:g}",),
        action=(
            "Group the branches by the question they answer. If one group answers a separate "
            "question, move it into a clearly named helper and test both outcomes. If every branch "
            "belongs to one decision, keep it together."
        ),
    )


def _dependency_degree(context: _RuleContext) -> list[Finding]:
    outgoing = context.rule.rule_type == "max_fan_out"
    values = context.fan_out if outgoing else context.fan_in
    direction = "outgoing" if outgoing else "incoming"
    finding_type = "high_fan_out" if outgoing else "high_fan_in"
    maximum = _maximum(context.rule)
    result = []
    for artifact_id, count in values.items():
        item = context.file_by_id.get(artifact_id)
        if item and count > maximum and _in_rule_scope(item["path"], context.rule):
            result.append(
                _dependency_finding(
                    context.rule, item, count, int(maximum), direction, finding_type
                )
            )
    return result


def _dependency_finding(
    rule: RuleConfig,
    item: dict[str, Any],
    count: int,
    maximum: int,
    direction: str,
    finding_type: str,
) -> Finding:
    summary = (
        f"{item['path']} directly uses {count} modules; this project reviews files above {maximum} modules"
        if direction == "outgoing"
        else f"{count} modules directly use {item['path']}; this project reviews files above {maximum} modules"
    )
    return _finding(
        rule,
        suffix=item["path"],
        finding_type=finding_type,
        summary=summary,
        explanation=_dependency_explanation(direction),
        paths=(item["path"],),
        evidence=(f"{direction}_dependencies={count}",),
        action=_dependency_action(direction),
    )


def _cycles(context: _RuleContext) -> list[Finding]:
    result = []
    for component in context.cycles:
        paths = tuple(
            sorted(
                context.file_by_id[item]["path"] for item in component if item in context.file_by_id
            )
        )
        if paths and any(_in_rule_scope(path, context.rule) for path in paths):
            result.append(_cycle_finding(context.rule, paths))
    return result


def _cycle_finding(rule: RuleConfig, paths: tuple[str, ...]) -> Finding:
    return _finding(
        rule,
        suffix="|".join(paths),
        finding_type="dependency_cycle",
        summary=f"{len(paths)} modules depend on one another in a loop",
        explanation=(
            "Following the imports or references eventually leads back to the starting module. "
            "This can make the modules harder to understand and test separately, but it does not "
            "mean the application is broken."
        ),
        paths=paths,
        evidence=paths,
        action=(
            "Find the smallest link that can point the other way. Move the shared idea into a small "
            "interface or module, then make the remaining dependencies flow in one direction."
        ),
    )


def _forbidden_dependencies(context: _RuleContext) -> list[Finding]:
    source_pattern = str(context.rule.params.get("from") or "")
    target_pattern = str(context.rule.params.get("to") or "")
    result = []
    for edge in context.relationships:
        source = context.file_by_id.get(int(edge["source_artifact_id"]))
        target = context.file_by_id.get(int(edge["target_artifact_id"]))
        if not source or not target:
            continue
        if _matches_file_or_group(source, source_pattern) and _matches_file_or_group(
            target, target_pattern
        ):
            result.append(_boundary_finding(context.rule, source, target, edge))
    return result


def _boundary_finding(
    rule: RuleConfig,
    source: dict[str, Any],
    target: dict[str, Any],
    edge: dict[str, Any],
) -> Finding:
    return _finding(
        rule,
        suffix=f"{source['path']}->{target['path']}",
        finding_type="architecture_violation",
        summary=f"{source['path']} uses {target['path']}, which the project rules do not allow",
        explanation=_boundary_explanation(rule.description),
        paths=(source["path"], target["path"]),
        evidence=(str(edge["evidence"]),),
        action=_boundary_action(rule.params.get("recommendation")),
    )


def _group_drift(context: _RuleContext) -> list[Finding]:
    return [
        _drift_finding(context.rule, item)
        for item in context.files
        if item["declared_group"]
        and item["inferred_group"]
        and item["declared_group"] != item["inferred_group"]
        and _in_rule_scope(item["path"], context.rule)
    ]


def _drift_finding(rule: RuleConfig, item: dict[str, Any]) -> Finding:
    return _finding(
        rule,
        suffix=item["path"],
        finding_type="architecture_drift",
        summary=f"{item['path']} no longer fits its declared area",
        explanation=(
            f"The project places it in {item['declared_group']}, but its path and dependencies make "
            f"it behave more like part of {item['inferred_group']}. Either the map is out of date "
            "or the file has started doing work that belongs elsewhere."
        ),
        paths=(item["path"],),
        evidence=(
            f"declared_group={item['declared_group']}",
            f"inferred_group={item['inferred_group']}",
        ),
        action=(
            "Choose which description is true. If the file belongs in the declared area, move the "
            "unrelated work or dependencies out. If it belongs in the suggested area, update its "
            "location or architecture rule."
        ),
    )


def _weak_coverage(context: _RuleContext) -> list[Finding]:
    minimum = float(context.rule.params.get("min", 0.8))
    coverage = _coverage_by_artifact(context.connection, context.snapshot_id)
    result = []
    for artifact_id, value in coverage.items():
        item = context.file_by_id.get(artifact_id)
        if item and value < minimum and _in_rule_scope(item["path"], context.rule):
            result.append(_coverage_finding(context.rule, item, value, minimum))
    return result


def _coverage_by_artifact(connection: sqlite3.Connection, snapshot_id: int) -> dict[int, float]:
    return {
        int(row["artifact_id"]): float(row["line_coverage"])
        for row in connection.execute(
            """
            SELECT artifact_id, MAX(line_coverage) AS line_coverage
            FROM coverage_measurements
            WHERE snapshot_id = ? AND artifact_id IS NOT NULL GROUP BY artifact_id
            """,
            (snapshot_id,),
        )
        if row["line_coverage"] is not None
    }


def _coverage_finding(
    rule: RuleConfig, item: dict[str, Any], coverage: float, minimum: float
) -> Finding:
    return _finding(
        rule,
        suffix=item["path"],
        finding_type="weak_test_coverage",
        summary=(
            f"Tests run {coverage:.0%} of {item['path']}; this project's goal is {minimum:.0%}"
        ),
        explanation=(
            "Line coverage cannot tell whether tests are good, but behavior in lines that never "
            "run during tests can break without being noticed."
        ),
        paths=(item["path"],),
        evidence=(f"line_coverage={coverage:.4f}",),
        action=(
            "Find the decisions and error cases the report did not run. Add small tests that check "
            "their visible behavior instead of tests that only touch extra lines."
        ),
    )


def _maximum(rule: RuleConfig) -> float:
    return float(rule.params.get("max", 0) or 0)


def _dead_code_findings(*args: Any, **kwargs: Any) -> list[Finding]:
    return dead_code_findings(*args, path_matcher=path_matches, **kwargs)


def _dependency_explanation(direction: str) -> str:
    if direction == "outgoing":
        return (
            "A file that reaches into many parts of the project can mix several jobs and become "
            "hard to test in isolation. This can be exactly right when the file is a coordinator "
            "for one clear workflow."
        )
    return (
        "A behavior change here can affect many callers. That is normal when this file is a stable "
        "shared promise with broad tests."
    )


def _dependency_action(direction: str) -> str:
    if direction == "outgoing":
        return (
            "Group the dependencies by the job they support. If one group belongs to a separate "
            "job, move that job behind a small, clearly named interface."
        )
    return (
        "Treat its public behavior as a shared promise. Find its callers and tests before changing "
        "it. Split it only when callers use clearly unrelated parts."
    )


def _boundary_explanation(description: str) -> str:
    base = (
        "The repository's architecture rules say these parts should stay separate. Direct use "
        "makes that separation harder to protect."
    )
    return f"{base} Project note: {description}" if description else base


def _boundary_action(recommendation: Any) -> str:
    base = "Change the source file so it reaches the needed behavior through an allowed module."
    return f"{base} Project guidance: {recommendation}" if recommendation else base


def _finding(
    rule: RuleConfig,
    *,
    suffix: str,
    finding_type: str,
    summary: str,
    explanation: str,
    paths: tuple[str, ...],
    evidence: tuple[str, ...],
    action: str,
    confidence: float = 1.0,
) -> Finding:
    digest = hashlib.sha256(suffix.encode()).hexdigest()[:20]
    return Finding(
        stable_key=f"{rule.rule_id}:{digest}",
        finding_type=finding_type,
        severity=rule.severity,
        confidence=confidence,
        summary=summary,
        explanation=explanation,
        affected_artifacts=paths,
        evidence=evidence,
        recommended_action=action,
    )


def _in_rule_scope(path: str, rule: RuleConfig) -> bool:
    patterns = rule.params.get("paths")
    if not patterns:
        return True
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(path_matches(path, str(pattern)) for pattern in patterns)


def _matches_file_or_group(item: dict[str, Any], pattern: str) -> bool:
    if not pattern:
        return False
    return (
        path_matches(item["path"], pattern)
        or item.get("declared_group") == pattern
        or item.get("inferred_group") == pattern
    )


_RULE_EVALUATORS = {
    "max_module_loc": _module_size,
    "max_function_lines": _function_size,
    "max_symbol_complexity": _symbol_complexity,
    "max_fan_out": _dependency_degree,
    "max_fan_in": _dependency_degree,
    "no_cycles": _cycles,
    "forbid_dependency": _forbidden_dependencies,
    "declared_group_drift": _group_drift,
    "minimum_line_coverage": _weak_coverage,
}
