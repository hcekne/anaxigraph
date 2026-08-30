from __future__ import annotations

import copy

import pytest

from anaxigraph.pattern_evaluation_contract import (
    PATTERN_ANALYSIS_KINDS,
    PATTERN_EVALUATION_SCHEMA,
    PATTERN_PRESENCE,
    PATTERN_RECOMMENDATIONS,
    PATTERN_REVIEW_CONTRACT_VERSION,
    PATTERN_REVIEW_SCHEMA,
    PATTERN_SCORE_CONTRACT_VERSION,
    PATTERN_SCORE_DIMENSIONS,
    finalized_evaluation,
    pattern_response_name,
    pattern_response_schema,
    score_values,
    validated_pattern_response,
)
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.semantic_pattern_requests import _constraints
from anaxigraph.semantic_taxonomy_contract import (
    response_contract_name,
    response_schema,
    validated_agent_semantic_response,
)

FINGERPRINT = "a" * 64
TARGET_KEY = "module:src/provider.py"
PATTERN_KEY = "provider-abstraction"


def test_pattern_contract_owns_query_and_prompt_vocabulary():
    properties = PATTERN_EVALUATION_SCHEMA["properties"]

    assert properties["presence"]["enum"] == list(PATTERN_PRESENCE)
    assert properties["recommendation"]["enum"] == list(PATTERN_RECOMMENDATIONS)
    assert _constraints()["independent_dimensions"] == list(PATTERN_SCORE_DIMENSIONS)


def _request(kind="pattern_assessment"):
    return {
        "analysis_kind": kind,
        "candidate": {
            "input_fingerprint": FINGERPRINT,
            "pattern_key": PATTERN_KEY,
            "target": {"key": TARGET_KEY},
        },
    }


def _score(value, name):
    return {
        "value": value,
        "rationale": f"Evidence-backed {name} rationale.",
        "evidence": [f"{name} evidence"],
    }


def _evaluation(**score_overrides):
    values = {
        "applicability": 80,
        "suitability": 75,
        "conformance": 20,
        "opportunity": 75,
        "confidence": 82,
        "benefit": 78,
        "urgency": 45,
        "execution_safety": 70,
        "migration_cost": 35,
        **score_overrides,
    }
    return {
        "score_contract_version": PATTERN_SCORE_CONTRACT_VERSION,
        "candidate_fingerprint": FINGERPRINT,
        "pattern_key": PATTERN_KEY,
        "target_key": TARGET_KEY,
        "summary": "A provider boundary fits the target and is not yet present.",
        "presence": "absent",
        "recommendation": "introduce",
        "scores": {name: _score(values[name], name) for name in PATTERN_SCORE_DIMENSIONS},
        "rationale": "Multiple concrete providers share one stable operation contract.",
        "evidence": ["Two provider implementations expose equivalent operations."],
        "counter_evidence": ["Only one provider is active in the current configuration."],
        "affected_targets": [TARGET_KEY],
        "local_precedents": ["module:src/storage.py"],
        "alternatives": ["strategy"],
        "prerequisites": ["Freeze the shared request and response semantics."],
        "risks": ["A broad base class could leak provider-specific behavior."],
        "invariants": ["Each provider retains equivalent observable behavior."],
        "invalidation_conditions": ["A second implementation is removed permanently."],
    }


def _review(evaluation=None, verdict="approve"):
    return {
        "review_contract_version": PATTERN_REVIEW_CONTRACT_VERSION,
        "candidate_fingerprint": FINGERPRINT,
        "verdict": verdict,
        "summary": "The scope, pattern identity, evidence, and scores are coherent.",
        "issues": [],
        "evaluation": evaluation or _evaluation(),
        "competing_interpretations": [],
        "confidence": 80,
        "evidence": ["Reviewed deterministic signals and counter-evidence."],
    }


def test_assessment_preserves_all_independent_scores_and_provenance():
    result = validated_pattern_response(
        _evaluation(),
        _request(),
        input_tokens=120,
        output_tokens=80,
    )

    assert set(score_values(result.value)) == set(PATTERN_SCORE_DIMENSIONS)
    assert len(set(score_values(result.value).values())) > 5
    assert result.confidence == 0.82
    assert result.input_tokens == 120
    assert result.output_tokens == 80
    assert result.evidence == tuple(result.value["evidence"])


def test_high_suitability_and_conformance_cannot_be_a_false_refactor_opportunity():
    evaluation = _evaluation(suitability=90, conformance=90, opportunity=20)
    evaluation["presence"] = "present"
    evaluation["recommendation"] = "retain"

    validated = validated_pattern_response(evaluation, _request())
    assert validated.value["recommendation"] == "retain"

    invalid = copy.deepcopy(evaluation)
    invalid["scores"]["opportunity"]["value"] = 80
    with pytest.raises(ValueError, match="cannot create high opportunity"):
        validated_pattern_response(invalid, _request())

    invalid = copy.deepcopy(evaluation)
    invalid["recommendation"] = "improve_conformance"
    with pytest.raises(ValueError, match="require retain or no_action"):
        validated_pattern_response(invalid, _request())


def test_introduce_recommendation_cannot_claim_pattern_is_already_conformant():
    evaluation = _evaluation(conformance=60)

    with pytest.raises(ValueError, match="introduce recommendation"):
        validated_pattern_response(evaluation, _request())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("candidate_fingerprint", "b" * 64, "candidate_fingerprint"),
        ("pattern_key", "adapter", "pattern_key"),
        ("target_key", "module:other.py", "target_key"),
        ("score_contract_version", "pattern-scores-v2", "score contract"),
    ],
)
def test_assessment_identity_and_contract_must_match_candidate(field, value, message):
    evaluation = _evaluation()
    evaluation[field] = value

    with pytest.raises(ValueError, match=message):
        validated_pattern_response(evaluation, _request())


def test_strict_assessment_schema_rejects_missing_and_extra_fields():
    missing = _evaluation()
    missing.pop("counter_evidence")
    with pytest.raises(SemanticAnalysisError, match="missing required fields"):
        validated_pattern_response(missing, _request())

    extra = _evaluation()
    extra["magic_score"] = 99
    with pytest.raises(SemanticAnalysisError, match="unsupported fields"):
        validated_pattern_response(extra, _request())


def test_independent_review_carries_the_full_finalized_evaluation():
    evaluation = _evaluation(opportunity=60, confidence=70)
    review = _review(evaluation)

    result = validated_pattern_response(review, _request("pattern_review"))

    assert result.confidence == 0.7
    assert finalized_evaluation(result.value) == evaluation
    assert result.value["evaluation"] is evaluation


def test_revision_requires_an_issue_and_may_correct_the_scores():
    revised = _evaluation(opportunity=45, confidence=65)
    review = _review(revised, verdict="revise")
    with pytest.raises(ValueError, match="requires at least one critique issue"):
        validated_pattern_response(review, _request("pattern_review"))

    review["issues"] = [
        {
            "kind": "score_consistency",
            "severity": "warning",
            "explanation": "Migration cost was understated.",
            "evidence": ["Three callers cross the proposed boundary."],
            "correction": "Lower opportunity and execution safety.",
        }
    ]
    validated = validated_pattern_response(review, _request("pattern_review"))
    assert validated.value["verdict"] == "revise"


def test_disagreement_is_retained_instead_of_fabricating_consensus():
    review = _review(verdict="retain_competing")
    with pytest.raises(ValueError, match="requires a competing interpretation"):
        validated_pattern_response(review, _request("pattern_review"))

    review["competing_interpretations"] = [
        {
            "pattern_key": "strategy",
            "rationale": "The variation may be algorithmic rather than provider-specific.",
            "evidence": ["Implementations share transport and differ in selection logic."],
            "conditions": ["Prefer strategy if no external provider boundary appears."],
        }
    ]
    validated = validated_pattern_response(review, _request("pattern_review"))
    assert validated.value["verdict"] == "retain_competing"


def test_review_identity_and_version_are_strict():
    review = _review()
    review["candidate_fingerprint"] = "b" * 64
    with pytest.raises(ValueError, match="candidate_fingerprint"):
        validated_pattern_response(review, _request("pattern_review"))

    review = _review()
    review["review_contract_version"] = "pattern-review-v2"
    with pytest.raises(ValueError, match="review contract"):
        validated_pattern_response(review, _request("pattern_review"))


def test_response_dispatch_is_narrow_and_versioned():
    assert PATTERN_ANALYSIS_KINDS == {"pattern_assessment", "pattern_review"}
    assessment = pattern_response_schema(_request())
    review = pattern_response_schema(_request("pattern_review"))
    assert assessment is not PATTERN_EVALUATION_SCHEMA
    assert review is not PATTERN_REVIEW_SCHEMA
    assert assessment["properties"]["candidate_fingerprint"]["enum"] == [FINGERPRINT]
    assert assessment["properties"]["pattern_key"]["enum"] == [PATTERN_KEY]
    assert assessment["properties"]["target_key"]["enum"] == [TARGET_KEY]
    assert review["properties"]["candidate_fingerprint"]["enum"] == [FINGERPRINT]
    assert review["properties"]["evaluation"]["properties"]["pattern_key"]["enum"] == [PATTERN_KEY]
    assert pattern_response_name(_request()) == "pattern_evaluation"
    assert pattern_response_name({"analysis_kind": "intrinsic"}) is None
    with pytest.raises(ValueError, match="unsupported pattern analysis kind"):
        validated_pattern_response({}, {"analysis_kind": "intrinsic"})


@pytest.mark.parametrize(
    ("kind", "schema", "name"),
    [
        ("pattern_assessment", PATTERN_EVALUATION_SCHEMA, "pattern_evaluation"),
        ("pattern_review", PATTERN_REVIEW_SCHEMA, "pattern_review"),
    ],
)
def test_shared_semantic_dispatch_uses_pattern_contracts(kind, schema, name):
    request = _request(kind)
    value = _evaluation() if kind == "pattern_assessment" else _review()

    assert response_schema(request)["required"] == schema["required"]
    assert response_contract_name(request) == name
    assert validated_agent_semantic_response(value, request).value == value
