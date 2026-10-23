"""Compact behavioral contracts replace verbose maintenance-task writers."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from annotation_contract_support import annotation_case

from anaxigraph.knowledge_annotation_contract import validated_annotation
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_records import document_record
from anaxigraph.semantic_model_contract import SemanticAnalysisError
from anaxigraph.semantic_taxonomy_contract import validated_agent_semantic_response
from anaxigraph.understandability import UNDERSTANDABILITY_VERSION


def reader_task(**changes):
    return {
        "key": "change-calculation",
        "task": "Change the calculation while preserving its caller contract.",
        "status": "obstructed",
        "knowledge_sources": ["names", "interfaces", "tests"],
        "evidence": ["pkg/core.py::Calculator.calculate", "tests/test_core.py"],
        "obstacle": "The argument name does not identify which quantity the caller supplies.",
        "smallest_change": "Give the internal calculation argument a domain name; preserve public callers.",
        "expected_benefit": "A reader can identify the quantity without reconstructing every caller.",
        "migration_cost": "low",
        "counter_evidence": ["Keep keyword argument compatibility for existing callers."],
        "verification": "Run the calculation tests, including keyword callers and invalid inputs.",
        "confidence": 0.85,
        **changes,
    }


def assessment(*tasks):
    return {"contract_version": UNDERSTANDABILITY_VERSION, "tasks": list(tasks)}


def test_annotation_keeps_behavior_contracts_and_unknowns_concise():
    request, value = annotation_case("Call configure before calculation")
    result = validated_agent_semantic_response(value, request)
    assert result.value == value
    assert result.value["contracts"][0]["functions"] == ["pkg.core.calculate"]
    assert result.value["functions"][0]["overview"]
    assert "unknown" in result.value["detail"]
    assert "understandability" not in result.value


@pytest.mark.parametrize(
    ("target", "field", "replacement"),
    [
        ("annotation", "overview", " "),
        ("annotation", "confidence", float("nan")),
        ("function", "overview", " "),
        ("function", "qualified_name", "pkg.core.unprovided"),
        ("contract", "name", " "),
        ("contract", "statement", " "),
        ("contract", "functions", ["pkg.core.unprovided"]),
        ("contract", "invariants", [" "]),
        ("contract", "evidence", [" "]),
    ],
)
def test_invalid_behavioral_contracts_are_rejected(target, field, replacement):
    request, value = annotation_case("Keep the session alive during calculation")
    selected = (
        value
        if target == "annotation"
        else value["functions" if target == "function" else "contracts"][0]
    )
    selected[field] = replacement
    with pytest.raises(SemanticAnalysisError):
        validated_annotation(value, request=request)


def test_annotation_covers_each_supplied_function_once():
    request, value = annotation_case()
    for functions in ([], [deepcopy(value["functions"][0])] * 2):
        candidate = {**value, "functions": functions}
        with pytest.raises(SemanticAnalysisError, match="each supplied function exactly once"):
            validated_annotation(candidate, request=request)


@pytest.mark.parametrize("kind", ["contracts", "capabilities"])
def test_annotation_named_entities_cannot_overwrite_each_other(kind):
    request, value = annotation_case()
    if kind == "capabilities":
        value[kind] = [
            {
                "name": "calculation",
                "purpose": "Calculate a quantity",
                "inputs": [],
                "outputs": [],
                "constraints": [],
            }
        ]
    value[kind].append(deepcopy(value[kind][0]))
    with pytest.raises(SemanticAnalysisError, match="unique names"):
        validated_annotation(value, request=request)


@pytest.mark.parametrize("field", ["name", "purpose"])
def test_annotation_capabilities_need_meaningful_identity_and_behavior(field):
    request, value = annotation_case()
    value["capabilities"] = [
        {
            "name": "calculation",
            "purpose": "Calculate a quantity",
            "inputs": [],
            "outputs": [],
            "constraints": [],
        }
    ]
    value["capabilities"][0][field] = " "
    with pytest.raises(SemanticAnalysisError, match="nonblank"):
        validated_annotation(value, request=request)


def test_model_annotation_cannot_add_a_fabricated_verification_field():
    request, value = annotation_case()
    value["contracts"][0]["verification"] = {"status": "passed", "source": "model opinion"}
    with pytest.raises(SemanticAnalysisError, match="unsupported fields"):
        validated_annotation(value, request=request)


def test_saved_legacy_reader_assessment_is_preserved_without_new_validation(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    original = {
        "summary": "Original paid module understanding",
        "understandability": assessment(reader_task()),
    }
    with database.transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO semantic_documents(repository_id,snapshot_id,scope_type,scope_key,document_kind,"
            "input_hash,intent_fingerprint,value_json,source,provider,model,prompt_version,schema_version,"
            "confidence,created_at) VALUES(?,?,'module','pkg/core.py','intrinsic','oldhash','oldintent',?,"
            "'agent','agent','historical-model','old-v1','module-dossier-v4',0.85,'2026-01-01')",
            (stats.repository_id, stats.snapshot_id, json.dumps(original)),
        )
        identifier = cursor.lastrowid
    with database.connect() as connection:
        saved = document_record(connection, identifier)
    assert saved["value"] == original
    assert saved["model"] == "historical-model"
    assert saved["input_hash"] == "oldhash"
    assert saved["value"]["understandability"]["tasks"][0]["counter_evidence"]
    assert saved["value"]["understandability"]["tasks"][0]["verification"]
