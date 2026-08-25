from __future__ import annotations

import pytest

from anaxigraph.finding_language import (
    evidence_sentences,
    normalize_finding_copy,
    plain_language_contract,
)
from anaxigraph.persistence.finding_read import finding_priority


def _legacy_finding(
    *,
    finding_type: str,
    summary: str,
    explanation: str,
    evidence: list[str],
    paths: list[str] | None = None,
) -> dict:
    return {
        "stable_key": f"legacy:{finding_type}",
        "finding_type": finding_type,
        "severity": "warning",
        "confidence": 1.0,
        "summary": summary,
        "explanation": explanation,
        "affected_artifacts": paths or ["src/anaxigraph/config.py"],
        "evidence": evidence,
        "recommended_action": "Confirm focused branch tests, then simplify decision structure.",
        "source": "deterministic",
        "status": "new",
    }


def test_legacy_complexity_copy_becomes_a_complete_plain_language_contract():
    finding = normalize_finding_copy(
        _legacy_finding(
            finding_type="symbol_complexity",
            summary="load_config has estimated complexity 17",
            explanation="Deterministic branch counting exceeds the configured 15 threshold.",
            evidence=["estimated_cyclomatic_complexity=17"],
        )
    )
    finding.update(finding_priority(finding, {}))

    assert finding["summary"] == "load_config makes many decisions in one function"
    assert "decision score of 17" in finding["explanation"]
    assert "does not prove the design is wrong" in finding["explanation"]
    assert "Deterministic branch counting" not in str(finding)
    language = finding["plain_language"]
    assert language["facts"] == ["The branch count gives it a decision score of 17."]
    assert "not a claim that the design" in language["confidence"]["meaning"]
    assert "An AI did not decide" in language["source"]["meaning"]
    assert "not a grade for the code" in language["priority"]["meaning"]


@pytest.mark.parametrize(
    ("finding_type", "summary", "explanation", "evidence", "expected"),
    [
        (
            "module_complexity",
            "src/anaxigraph/config.py is 620 LOC",
            "The module exceeds the 500 LOC inspection threshold.",
            ["lines_of_code=620"],
            "src/anaxigraph/config.py may be doing too many jobs",
        ),
        (
            "long_function",
            "prepare spans 44 logical lines",
            "The symbol exceeds the 25-line inspection signal.",
            ["symbol=prepare", "lines=10-60"],
            "prepare takes a lot of code to do one job",
        ),
        (
            "high_fan_out",
            "src/anaxigraph/config.py has 18 outgoing dependencies",
            "The module exceeds the configured 12 outgoing-dependency signal.",
            ["outgoing_dependencies=18"],
            "src/anaxigraph/config.py reaches into many other modules",
        ),
        (
            "high_fan_in",
            "src/anaxigraph/config.py has 18 incoming dependencies",
            "The module exceeds the configured 12 incoming-dependency signal.",
            ["incoming_dependencies=18"],
            "Many modules rely on src/anaxigraph/config.py",
        ),
        (
            "dependency_cycle",
            "Dependency cycle spans 2 modules",
            "The modules participate in a strongly connected dependency component.",
            ["src/anaxigraph/config.py", "src/anaxigraph/cli.py"],
            "2 modules depend on one another in a loop",
        ),
        (
            "architecture_violation",
            "Forbidden dependency from src/anaxigraph/config.py to src/anaxigraph/cli.py",
            "The dependency crosses a declared architecture boundary.",
            ["import cli"],
            (
                "src/anaxigraph/config.py uses src/anaxigraph/cli.py, which the project rules "
                "do not allow"
            ),
        ),
        (
            "architecture_drift",
            "src/anaxigraph/config.py differs from its declared group",
            "Declared and inferred groups differ.",
            ["declared_group=foundation", "inferred_group=delivery"],
            "src/anaxigraph/config.py no longer fits its declared area",
        ),
        (
            "weak_test_coverage",
            "src/anaxigraph/config.py has 42.0% line coverage",
            "Coverage is below the configured 80.0% threshold.",
            ["line_coverage=0.4200"],
            "Tests may miss behavior in src/anaxigraph/config.py",
        ),
        (
            "possible_dead_code",
            "src/anaxigraph/config.py may be unreachable",
            "No incoming static relationship was found.",
            ["incoming_static_relationships=0", "days_since_change=130"],
            "src/anaxigraph/config.py may no longer be used",
        ),
    ],
)
def test_known_legacy_findings_are_upgraded_without_a_rescan(
    finding_type, summary, explanation, evidence, expected
):
    paths = (
        ["src/anaxigraph/config.py", "src/anaxigraph/cli.py"]
        if finding_type in {"dependency_cycle", "architecture_violation"}
        else None
    )
    finding = normalize_finding_copy(
        _legacy_finding(
            finding_type=finding_type,
            summary=summary,
            explanation=explanation,
            evidence=evidence,
            paths=paths,
        )
    )

    assert finding["summary"] == expected
    assert finding["explanation"]
    assert finding["recommended_action"]


@pytest.mark.parametrize(
    ("finding_type", "evidence", "paths", "expected"),
    [
        (
            "module_complexity",
            ["lines_of_code=620", "review_limit_lines=500"],
            None,
            "The project starts a closer review above 500 lines.",
        ),
        (
            "long_function",
            [
                "symbol=Config.load",
                "logical_lines=44",
                "source_lines=10-60",
                "review_limit_lines=25",
            ],
            None,
            "It appears on source lines 10-60.",
        ),
        (
            "symbol_complexity",
            ["decision_score=17", "review_limit_decision_score=15"],
            None,
            "The branch count gives it a decision score of 17.",
        ),
        (
            "high_fan_out",
            ["outgoing_dependencies=18", "review_limit_dependencies=12"],
            None,
            "The module uses 18 directly.",
        ),
        (
            "high_fan_in",
            ["incoming_dependencies=18"],
            None,
            "Other modules use 18 directly.",
        ),
        (
            "dependency_cycle",
            ["src/a.py", "src/b.py"],
            ["src/a.py", "src/b.py"],
            "The dependency loop contains src/a.py, src/b.py.",
        ),
        (
            "architecture_violation",
            ["import b"],
            ["src/a.py", "src/b.py"],
            "src/a.py directly refers to src/b.py.",
        ),
        (
            "architecture_drift",
            ["declared_group=foundation", "inferred_group=delivery"],
            None,
            "The project places this file in foundation.",
        ),
        (
            "weak_test_coverage",
            ["line_coverage=0.42", "coverage_goal=0.8"],
            None,
            "The project's coverage goal is 80%.",
        ),
        (
            "possible_dead_code",
            [
                "incoming_static_relationships=0",
                "days_since_change=130",
                "detected_entry_points=0",
                "detected_registrations=0",
            ],
            None,
            "The analyzer did not find a framework or runtime registration for it.",
        ),
        (
            "future_check",
            ["custom_measurement=7"],
            None,
            "The check recorded custom measurement as 7.",
        ),
        (
            "future_check",
            ["free-form evidence"],
            None,
            "The check recorded: free-form evidence.",
        ),
    ],
)
def test_every_finding_kind_explains_its_evidence(finding_type, evidence, paths, expected):
    finding = _legacy_finding(
        finding_type=finding_type,
        summary="Already plain",
        explanation="Already clear.",
        evidence=evidence,
        paths=paths,
    )

    assert expected in evidence_sentences(finding)


def test_plain_language_contract_explains_semantic_and_unknown_sources():
    semantic = plain_language_contract(
        {
            "finding_type": "future_check",
            "severity": "critical",
            "confidence": 2,
            "source": "semantic",
            "evidence": ["line_coverage=unknown"],
        },
        priority_score=82,
        priority_label="Urgent",
        priority_reasons=["It affects a public promise."],
        false_positive_conditions=["The evidence is out of date."],
    )

    assert semantic["what"] == "AnaxiGraph found something to inspect."
    assert semantic["next_step"].startswith("Read the affected code")
    assert semantic["confidence"]["value"] == 1.0
    assert "An AI suggested this" in semantic["source"]["meaning"]
    assert "Treat it as evidence to check" in semantic["confidence"]["meaning"]
    assert semantic["level"]["meaning"].startswith("The project treats this as urgent")

    unknown = plain_language_contract(
        {"severity": "project-specific", "confidence": -1, "source": "imported-tool"},
        priority_score=1,
        priority_label="Low",
        priority_reasons=[],
        false_positive_conditions=[],
    )
    assert unknown["confidence"]["value"] == 0.0
    assert "imported-tool" in unknown["source"]["meaning"]
    assert "architecture rule" in unknown["level"]["meaning"]


def test_unrecognized_old_copy_is_preserved_instead_of_guessed():
    known_types = [
        "module_complexity",
        "long_function",
        "symbol_complexity",
        "high_fan_out",
        "dependency_cycle",
        "architecture_violation",
        "architecture_drift",
        "weak_test_coverage",
        "possible_dead_code",
        "future_check",
    ]
    for finding_type in known_types:
        finding = _legacy_finding(
            finding_type=finding_type,
            summary="A person already rewrote this",
            explanation="Keep this exact explanation.",
            evidence=[],
        )

        normalized = normalize_finding_copy(finding)

        assert normalized["summary"] == "A person already rewrote this"
        assert normalized["explanation"] == "Keep this exact explanation."


def test_legacy_upgrade_keeps_project_specific_boundary_guidance():
    finding = _legacy_finding(
        finding_type="architecture_violation",
        summary="Forbidden dependency from src/a.py to src/b.py",
        explanation="The UI layer must go through the application service.",
        evidence=["import b"],
        paths=["src/a.py", "src/b.py"],
    )

    normalized = normalize_finding_copy(finding)

    assert "Project note: The UI layer" in normalized["explanation"]
    assert "Project guidance: Confirm focused branch tests" in normalized["recommended_action"]


def test_legacy_upgrade_names_a_configured_limit_when_old_copy_omits_the_number():
    finding = _legacy_finding(
        finding_type="module_complexity",
        summary="src/a.py is 620 LOC",
        explanation="This file is above the configured limit.",
        evidence=["lines_of_code=620"],
        paths=["src/a.py"],
    )

    normalized = normalize_finding_copy(finding)

    assert "at the configured limit" in normalized["explanation"]
