"""Codex's wire schema must not redefine the backward-compatible storage contract."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from semantic_support import _agent_charter

from anaxigraph.architecture_charter_contract import ARCHITECTURE_CHARTER_SCHEMA
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import CodexSemanticProvider, _codex_schema, _without_optional_nulls
from anaxigraph.semantic_contract import SemanticAnalysisError, _validate_schema
from anaxigraph.semantic_taxonomy_contract import response_schema


def _assert_strict(schema):
    if isinstance(schema, list):
        for child in schema:
            _assert_strict(child)
    elif isinstance(schema, dict):
        if schema.get("type") == "object":
            assert set(schema["required"]) == set(schema["properties"])
            assert schema["additionalProperties"] is False
        for child in schema.values():
            _assert_strict(child)


@pytest.mark.parametrize(
    "payload",
    [
        {"analysis_kind": "intrinsic", "detailed_reviews": False},
        {"analysis_kind": "context", "detailed_reviews": True},
        {"analysis_kind": "taxonomy_proposal"},
        {"analysis_kind": "taxonomy_review"},
        {"analysis_kind": "synthesis", "scope_type": "repository"},
        {"analysis_kind": "synthesis_chunk", "scope_type": "repository"},
        {"analysis_kind": "pattern_assessment"},
        {"analysis_kind": "pattern_review"},
        *(
            {"analysis_kind": kind}
            for kind in ["fresh_proposal", "fresh_adjudication", "fresh_comparison", "fresh_review"]
        ),
    ],
)
def test_every_codex_contract_has_required_fields_recursively_without_mutation(payload):
    original = response_schema(payload)
    before = deepcopy(original)
    wire = _codex_schema(original)
    _assert_strict(wire)
    assert original == before
    assert wire is not original


def test_optional_charter_fields_allow_null_only_on_the_wire():
    wire = _codex_schema(ARCHITECTURE_CHARTER_SCHEMA)
    claim = wire["properties"]["actors"]["items"]
    assert claim["properties"]["owner_scope"]["anyOf"][1] == {"type": "null"}
    assert wire["properties"]["definitions"]["anyOf"][1] == {"type": "null"}
    assert (
        "owner_scope"
        not in ARCHITECTURE_CHARTER_SCHEMA["properties"]["actors"]["items"]["required"]
    )
    assert "definitions" not in ARCHITECTURE_CHARTER_SCHEMA["required"]


@pytest.mark.parametrize("optional_value", [None, "Runtime"])
def test_codex_charter_roundtrip_preserves_values_and_usage(monkeypatch, optional_value):
    value = _agent_charter()
    value["definitions"] = None if optional_value is None else []
    for claim in value["actors"]:
        claim["owner_scope"] = optional_value
    original = deepcopy(value)

    def run(command, **kwargs):
        _assert_strict(json.loads(Path(command[command.index("--output-schema") + 1]).read_text()))
        Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(value))
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 20},
                }
            ),
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    result = CodexSemanticProvider(SemanticConfig(provider="codex")).analyze(
        {"analysis_kind": "synthesis", "scope_type": "repository"}
    )
    assert result.value == _without_optional_nulls(value, ARCHITECTURE_CHARTER_SCHEMA)
    assert ("definitions" in result.value) == (optional_value is not None)
    assert value == original
    assert result.input_tokens == 100 and result.output_tokens == 20
    assert result.cache_read_input_tokens == 80 and result.usage_reported


def test_null_normalization_never_hides_required_null_or_unknown_fields():
    value = _agent_charter()
    value["purpose"]["statement"] = None
    value["unexpected"] = None
    normalized = _without_optional_nulls(value, ARCHITECTURE_CHARTER_SCHEMA)
    assert normalized["purpose"]["statement"] is None
    assert "unexpected" in normalized
    with pytest.raises(SemanticAnalysisError, match="unsupported fields"):
        _validate_schema(normalized, ARCHITECTURE_CHARTER_SCHEMA, "charter")
    del normalized["unexpected"]
    with pytest.raises(SemanticAnalysisError, match="must be a string"):
        _validate_schema(normalized, ARCHITECTURE_CHARTER_SCHEMA, "charter")


def test_nested_optional_object_can_be_absent_without_invented_defaults():
    schema = response_schema({"analysis_kind": "fresh_review"})
    field = schema["properties"]["recommendations"]["items"]
    value = {"transformation": {"target": "app.py", "result": None}}
    assert _without_optional_nulls(value, field) == {"transformation": {"target": "app.py"}}
    assert _without_optional_nulls({"transformation": None}, field) == {}
