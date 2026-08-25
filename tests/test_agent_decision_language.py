from __future__ import annotations

from anaxigraph.agent_decision_language import (
    CONSOLIDATION_LANGUAGE_VERSION,
    DEAD_CODE_LANGUAGE_VERSION,
    consolidation_explanation,
    dead_code_explanation,
    dead_code_policy_explanation,
)


def test_consolidation_explanation_leads_with_a_decision_and_explains_the_score():
    result = consolidation_explanation(
        path="src/service.py",
        status="candidate",
        recommendation="merge",
        score=82,
        rationale="Both modules choose and run providers.",
        candidates=["src/provider_service.py"],
        evidence=["The same responsibility appears in both modules."],
        counter_evidence=["Their public return types differ."],
    )

    assert result["version"] == CONSOLIDATION_LANGUAGE_VERSION
    assert result["conclusion"].startswith("Consider combining src/service.py")
    assert result["what_to_do"].startswith("Compare src/service.py")
    assert result["reasons_to_be_careful"][0] == ("Their results returned to callers differ.")
    assert result["evidence_strength"] == {
        "value": 82,
        "meaning": (
            "Support for this recommendation is strong. This number measures the available "
            "evidence for this suggestion; it is not a code-quality grade and does not authorize "
            "a refactor."
        ),
    }


def test_incomplete_consolidation_evidence_says_to_leave_the_code_alone():
    result = consolidation_explanation(
        path="src/service.py",
        status="review",
        recommendation="split",
        score=61,
        rationale="The module owns two responsibilities.",
        candidates=[],
        evidence=["Configuration and execution live together."],
        counter_evidence=[],
    )

    assert result["conclusion"].startswith("Do not merge or split src/service.py")
    assert result["what_to_do"].startswith("Leave src/service.py as it is")
    assert "not strong and balanced enough" in result["reasons_to_be_careful"][0]
    assert "change together" in result["reasons_to_be_careful"][1]


def test_dead_code_explanation_translates_reachability_shorthand_and_blocks_deletion():
    result = dead_code_explanation(
        module="src/service.py",
        path_or_symbol="src/service.py:legacy_adapter",
        status="suppressed",
        rationale="No static callers were observed.",
        evidence=["incoming references=0"],
        counter_evidence=["May be loaded from configuration."],
        suppression_reasons=[
            "No trusted deterministic reachability finding corroborates it.",
            "Dynamic registration, reflection, configuration, and generated wiring remain caveats.",
        ],
        verification="Inspect configured adapter names.",
    )

    assert result["version"] == DEAD_CODE_LANGUAGE_VERSION
    assert result["conclusion"].startswith("Do not delete src/service.py:legacy_adapter")
    assert result["what_anaxigraph_saw"][1] == (
        "The indexed source contains no direct source-code link to this item."
    )
    assert "source map did not independently confirm" in result["why_it_is_not_safe_to_remove"][1]
    assert "code that registers it when the application starts or runs" in result["deletion_rule"]
    assert result["what_to_do"].startswith(
        "Before changing src/service.py:legacy_adapter, inspect configured adapter names"
    )
    assert "code that looks up names while running" in result["why_it_is_not_safe_to_remove"][2]

    visible = str(result).lower()
    for unexplained in (
        "incoming static link",
        "deterministic reachability",
        "runtime registration",
        "semantic review",
    ):
        assert unexplained not in visible


def test_dead_code_structured_evidence_says_what_each_measure_means():
    result = dead_code_explanation(
        module="src/service.py",
        path_or_symbol="src/service.py:legacy_adapter",
        status="candidate",
        rationale="This item may be unused.",
        evidence=[
            "days_since_change=130",
            "internal_resolution_rate=0.82",
            "registration_capability=structural",
            "detected_registrations=0",
            "parse_status=partial",
        ],
        counter_evidence=[],
        suppression_reasons=[],
        verification="Search settings and startup code.",
    )

    observations = " ".join(result["what_anaxigraph_saw"])
    assert "no change to this item for 130 days" in observations
    assert "connected 82% of internal source-code references" in observations
    assert "parsed code structure" in observations
    assert "places that register this item for later use" in observations
    assert "understood only part of this file's structure" in observations


def test_dead_code_collection_summary_never_calls_a_candidate_safe_to_delete():
    result = dead_code_policy_explanation(2)

    assert result["version"] == DEAD_CODE_LANGUAGE_VERSION
    assert result["summary"] == (
        "AnaxiGraph found 2 items worth checking, but it is not saying that any of them can be "
        "deleted yet."
    )
    assert "Only remove it after those checks agree" in result["what_to_do"]
    assert "runtime registration" not in str(result).lower()
