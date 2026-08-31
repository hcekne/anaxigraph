from __future__ import annotations

from copy import deepcopy

import pytest

from anaxigraph.architecture_charter import architecture_charter
from anaxigraph.architecture_charter_contract import validated_architecture_charter
from anaxigraph.architecture_charter_corrections import save_charter_correction
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticAnalysisError
from anaxigraph.semantic_status import _architecture_charter_document, _repository_charter_ready
from anaxigraph.understanding import SemanticEngine
from tests.semantic_support import _agent_charter


def _overview() -> dict:
    return {
        "snapshot": {"id": 42},
        "files": 7,
        "group_hierarchies": {
            "current": [
                {
                    "key": "application",
                    "name": "application",
                    "label": "Application",
                    "description": "Owns observable application behavior.",
                    "files": 5,
                    "children": [{"key": "application-interface", "name": "application-interface"}],
                },
                {
                    "key": "testing",
                    "name": "testing",
                    "label": "Testing",
                    "files": 2,
                    "children": [],
                },
            ]
        },
    }


def _request() -> dict:
    return {"analysis_kind": "synthesis", "scope_type": "repository"}


def test_static_scan_exposes_an_honest_stable_provisional_charter():
    repository = {"id": 3, "name": "Sample"}

    first = architecture_charter(repository, _overview(), {})
    second = architecture_charter(repository, _overview(), {})

    assert first == second
    assert first["identity"] == "architecture-charter-v1:3:42:provisional"
    assert first["state"] == "provisional"
    assert first["complete"] is False
    assert first["responsibilities"][0]["statement"] == ("Owns observable application behavior.")
    assert first["responsibilities"][0]["related"] == ["application-interface"]
    assert first["unknowns"]
    assert first["capability_brief"]["contract_version"] == "capability-brief-v1"
    assert "src/" not in str(first["capability_brief"])


def test_repository_without_policy_or_human_input_gets_a_provisional_charter(tmp_path, database):
    repository = tmp_path / "unconfigured"
    repository.mkdir()
    (repository / "app.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")

    stats = RepositoryScanner(database).scan(repository)
    row = database.repository(stats.repository_id)
    assert row is not None
    result = architecture_charter(row, database.overview(stats.repository_id), {})

    assert not (repository / ".anaxigraph.yml").exists()
    assert result["state"] == "provisional"
    assert result["responsibilities"]
    assert result["readiness"]["state"] == "provisional"


def test_agent_charter_requires_evidence_and_preserves_documentation_conflicts():
    value = _agent_charter()
    value["conflicts"] = [
        {
            "claim": "The README says every language has parser-backed analysis.",
            "documentation_evidence": ["README claim supplied to repository synthesis"],
            "code_evidence": ["language inventory reports fallback analysis"],
            "status": "open",
        }
    ]

    result = validated_architecture_charter(value, _request())

    assert result.value["conflicts"] == value["conflicts"]
    without_evidence = deepcopy(value)
    without_evidence["purpose"]["evidence"] = []
    with pytest.raises(SemanticAnalysisError, match="at least 1 item"):
        validated_architecture_charter(without_evidence, _request())


def test_capability_brief_rejects_internal_paths_except_declared_compatibility_obligations():
    leaked = _agent_charter()
    leaked["capability_brief"]["observable_capabilities"] = [
        "Reads src/anaxigraph/scanner.py to explain repositories."
    ]
    with pytest.raises(SemanticAnalysisError, match="internal file or package identity"):
        validated_architecture_charter(leaked, _request())

    public_constraint = _agent_charter()
    public_constraint["capability_brief"]["compatibility_obligations"] = [
        "Existing callers rely on the public path schemas/report.py."
    ]
    validated_architecture_charter(public_constraint, _request())


@pytest.mark.parametrize(
    ("status", "expected_state", "complete"),
    [("current", "current", True), ("stale", "stale", False)],
)
def test_saved_charter_keeps_identity_provenance_and_freshness(status, expected_state, complete):
    document = {
        "status": status,
        "document_id": 91,
        "value": _agent_charter(),
        "confidence": 0.85,
        "provider": "agent",
        "model": None,
        "executor_id": "codex",
        "executor_model": "gpt-test",
        "prompt_version": "test-v1",
        "created_at": "2026-08-31T12:00:00+00:00",
    }

    result = architecture_charter(
        {"id": 3, "name": "Sample"},
        _overview(),
        {"architecture_charter": document},
    )

    assert result["identity"] == "architecture-charter-v1:3:42:91"
    assert result["state"] == expected_state
    assert result["complete"] is complete
    assert result["provenance"]["executor_id"] == "codex"
    if status == "stale":
        assert "changed" in result["caveats"][0]


def test_legacy_repository_summary_cannot_masquerade_as_a_current_charter():
    state = {
        "status": "current",
        "document_id": 12,
        "value_json": '{"summary":"An old generic repository dossier"}',
    }

    assert _repository_charter_ready(state) is False
    assert _architecture_charter_document(state) is None


def test_declared_correction_overlays_inference_survives_scan_and_can_be_withdrawn(
    tmp_path, database
):
    repository = tmp_path / "corrected"
    repository.mkdir()
    source = repository / "app.py"
    source.write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
    first = RepositoryScanner(database).scan(repository)
    correction = save_charter_correction(
        database,
        first.repository_id,
        section="purpose",
        statement="Provide a deliberately tiny greeting service.",
        author="repository owner",
        rationale="Static analysis cannot infer the intended user outcome.",
    )

    source.write_text("def greet(name):\n    return f'hello {name}'\n", encoding="utf-8")
    second = RepositoryScanner(database).scan(repository)
    row = database.repository(second.repository_id)
    assert row is not None
    semantic = SemanticEngine(database).status(
        second.repository_id, load_config(repository).semantic
    )
    result = architecture_charter(row, database.overview(second.repository_id), semantic)

    assert result["identity"].endswith(f":c{correction['document_id']}")
    assert "AI review" in result["purpose"]["statement"]
    assert result["purpose"]["presented_statement"] == (
        "Provide a deliberately tiny greeting service."
    )
    assert result["declared_context"][0]["inferred_statement"] == result["purpose"]["statement"]
    assert result["declared_context"][0]["author"] == "repository owner"

    withdrawn = save_charter_correction(
        database,
        second.repository_id,
        section="purpose",
        author="repository owner",
        rationale="The repository now explains this outcome directly.",
        active=False,
    )
    semantic = SemanticEngine(database).status(
        second.repository_id, load_config(repository).semantic
    )
    result = architecture_charter(row, database.overview(second.repository_id), semantic)
    assert result["declared_context"] == []
    assert "presented_statement" not in result["purpose"]
    assert result["identity"].endswith(f":c{withdrawn['document_id']}")
