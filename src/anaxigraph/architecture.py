"""Deterministic architecture metrics, rule evaluation, and finding lifecycle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, RuleConfig, path_matches
from anaxigraph.relationships import (
    AMBIGUOUS_INTERNAL,
    relationship_metadata,
    relationship_quality,
    resolution_status,
)
from anaxigraph.storage import utc_now


@dataclass(frozen=True, slots=True)
class Finding:
    stable_key: str
    finding_type: str
    severity: str
    confidence: float
    summary: str
    explanation: str
    affected_artifacts: tuple[str, ...]
    evidence: tuple[str, ...]
    recommended_action: str
    source: str = "deterministic"


DEFAULT_RULES = (
    RuleConfig(
        rule_id="module-size",
        rule_type="max_module_loc",
        severity="warning",
        description="Large modules are inspection signals for mixed responsibilities.",
        params={"max": 300},
    ),
    RuleConfig(
        rule_id="function-size",
        rule_type="max_function_lines",
        severity="info",
        description="Long functions are inspection signals, not automatic design failures.",
        params={"max": 25},
    ),
    RuleConfig(
        rule_id="symbol-complexity",
        rule_type="max_symbol_complexity",
        severity="warning",
        description="Complex symbols deserve focused tests and possible simplification.",
        params={"max": 10},
    ),
    RuleConfig(
        rule_id="fan-out",
        rule_type="max_fan_out",
        severity="warning",
        description="High fan-out can indicate an orchestration or boundary problem.",
        params={"max": 12},
    ),
    RuleConfig(
        rule_id="dependency-cycles",
        rule_type="no_cycles",
        severity="warning",
        description="Module dependency cycles make isolated changes harder.",
    ),
    RuleConfig(
        rule_id="stale-unreferenced-source",
        rule_type="dead_code",
        severity="info",
        description="Combine static reachability and change age to identify candidates only.",
        params={"minimum_age_days": 90, "minimum_resolution_rate": 0.95},
    ),
)


def evaluate_architecture(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    config: AnaxiGraphConfig,
    manage_finding_lifecycle: bool = True,
) -> list[Finding]:
    files = [
        dict(row)
        for row in connection.execute(
            """
            SELECT fv.*, a.id AS artifact_id, a.artifact_type
            FROM file_versions fv JOIN artifacts a ON a.id = fv.artifact_id
            WHERE fv.snapshot_id = ?
            """,
            (snapshot_id,),
        )
    ]
    symbols = [
        dict(row)
        for row in connection.execute(
            """
            SELECT s.*, fv.path, fv.artifact_id FROM symbols s
            JOIN file_versions fv ON fv.id = s.artifact_version_id
            WHERE fv.snapshot_id = ?
            """,
            (snapshot_id,),
        )
    ]
    relationships = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM relationships WHERE snapshot_id = ? AND target_artifact_id IS NOT NULL",
            (snapshot_id,),
        )
    ]
    file_by_id = {int(row["artifact_id"]): row for row in files}
    fan_out = Counter(int(row["source_artifact_id"]) for row in relationships)
    fan_in = Counter(int(row["target_artifact_id"]) for row in relationships)
    graph: dict[int, set[int]] = defaultdict(set)
    for row in relationships:
        graph[int(row["source_artifact_id"])].add(int(row["target_artifact_id"]))
    cycles = [component for component in _strongly_connected(graph) if len(component) > 1]

    configured_by_id = {rule.rule_id: rule for rule in config.architecture.rules}
    rules = tuple(configured_by_id.get(rule.rule_id, rule) for rule in DEFAULT_RULES)
    rules += tuple(
        rule
        for rule in config.architecture.rules
        if rule.rule_id not in {item.rule_id for item in DEFAULT_RULES}
    )
    _persist_rules(connection, repository_id, rules)

    findings: list[Finding] = []
    for rule in rules:
        if not rule.enabled:
            continue
        findings.extend(
            _evaluate_rule(
                connection,
                rule=rule,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                files=files,
                symbols=symbols,
                relationships=relationships,
                file_by_id=file_by_id,
                fan_in=fan_in,
                fan_out=fan_out,
                cycles=cycles,
            )
        )

    _record_metrics(
        connection,
        snapshot_id=snapshot_id,
        files=files,
        relationships=relationships,
        symbols=symbols,
        fan_in=fan_in,
        fan_out=fan_out,
        cycles=cycles,
        findings=findings,
    )
    if manage_finding_lifecycle:
        _update_finding_lifecycle(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            findings=findings,
        )
    return findings


def _evaluate_rule(
    connection: sqlite3.Connection,
    *,
    rule: RuleConfig,
    repository_id: int,
    snapshot_id: int,
    files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    file_by_id: dict[int, dict[str, Any]],
    fan_in: Counter[int],
    fan_out: Counter[int],
    cycles: list[set[int]],
) -> list[Finding]:
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
    elif rule.rule_type == "dead_code":
        result.extend(
            _dead_code_findings(
                connection,
                rule=rule,
                repository_id=repository_id,
                files=files,
                fan_in=fan_in,
            )
        )
    return result


def _dead_code_findings(
    connection: sqlite3.Connection,
    *,
    rule: RuleConfig,
    repository_id: int,
    files: list[dict[str, Any]],
    fan_in: Counter[int],
) -> list[Finding]:
    if not files:
        return []
    snapshot_id = int(files[0]["snapshot_id"])
    relationship_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT target_artifact_id, metadata_json
            FROM relationships WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        )
    ]
    quality = relationship_quality(relationship_rows)
    resolution_rate = quality["resolution_rate"]
    minimum_resolution = float(rule.params.get("minimum_resolution_rate", 0.95))
    if resolution_rate is None or resolution_rate < minimum_resolution:
        # No incoming edge is not evidence of dead code when too many internal references
        # could not be resolved. Suppression is deliberately safer than a false deletion hint.
        return []
    possible_incoming: set[str] = set()
    for row in relationship_rows:
        if resolution_status(row) != AMBIGUOUS_INTERNAL:
            continue
        possible_incoming.update(relationship_metadata(row).get("candidate_paths") or ())

    age_days = int(rule.params.get("minimum_age_days", 90))
    cutoff = datetime.now(UTC) - timedelta(days=age_days)
    last_changes = {
        row["path"]: row["last_change"]
        for row in connection.execute(
            """
            SELECT path, MAX(committed_at) AS last_change FROM git_changes
            WHERE repository_id = ? GROUP BY path
            """,
            (repository_id,),
        )
    }
    result: list[Finding] = []
    for item in files:
        path = item["path"]
        if (
            item["artifact_type"] != "source"
            or fan_in[int(item["artifact_id"])]
            or path in possible_incoming
            or not _in_rule_scope(path, rule)
            or _looks_like_entrypoint(path)
        ):
            continue
        last_change = last_changes.get(path)
        if not last_change:
            continue
        try:
            changed_at = datetime.fromisoformat(last_change.replace("Z", "+00:00"))
        except ValueError:
            continue
        if changed_at > cutoff:
            continue
        days = (datetime.now(UTC) - changed_at).days
        result.append(
            _finding(
                rule,
                suffix=path,
                finding_type="possible_dead_code",
                summary=f"{path} may be unreachable",
                explanation=(
                    f"No incoming static relationship was detected and the file has not changed for {days} days. "
                    "Dynamic registration and runtime use have not been disproven."
                ),
                paths=(path,),
                evidence=(
                    "incoming_static_relationships=0",
                    f"days_since_change={days}",
                    f"internal_resolution_rate={resolution_rate:.4f}",
                ),
                action="Check route, dependency-injection, event, configuration, and runtime registrations before deletion.",
                confidence=round(min(0.8, 0.45 + 0.3 * resolution_rate), 2),
            )
        )
    return result


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


def _looks_like_entrypoint(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in {
        "__init__.py",
        "__main__.py",
        "main.py",
        "app.py",
        "index.js",
        "index.ts",
        "index.tsx",
        "main.js",
        "main.ts",
        "main.tsx",
        "conftest.py",
    }


def _strongly_connected(graph: dict[int, set[int]]) -> list[set[int]]:
    index = 0
    stack: list[int] = []
    indices: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    on_stack: set[int] = set()
    result: list[set[int]] = []

    def visit(node: int) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, set()):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: set[int] = set()
            while stack:
                target = stack.pop()
                on_stack.remove(target)
                component.add(target)
                if target == node:
                    break
            result.append(component)

    all_nodes = set(graph) | {target for targets in graph.values() for target in targets}
    for node in all_nodes:
        if node not in indices:
            visit(node)
    return result


def _persist_rules(
    connection: sqlite3.Connection, repository_id: int, rules: tuple[RuleConfig, ...]
) -> None:
    for rule in rules:
        connection.execute(
            """
            INSERT INTO architecture_rules(
                repository_id, rule_id, rule_type, severity, description, source, enabled, config_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repository_id, rule_id) DO UPDATE SET
                rule_type = excluded.rule_type, severity = excluded.severity,
                description = excluded.description, source = excluded.source,
                enabled = excluded.enabled, config_json = excluded.config_json
            """,
            (
                repository_id,
                rule.rule_id,
                rule.rule_type,
                rule.severity,
                rule.description,
                "configured" if rule not in DEFAULT_RULES else "builtin",
                int(rule.enabled),
                json.dumps(rule.params, sort_keys=True),
            ),
        )


def _record_metrics(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    files: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    fan_in: Counter[int],
    fan_out: Counter[int],
    cycles: list[set[int]],
    findings: list[Finding],
) -> None:
    repository_metrics = {
        "total_loc": sum(int(item["lines_of_code"]) for item in files),
        "artifact_count": len(files),
        "symbol_count": len(symbols),
        "dependency_count": len(relationships),
        "average_degree": (
            (sum(fan_in.values()) + sum(fan_out.values())) / len(files) if files else 0
        ),
        "maximum_degree": max(
            (fan_in[item["artifact_id"]] + fan_out[item["artifact_id"]] for item in files),
            default=0,
        ),
        "cycle_count": len(cycles),
        "average_complexity": (
            sum(float(item["complexity"]) for item in files) / len(files) if files else 0
        ),
        "architecture_violation_count": sum(
            1 for finding in findings if finding.finding_type == "architecture_violation"
        ),
        "dead_code_candidate_count": sum(
            1 for finding in findings if finding.finding_type == "possible_dead_code"
        ),
    }
    for name, value in repository_metrics.items():
        connection.execute(
            """
            INSERT INTO metrics(snapshot_id, entity_type, entity_id, name, value)
            VALUES (?, 'repository', NULL, ?, ?)
            """,
            (snapshot_id, name, float(value)),
        )
    for item in files:
        artifact_id = int(item["artifact_id"])
        for name, value in (
            ("fan_in", fan_in[artifact_id]),
            ("fan_out", fan_out[artifact_id]),
            ("complexity", item["complexity"]),
            ("lines_of_code", item["lines_of_code"]),
        ):
            connection.execute(
                """
                INSERT INTO metrics(snapshot_id, entity_type, entity_id, name, value)
                VALUES (?, 'artifact', ?, ?, ?)
                """,
                (snapshot_id, artifact_id, name, float(value)),
            )


def _update_finding_lifecycle(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    findings: list[Finding],
) -> None:
    now = utc_now()
    current_keys = {finding.stable_key for finding in findings}
    for finding in findings:
        existing = connection.execute(
            "SELECT id, status FROM findings WHERE repository_id = ? AND stable_key = ?",
            (repository_id, finding.stable_key),
        ).fetchone()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO findings(
                    repository_id, stable_key, finding_type, severity, confidence, summary,
                    explanation, affected_artifacts_json, evidence_json, recommended_action,
                    source, status, first_snapshot_id, last_snapshot_id,
                    first_detected_at, last_detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)
                """,
                (
                    repository_id,
                    finding.stable_key,
                    finding.finding_type,
                    finding.severity,
                    finding.confidence,
                    finding.summary,
                    finding.explanation,
                    json.dumps(finding.affected_artifacts),
                    json.dumps(finding.evidence),
                    finding.recommended_action,
                    finding.source,
                    snapshot_id,
                    snapshot_id,
                    now,
                    now,
                ),
            )
            finding_id = int(cursor.lastrowid)
        else:
            finding_id = int(existing["id"])
            status = "regressed" if existing["status"] == "resolved" else existing["status"]
            connection.execute(
                """
                UPDATE findings SET finding_type = ?, severity = ?, confidence = ?, summary = ?,
                    explanation = ?, affected_artifacts_json = ?, evidence_json = ?,
                    recommended_action = ?, source = ?, status = ?, last_snapshot_id = ?,
                    last_detected_at = ?, resolved_at = CASE WHEN ? = 'regressed' THEN NULL ELSE resolved_at END
                WHERE id = ?
                """,
                (
                    finding.finding_type,
                    finding.severity,
                    finding.confidence,
                    finding.summary,
                    finding.explanation,
                    json.dumps(finding.affected_artifacts),
                    json.dumps(finding.evidence),
                    finding.recommended_action,
                    finding.source,
                    status,
                    snapshot_id,
                    now,
                    status,
                    finding_id,
                ),
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO finding_occurrences(
                finding_id, snapshot_id, detected_at, evidence_json
            ) VALUES (?, ?, ?, ?)
            """,
            (finding_id, snapshot_id, now, json.dumps(finding.evidence)),
        )

    active_rows = connection.execute(
        """
        SELECT id, stable_key, status FROM findings
        WHERE repository_id = ? AND status NOT IN ('resolved', 'dismissed')
        """,
        (repository_id,),
    ).fetchall()
    for row in active_rows:
        if row["stable_key"] not in current_keys:
            connection.execute(
                "UPDATE findings SET status = 'resolved', resolved_at = ? WHERE id = ?",
                (now, row["id"]),
            )
