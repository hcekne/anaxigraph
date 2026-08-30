from __future__ import annotations

import pytest

from anaxigraph.finding_language import evidence_sentences, plain_language_contract
from anaxigraph.persistence.finding_read import finding_priority


def _finding(
    *,
    finding_type: str,
    summary: str,
    explanation: str,
    evidence: list[str],
    paths: list[str] | None = None,
) -> dict:
    return {
        "stable_key": f"finding:{finding_type}",
        "finding_type": finding_type,
        "severity": "warning",
        "confidence": 1.0,
        "summary": summary,
        "explanation": explanation,
        "affected_artifacts": paths or ["src/anaxigraph/config.py"],
        "evidence": evidence,
        "recommended_action": "Confirm focused tests, then simplify the decision structure.",
        "source": "deterministic",
        "status": "new",
    }


def test_complexity_finding_has_a_complete_plain_language_contract():
    finding = _finding(
        finding_type="symbol_complexity",
        summary="load_config has a branch score of 17; this project reviews functions above 15",
        explanation=(
            "More branches create more possible outcomes to understand and test. They can still "
            "belong together when they answer one clear question."
        ),
        evidence=["estimated_cyclomatic_complexity=17"],
    )
    finding.update(finding_priority(finding, {}))

    language = finding["plain_language"]
    assert language["version"] == "plain-language-v2"
    assert language["facts"] == [
        "This function has a branch score of 17.",
        (
            "The score starts at 1 and rises for each if-statement, loop, case, exception handler, "
            "or combined condition."
        ),
    ]
    assert "possible outcomes" in language["why_it_matters"]
    assert "one clear question" in language["why_it_matters"]
    assert "scan the repository again" in language["how_to_check"]
    assert "not a claim that the design" in language["confidence"]["meaning"]
    assert "does not decide whether the design is good or bad" in language["source"]["meaning"]
    assert "not a grade for the code" in language["priority"]["meaning"]


@pytest.mark.parametrize(
    ("finding_type", "evidence", "paths", "expected"),
    [
        (
            "module_complexity",
            ["lines_of_code=620", "review_limit_lines=500"],
            None,
            "This project asks for a closer look above 500 lines.",
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
            "This function has a branch score of 17.",
        ),
        (
            "high_fan_out",
            ["outgoing_dependencies=18", "review_limit_dependencies=12"],
            None,
            "This file directly uses 18 other files.",
        ),
        (
            "high_fan_in",
            ["incoming_dependencies=18"],
            None,
            "This file is directly used by 18 other files.",
        ),
        (
            "dependency_cycle",
            ["src/a.py", "src/b.py"],
            ["src/a.py", "src/b.py"],
            "The loop of files that use one another contains src/a.py, src/b.py.",
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
            (
                "The analyzer did not find framework setup or code that registers it when the "
                "application starts or runs."
            ),
        ),
        (
            "future_check",
            ["custom_measurement=7"],
            None,
            "AnaxiGraph measured custom measurement as 7.",
        ),
        (
            "future_check",
            ["free-form evidence"],
            None,
            "AnaxiGraph recorded this evidence: free-form evidence.",
        ),
    ],
)
def test_every_finding_kind_explains_its_evidence(finding_type, evidence, paths, expected):
    finding = _finding(
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
    assert semantic["version"] == "plain-language-v2"
    assert semantic["next_step"].startswith("Read the affected code")
    assert semantic["confidence"]["value"] == 1.0
    assert "An AI suggested this" in semantic["source"]["meaning"]
    assert "idea to check" in semantic["confidence"]["meaning"]
    assert "before making more changes" in semantic["level"]["meaning"]
    assert semantic["status"]["meaning"].startswith("No decision")
    assert semantic["priority"]["guidance"] == "Check this before the other findings."

    unknown = plain_language_contract(
        {"severity": "project-specific", "confidence": -1, "source": "imported-tool"},
        priority_score=1,
        priority_label="Low",
        priority_reasons=[],
        false_positive_conditions=[],
    )
    assert unknown["confidence"]["value"] == 0.0
    assert "imported-tool" in unknown["source"]["meaning"]
    assert "repository supplied" in unknown["level"]["meaning"]


def test_ai_finding_copy_is_rewritten_in_the_primary_explanation():
    language = plain_language_contract(
        {
            "finding_type": "future_check",
            "summary": "The provider boundary may leak selection policy.",
            "explanation": "A semantic review found a fragile module boundary.",
            "recommended_action": "Preserve public contracts during the structural change.",
            "source": "semantic",
            "evidence": [],
        },
        priority_score=50,
        priority_label="Medium",
        priority_reasons=[],
        false_positive_conditions=["Runtime registration may supply another caller."],
    )

    visible = " ".join(
        [
            language["what"],
            language["why_it_matters"],
            language["next_step"],
            *language["when_no_change_may_be_needed"],
        ]
    ).lower()
    assert "shared interface used to call providers" in visible
    assert "rules for choosing an implementation" in visible
    assert "ai review of what the code does" in visible
    assert "way the code is divided between files" in visible
    assert "behavior and names that other code relies on" in visible
    assert "moving, merging, or splitting code" in visible
    assert "code registered while the application starts or runs" in visible

    free_form = evidence_sentences(
        {
            "finding_type": "future_check",
            "evidence": ["The module boundary hides a public contract."],
        }
    )
    assert "way the code is divided between files" in free_form[0]
    assert "behavior and names that other code relies on" in free_form[0]
