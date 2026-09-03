"""Submission size limit for coding-agent semantic dossiers."""

from __future__ import annotations

import pytest

from anaxigraph import semantic_agent_contracts
from anaxigraph.api_limits import MAX_REQUEST_BODY_BYTES
from anaxigraph.semantic_agent_contracts import (
    MAX_SUBMISSION_BYTES,
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


def test_submission_limit_counts_utf8_bytes_not_characters(schema_validation):
    # 400,000 three-byte characters: ~400k characters but ~1.2 MB encoded.
    dossier = {"summary": "中" * 400_000}

    with pytest.raises(ValueError, match=str(MAX_SUBMISSION_BYTES)):
        _validate(dossier)

    assert schema_validation == []


def test_submission_limit_accepts_ascii_under_limit_and_rejects_over_limit(
    schema_validation,
):
    under = {"summary": "x" * 999_000}
    over = {"summary": "x" * 1_000_001}

    assert _validate(under).value == _ACCEPTED.value
    assert schema_validation == [under]

    with pytest.raises(ValueError, match=r"\d+-byte submission limit"):
        _validate(over)

    assert schema_validation == [under]


def test_submission_limit_is_below_http_body_limit():
    assert MAX_SUBMISSION_BYTES <= MAX_REQUEST_BODY_BYTES


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
