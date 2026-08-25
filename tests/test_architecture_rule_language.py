from __future__ import annotations

import sqlite3
from collections import Counter

import pytest

from anaxigraph.architecture_rules import _evaluate_rule, _matches_file_or_group
from anaxigraph.config import RuleConfig


@pytest.fixture
def rule_evidence():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE coverage_measurements (
            snapshot_id INTEGER NOT NULL,
            artifact_id INTEGER,
            line_coverage REAL
        )
        """
    )
    connection.executemany(
        "INSERT INTO coverage_measurements VALUES (1, ?, ?)",
        [(1, 0.42), (2, 0.95), (3, None)],
    )
    files = [
        {
            "artifact_id": 1,
            "path": "src/a.py",
            "artifact_type": "source",
            "lines_of_code": 620,
            "declared_group": "foundation",
            "inferred_group": "delivery",
        },
        {
            "artifact_id": 2,
            "path": "src/b.py",
            "artifact_type": "source",
            "lines_of_code": 20,
            "declared_group": "delivery",
            "inferred_group": "delivery",
        },
    ]
    symbols = [
        {
            "path": "src/a.py",
            "name": "load_config",
            "qualified_name": "Config.load_config",
            "logical_lines": 44,
            "symbol_type": "function",
            "start_line": 10,
            "end_line": 60,
            "complexity": 17,
        }
    ]
    relationships = [
        {"source_artifact_id": 1, "target_artifact_id": 999, "evidence": "missing"},
        {"source_artifact_id": 1, "target_artifact_id": 2, "evidence": "import b"},
    ]
    yield connection, files, symbols, relationships
    connection.close()


@pytest.mark.parametrize(
    ("rule", "finding_type", "summary"),
    [
        (
            RuleConfig(
                "module-size",
                "max_module_loc",
                params={"max": 500, "paths": "src/*.py"},
            ),
            "module_complexity",
            "src/a.py may be doing too many jobs",
        ),
        (
            RuleConfig("function-size", "max_function_lines", params={"max": 25}),
            "long_function",
            "load_config takes a lot of code to do one job",
        ),
        (
            RuleConfig("function-decisions", "max_symbol_complexity", params={"max": 15}),
            "symbol_complexity",
            "load_config makes many decisions in one function",
        ),
        (
            RuleConfig("uses-many", "max_fan_out", params={"max": 12}),
            "high_fan_out",
            "src/a.py reaches into many other modules",
        ),
        (
            RuleConfig("used-by-many", "max_fan_in", params={"max": 12}),
            "high_fan_in",
            "Many modules rely on src/b.py",
        ),
        (
            RuleConfig("dependency-loop", "no_cycles"),
            "dependency_cycle",
            "2 modules depend on one another in a loop",
        ),
        (
            RuleConfig(
                "delivery-boundary",
                "forbid_dependency",
                description="Foundation code must go through the delivery service.",
                params={
                    "from": "src/a.py",
                    "to": "src/b.py",
                    "recommendation": "Call the service interface.",
                },
            ),
            "architecture_violation",
            "src/a.py uses src/b.py, which the project rules do not allow",
        ),
        (
            RuleConfig("group-drift", "declared_group_drift"),
            "architecture_drift",
            "src/a.py no longer fits its declared area",
        ),
        (
            RuleConfig("coverage", "minimum_line_coverage", params={"min": 0.8}),
            "weak_test_coverage",
            "Tests may miss behavior in src/a.py",
        ),
    ],
)
def test_each_architecture_rule_writes_a_plain_explanation(
    rule_evidence, rule, finding_type, summary
):
    connection, files, symbols, relationships = rule_evidence

    findings = _evaluate_rule(
        connection,
        rule=rule,
        repository_id=1,
        snapshot_id=1,
        files=files,
        symbols=symbols,
        relationships=relationships,
        relationship_evidence=relationships,
        file_by_id={item["artifact_id"]: item for item in files},
        fan_in=Counter({2: 18}),
        fan_out=Counter({1: 18}),
        cycles=[{1, 2}],
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.finding_type == finding_type
    assert finding.summary == summary
    assert finding.explanation
    assert finding.recommended_action
    assert "inspection signal" not in finding.explanation
    assert "configured threshold" not in finding.explanation


def test_rule_copy_keeps_machine_evidence_without_using_it_as_the_explanation(rule_evidence):
    connection, files, symbols, relationships = rule_evidence
    rule = RuleConfig("function-decisions", "max_symbol_complexity", params={"max": 15})

    finding = _evaluate_rule(
        connection,
        rule=rule,
        repository_id=1,
        snapshot_id=1,
        files=files,
        symbols=symbols,
        relationships=relationships,
        relationship_evidence=relationships,
        file_by_id={item["artifact_id"]: item for item in files},
        fan_in=Counter(),
        fan_out=Counter(),
        cycles=[],
    )[0]

    assert finding.evidence == ("estimated_cyclomatic_complexity=17",)
    assert "decision score of 17" in finding.explanation
    assert "does not prove the design is wrong" in finding.explanation


def test_unknown_rule_and_empty_boundary_pattern_fail_closed(rule_evidence):
    connection, files, symbols, relationships = rule_evidence

    findings = _evaluate_rule(
        connection,
        rule=RuleConfig("future", "not_supported"),
        repository_id=1,
        snapshot_id=1,
        files=files,
        symbols=symbols,
        relationships=relationships,
        relationship_evidence=relationships,
        file_by_id={item["artifact_id"]: item for item in files},
        fan_in=Counter(),
        fan_out=Counter(),
        cycles=[],
    )

    assert findings == []
    assert _matches_file_or_group(files[0], "") is False
