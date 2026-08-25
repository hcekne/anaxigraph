"""Deterministic architecture rule evaluators and finding construction."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from typing import Any

from anaxigraph.architecture_dead_code import dead_code_findings
from anaxigraph.architecture_models import Finding
from anaxigraph.config import RuleConfig, path_matches


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
    if rule.rule_type == "dead_code":
        return _dead_code_findings(
            connection,
            rule=rule,
            repository_id=repository_id,
            files=files,
            fan_in=fan_in,
            relationship_evidence=relationship_evidence,
        )
    result: list[Finding] = []
    maximum = float(rule.params.get("max", 0) or 0)
    if rule.rule_type == "max_module_loc":
        for item in files:
            reviewable = item["artifact_type"] in {"source", "test"} or bool(
                rule.params.get("include_reference", False)
            )
            if (
                reviewable
                and _in_rule_scope(item["path"], rule)
                and item["lines_of_code"] > maximum
            ):
                result.append(
                    _finding(
                        rule,
                        suffix=item["path"],
                        finding_type="module_complexity",
                        summary=f"{item['path']} is {item['lines_of_code']} LOC",
                        explanation=(
                            f"The module exceeds the {int(maximum)} LOC inspection threshold. "
                            "Size alone is not a violation; verify whether distinct change reasons have emerged."
                        ),
                        paths=(item["path"],),
                        evidence=(f"lines_of_code={item['lines_of_code']}",),
                        action="Inspect responsibilities and split only if doing so reduces coupling or change reasons.",
                    )
                )
    elif rule.rule_type == "max_function_lines":
        for item in symbols:
            if (
                _in_rule_scope(item["path"], rule)
                and item["logical_lines"] > maximum
                and item["symbol_type"] in {"function", "method", "api_endpoint", "event_handler"}
            ):
                result.append(
                    _finding(
                        rule,
                        suffix=f"{item['path']}:{item['qualified_name']}",
                        finding_type="long_function",
                        summary=f"{item['name']} spans {item['logical_lines']} logical lines",
                        explanation=(
                            f"The symbol exceeds the {int(maximum)}-line inspection signal. "
                            "Review readability and responsibility before changing its shape."
                        ),
                        paths=(item["path"],),
                        evidence=(
                            f"symbol={item['qualified_name']}",
                            f"lines={item['start_line']}-{item['end_line']}",
                        ),
                        action="Keep cohesive logic together; extract only a separately meaningful operation.",
                    )
                )
    elif rule.rule_type == "max_symbol_complexity":
        for item in symbols:
            if (
                item["symbol_type"]
                in {"function", "method", "api_endpoint", "event_handler", "react_component"}
                and _in_rule_scope(item["path"], rule)
                and item["complexity"] > maximum
            ):
                result.append(
                    _finding(
                        rule,
                        suffix=f"{item['path']}:{item['qualified_name']}",
                        finding_type="symbol_complexity",
                        summary=f"{item['name']} has estimated complexity {item['complexity']:g}",
                        explanation=f"Deterministic branch counting exceeds the configured {maximum:g} threshold.",
                        paths=(item["path"],),
                        evidence=(f"estimated_cyclomatic_complexity={item['complexity']:g}",),
                        action="Confirm focused branch tests, then simplify decision structure where it improves clarity.",
                    )
                )
    elif rule.rule_type in {"max_fan_out", "max_fan_in"}:
        values = fan_out if rule.rule_type == "max_fan_out" else fan_in
        direction = "outgoing" if rule.rule_type == "max_fan_out" else "incoming"
        finding_type = "high_fan_out" if rule.rule_type == "max_fan_out" else "high_fan_in"
        for artifact_id, count in values.items():
            item = file_by_id.get(artifact_id)
            if item and count > maximum and _in_rule_scope(item["path"], rule):
                result.append(
                    _finding(
                        rule,
                        suffix=item["path"],
                        finding_type=finding_type,
                        summary=f"{item['path']} has {count} {direction} dependencies",
                        explanation=(
                            f"The module exceeds the configured {int(maximum)} {direction}-dependency signal."
                        ),
                        paths=(item["path"],),
                        evidence=(f"{direction}_dependencies={count}",),
                        action=(
                            "Inspect whether orchestration responsibilities or boundary stability justify the coupling."
                        ),
                    )
                )
    elif rule.rule_type == "no_cycles":
        for component in cycles:
            paths = tuple(
                sorted(file_by_id[item]["path"] for item in component if item in file_by_id)
            )
            if not paths or not any(_in_rule_scope(path, rule) for path in paths):
                continue
            result.append(
                _finding(
                    rule,
                    suffix="|".join(paths),
                    finding_type="dependency_cycle",
                    summary=f"Dependency cycle spans {len(paths)} modules",
                    explanation=(
                        "These modules form a circular dependency chain: following imports or "
                        "references from any module eventually leads back to it. That makes the "
                        "modules harder to change or test independently; it does not mean the "
                        "application is necessarily broken."
                    ),
                    paths=paths,
                    evidence=paths,
                    action=(
                        "Inspect the dependency edges, choose the smallest shared contract, and "
                        "move or invert that contract so dependencies flow in one direction."
                    ),
                )
            )
    elif rule.rule_type == "forbid_dependency":
        source_pattern = str(rule.params.get("from") or "")
        target_pattern = str(rule.params.get("to") or "")
        for edge in relationships:
            source = file_by_id.get(int(edge["source_artifact_id"]))
            target = file_by_id.get(int(edge["target_artifact_id"]))
            if not source or not target:
                continue
            if _matches_file_or_group(source, source_pattern) and _matches_file_or_group(
                target, target_pattern
            ):
                result.append(
                    _finding(
                        rule,
                        suffix=f"{source['path']}->{target['path']}",
                        finding_type="architecture_violation",
                        summary=f"Forbidden dependency from {source['path']} to {target['path']}",
                        explanation=rule.description
                        or "The dependency crosses a declared architecture boundary.",
                        paths=(source["path"], target["path"]),
                        evidence=(edge["evidence"],),
                        action=str(
                            rule.params.get("recommendation")
                            or "Depend on an allowed boundary or interface."
                        ),
                    )
                )
    elif rule.rule_type == "declared_group_drift":
        for item in files:
            if (
                item["declared_group"]
                and item["inferred_group"]
                and item["declared_group"] != item["inferred_group"]
                and _in_rule_scope(item["path"], rule)
            ):
                result.append(
                    _finding(
                        rule,
                        suffix=item["path"],
                        finding_type="architecture_drift",
                        summary=f"{item['path']} differs from its declared group",
                        explanation=(
                            f"Declared as {item['declared_group']}; dependency/path inference suggests "
                            f"{item['inferred_group']}."
                        ),
                        paths=(item["path"],),
                        evidence=(
                            f"declared_group={item['declared_group']}",
                            f"inferred_group={item['inferred_group']}",
                        ),
                        action="Confirm the declaration or move the dependency responsibility back across the boundary.",
                    )
                )
    elif rule.rule_type == "minimum_line_coverage":
        minimum = float(rule.params.get("min", 0.8))
        coverage_by_artifact = {
            int(row["artifact_id"]): row["line_coverage"]
            for row in connection.execute(
                """
                SELECT artifact_id, MAX(line_coverage) AS line_coverage
                FROM coverage_measurements
                WHERE snapshot_id = ? AND artifact_id IS NOT NULL GROUP BY artifact_id
                """,
                (snapshot_id,),
            )
        }
        for artifact_id, coverage in coverage_by_artifact.items():
            item = file_by_id.get(artifact_id)
            if (
                item
                and coverage is not None
                and coverage < minimum
                and _in_rule_scope(item["path"], rule)
            ):
                result.append(
                    _finding(
                        rule,
                        suffix=item["path"],
                        finding_type="weak_test_coverage",
                        summary=f"{item['path']} has {coverage:.1%} line coverage",
                        explanation=f"Coverage is below the configured {minimum:.1%} threshold.",
                        paths=(item["path"],),
                        evidence=(f"line_coverage={coverage:.4f}",),
                        action="Add behavior-focused tests around the unexercised decisions and boundaries.",
                    )
                )
    return result


def _dead_code_findings(*args: Any, **kwargs: Any) -> list[Finding]:
    return dead_code_findings(*args, path_matcher=path_matches, **kwargs)


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
