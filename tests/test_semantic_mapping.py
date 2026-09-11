from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from semantic_support import _agent_dossier, _fake_provider, _semantic_config

from anaxigraph import semantic_freshness, semantic_runner
from anaxigraph.agent import architecture_guidance
from anaxigraph.config import SemanticConfig, load_config, semantic_config_from_mapping
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import ClaudeSemanticProvider, _prompt
from anaxigraph.semantic_contract import DOSSIER_SCHEMA, SemanticAnalysisError
from anaxigraph.semantic_request_analysis import analyze_semantic_request
from anaxigraph.semantic_request_support import (
    MAPPING_REQUIREMENTS,
    MAPPING_SCHEMA,
    compact_dossier,
)
from anaxigraph.semantic_taxonomy_contract import (
    response_contract_name,
    response_schema,
    validated_agent_semantic_response,
    validated_semantic_response,
)
from anaxigraph.understandability import AGENT_REVIEW_POLICY
from anaxigraph.understanding import SemanticEngine


def mapping_request(**changes):
    return {
        "path": "pkg/core.py",
        "source": "def total(quantity, price): return quantity * price\n",
        "analysis_kind": "intrinsic",
        "schema_version": "repository-understanding-v7",
        "detailed_reviews": False,
        "max_output_tokens": 4_000,
        "writing_requirements": MAPPING_REQUIREMENTS,
        **changes,
    }


class MappingProvider:
    name = "deterministic-mapping-test"

    def __init__(self):
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return validated_agent_semantic_response(_agent_dossier(request), request)


def test_default_contract_is_small_and_detailed_reviews_are_explicit():
    request = mapping_request()
    assert semantic_config_from_mapping({"enabled": True}).detailed_reviews is False
    assert response_schema(request) == MAPPING_SCHEMA
    assert len(MAPPING_SCHEMA["required"]) == 5
    assert len(json.dumps(MAPPING_SCHEMA)) < len(json.dumps(DOSSIER_SCHEMA)) / 4
    assert response_schema({**request, "detailed_reviews": True}) == DOSSIER_SCHEMA
    assert SemanticConfig().max_output_tokens == 4_000
    assert SemanticConfig().max_output_tokens_on_retry == 8_000
    assert response_contract_name({**request, "detailed_reviews": True}) == "review_dossier"
    assert set(compact_dossier(_agent_dossier({**request, "detailed_reviews": True}))) == set(
        MAPPING_SCHEMA["required"]
    )


@pytest.mark.parametrize("value", ["false", "true", 1, [], None])
def test_review_policy_cannot_accidentally_enable_spending(value):
    with pytest.raises(ValueError, match="detailed_reviews"):
        semantic_config_from_mapping({"detailed_reviews": value})


@pytest.mark.parametrize(
    "changes",
    [
        {"summary": " "},
        {"responsibilities": "Must be a list"},
        {"public_contracts": [42]},
        {"evidence": None},
        {"detailed_summary": "A second essay"},
        {"confidence": float("nan")},
    ],
)
def test_routine_output_shape_is_validated_before_storage(changes):
    request = mapping_request()
    value = {**_agent_dossier(request), **changes}
    with pytest.raises(SemanticAnalysisError):
        validated_semantic_response(value, request)


def test_prompt_reuses_stable_prefix_and_places_complete_source_last():
    first = mapping_request(source="FIRST SOURCE")
    second = mapping_request(path="pkg/other.py", source="SECOND SOURCE")
    left, right = _prompt(first), _prompt(second)
    assert left[: left.index('"path"')] == right[: right.index('"path"')]
    assert left.index('"writing_requirements"') < left.index('"path"')
    payload = json.loads(left.split("ANAXIGRAPH_PAYLOAD\n", 1)[1])
    assert payload == first
    assert list(payload)[-1] == "source"
    assert left.count(MAPPING_REQUIREMENTS["writing"]) == 1


@pytest.mark.parametrize(("configured", "expected"), [(4_000, 4_000), (800, 800)])
def test_claude_receives_the_lower_per_request_output_limit(monkeypatch, configured, expected):
    request = mapping_request()
    monkeypatch.setenv("ANAXIGRAPH_TEST_MARKER", "preserved")

    def run(command, **kwargs):
        assert kwargs["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == str(expected)
        assert kwargs["env"]["ANAXIGRAPH_TEST_MARKER"] == "preserved"
        assert json.loads(command[command.index("--json-schema") + 1]) == MAPPING_SCHEMA
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"structured_output": _agent_dossier(request)}),
        )

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
    result = ClaudeSemanticProvider(SemanticConfig(max_output_tokens=configured)).analyze(request)
    assert set(result.value) == set(MAPPING_SCHEMA["required"])


def test_large_file_chunks_and_reduction_keep_the_lean_contract():
    provider = MappingProvider()
    request = mapping_request(source="VALUE = 1\n" * 1_000, contract="Describe this file")
    result = analyze_semantic_request(provider, request, SemanticConfig(max_source_chars=4_000))
    assert len(provider.requests) > 1
    assert provider.requests[-1]["analysis_kind"] == "intrinsic_synthesis"
    assert all(request["detailed_reviews"] is False for request in provider.requests)
    assert all(request["max_output_tokens"] == 4_000 for request in provider.requests)
    assert set(result.value) == set(MAPPING_SCHEMA["required"])


@pytest.mark.parametrize("detailed", [False, True])
def test_group_reduction_preserves_the_requested_level_of_detail(detailed):
    provider = MappingProvider()
    request = mapping_request(
        analysis_kind="synthesis",
        scope_type="group",
        detailed_reviews=detailed,
        child_dossiers=[
            {"scope": f"module-{index}", "value": {"summary": "x" * 1_500}} for index in range(30)
        ],
    )
    analyze_semantic_request(
        provider, request, SemanticConfig(max_source_chars=4_000, max_context_modules=2)
    )
    assert any(item["analysis_kind"] == "synthesis_reduction" for item in provider.requests)
    for child in provider.requests[-1]["child_dossiers"]:
        assert ("architecture_role" in child["value"]) is detailed
        if not detailed:
            assert set(child["value"]) == set(MAPPING_SCHEMA["required"])


def test_lean_map_finishes_and_still_supports_guidance(repository, database, tmp_path, monkeypatch):
    _semantic_config(
        repository, _fake_provider(tmp_path), tmp_path / "calls", detailed_reviews=False
    )
    config = load_config(repository)
    provider = MappingProvider()
    monkeypatch.setattr(semantic_runner, "create_semantic_provider", lambda _: provider)
    scan = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    result = engine.bootstrap(scan.repository_id, repository, config)
    assert result["semantic"]["semantically_ready"]
    assert result["semantic"]["enabled"]
    assert result["semantic"]["patterns"]["enabled"] is False
    assert result["semantic"]["patterns"]["selected"] == 0
    assert not any(request["analysis_kind"].startswith("pattern_") for request in provider.requests)
    for request in provider.requests:
        if response_contract_name(request) == "dossier":
            assert request["max_output_tokens"] == 4_000
            assert "understandability_policy" not in request
            assert "input_term_meanings" not in request
            assert AGENT_REVIEW_POLICY not in json.dumps(request)
        elif request["analysis_kind"] == "taxonomy_proposal":
            assert all(
                "architecture_role" not in module["dossier"] for module in request["modules"]
            )
    saved = engine.dossier(scan.repository_id, "pkg/core.py")
    assert set(saved["context"]["value"]) == set(MAPPING_SCHEMA["required"])
    guide = architecture_guidance(
        database, repository_id=scan.repository_id, goal="Change Calculator", config=config
    )
    assert guide["primary_files"][0]["summary"]
    reader = guide["architecture_decision"].get("understandability") or {"status": "unknown"}
    assert reader["status"] == "unknown"
    monkeypatch.setattr(semantic_freshness, "AGENT_REVIEW_POLICY", "Changed review instructions")
    assert engine.bootstrap(scan.repository_id, repository, config)["processed"] == 0


def test_review_mode_refreshes_evidence_and_can_return_to_lean_mapping(
    repository, database, tmp_path, monkeypatch
):
    _semantic_config(
        repository, _fake_provider(tmp_path), tmp_path / "calls", detailed_reviews=False
    )
    lean = load_config(repository)
    provider = MappingProvider()
    monkeypatch.setattr(semantic_runner, "create_semantic_provider", lambda _: provider)
    scan = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.bootstrap(scan.repository_id, repository, lean)["semantic"]["semantically_ready"]
    review = replace(lean, semantic=replace(lean.semantic, detailed_reviews=True))
    provider.requests.clear()
    detailed = engine.bootstrap(scan.repository_id, repository, review)
    assert detailed["semantic"]["semantically_ready"]
    assert any(item["analysis_kind"] == "pattern_review" for item in provider.requests)
    for request in provider.requests:
        if request["analysis_kind"] in {
            "intrinsic",
            "context",
            "pattern_assessment",
            "pattern_review",
        }:
            assert json.dumps(request).count(AGENT_REVIEW_POLICY) == 1
    assert (
        "understandability" in engine.dossier(scan.repository_id, "pkg/core.py")["context"]["value"]
    )
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT id FROM semantic_jobs WHERE repository_id = ? AND job_kind = 'pattern_review' LIMIT 1",
            (scan.repository_id,),
        ).fetchone()
        connection.execute("UPDATE semantic_jobs SET status = 'retry' WHERE id = ?", (row["id"],))
    provider.requests.clear()
    restored = engine.bootstrap(scan.repository_id, repository, lean)
    assert restored["semantic"]["semantically_ready"]
    assert not any(item["analysis_kind"].startswith("pattern_") for item in provider.requests)
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT status FROM semantic_jobs WHERE id = ?", (row["id"],)
            ).fetchone()[0]
            == "superseded"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_documents WHERE document_kind = 'pattern_review'"
            ).fetchone()[0]
            > 0
        )
