"""Caller obligations are named graph contracts, with no fabricated behavior checks."""

import pytest
from annotation_contract_support import annotation_case

from anaxigraph.knowledge_annotation_contract import validated_annotation
from anaxigraph.semantic_model_contract import SemanticAnalysisError


def test_caller_obligations_are_written_once_and_bound_to_owning_functions():
    obligations = ["Close the session the constructor opened", "Call configure before calculation"]
    request, value = annotation_case(*obligations)
    result = validated_annotation(value, request=request)
    contract = result.value["contracts"][0]
    assert contract["invariants"] == obligations
    assert contract["functions"] == ["pkg.core.calculate"]
    assert len(result.value["contracts"]) == 1
    assert "caller_obligations" not in result.value["functions"][0]


def test_unknown_obligations_remain_unknown_without_inventing_an_empty_guarantee():
    request, value = annotation_case()
    value["contracts"] = []
    value["detail"] = "The session lifetime contract is unknown from supplied evidence."
    value["confidence"] = 0.1
    result = validated_annotation(value, request=request)
    assert result.value["contracts"] == []
    assert "unknown" in result.value["detail"]
    assert result.confidence == 0.1


def test_blank_obligations_and_unknown_function_bindings_are_refused():
    request, value = annotation_case(" ")
    with pytest.raises(SemanticAnalysisError, match="cannot be blank"):
        validated_annotation(value, request=request)
    value["contracts"][0]["invariants"] = ["Preserve ordering"]
    value["contracts"][0]["functions"] = ["pkg.other.unprovided"]
    with pytest.raises(SemanticAnalysisError, match="supplied functions"):
        validated_annotation(value, request=request)


def test_inferred_contracts_have_confidence_and_no_aggregate_quality_grade():
    request, value = annotation_case("Preserve the caller's quantity")
    result = validated_annotation(value, request=request)
    assert 0 <= result.confidence <= 1
    assert "score" not in result.value
    assert not any(key.endswith("_score") for key in result.value)
