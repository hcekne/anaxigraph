"""Agent results retain schema and usage validation without arbitrary byte cutoffs."""

from __future__ import annotations

import pytest

from anaxigraph import semantic_agent_contracts
from anaxigraph.semantic_agent_contracts import (
    SemanticAgentContractService,
)
from anaxigraph.semantic_contract import SemanticResult

_REQUEST = {"analysis_kind": "intrinsic", "path": "module.py"}
_ACCEPTED = SemanticResult(value={"summary": "accepted"}, confidence=0.5, evidence=())


@pytest.fixture
def schema_validation(monkeypatch):
    calls: list[dict] = []

    def stub(dossier, request, *, input_tokens, output_tokens):
        calls.append(dossier)
        return _ACCEPTED

    monkeypatch.setattr(semantic_agent_contracts, "validated_agent_semantic_response", stub)
    return calls


def _validate(dossier):
    return SemanticAgentContractService().validate_submission(
        dossier, _REQUEST, input_tokens=1, output_tokens=1
    )


@pytest.mark.parametrize("summary", ["中" * 400_000, "x" * 2_200_000])
@pytest.mark.parametrize("kind", ["intrinsic", "taxonomy_proposal", "taxonomy_review"])
def test_repository_sized_results_reach_schema_validation(schema_validation, summary, kind):
    dossier = {"summary": summary}
    result = SemanticAgentContractService().validate_submission(
        dossier, {**_REQUEST, "analysis_kind": kind}, input_tokens=1, output_tokens=1
    )
    assert result.value == _ACCEPTED.value
    assert result.usage_reported is True
    assert schema_validation == [dossier]


def test_large_invalid_result_still_fails_schema_validation():
    with pytest.raises(ValueError):
        _validate({"summary": "x" * 2_200_000})


def test_negative_token_counts_are_refused(schema_validation):
    with pytest.raises(ValueError, match="cannot be negative"):
        SemanticAgentContractService().validate_submission(
            {"summary": "ok"}, _REQUEST, input_tokens=-1, output_tokens=0
        )

    assert schema_validation == []


def test_omitted_token_counts_are_unknown_usage_and_explicit_zeros_are_reported(
    schema_validation,
):
    service = SemanticAgentContractService()

    silent = service.validate_submission(
        {"summary": "ok"}, _REQUEST, input_tokens=None, output_tokens=None
    )
    explicit = service.validate_submission(
        {"summary": "ok"},
        _REQUEST,
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=5,
        cache_creation_input_tokens=2,
    )

    assert silent.usage_reported is False
    assert explicit.usage_reported is True
    assert explicit.cache_read_input_tokens == 5
    assert explicit.cache_creation_input_tokens == 2
