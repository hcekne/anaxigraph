from __future__ import annotations

import json
from copy import deepcopy

import pytest

from anaxigraph.architecture_charter import architecture_charter
from anaxigraph.architecture_charter_contract import validated_architecture_charter
from anaxigraph.architecture_charter_corrections import (
    CORRECTION_VERSION,
    _insert_correction,
    read_charter_corrections,
    save_charter_correction,
)
from anaxigraph.cli import main
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


_CONCERN = "Snapshot projection may leave temporary tables behind."
_WHY = "storage.py:33 drops the temporary table inside the same transaction."


def _charter_with_concern() -> dict:
    value = deepcopy(_agent_charter())
    value["coherence_concerns"] = [
        {
            "key": "temp-tables",
            "name": "Temporary tables",
            "statement": _CONCERN,
            "related": [],
            "entry_points": ["src/anaxigraph/storage.py"],
            "evidence": ["snapshot projection review"],
            "counter_evidence": [],
            "confidence": 0.6,
        }
    ]
    return {
        "status": "current",
        "document_id": 91,
        "value": value,
        "provider": "agent",
        "created_at": "2026-09-01T12:00:00+00:00",
    }


def _refutation(**overrides) -> dict:
    correction = {
        "document_id": 7,
        "section": "coherence_concerns",
        "key": "temp-tables",
        "statement": "",
        "author": "repository owner",
        "rationale": _WHY,
        "active": True,
        "disposition": "refute",
        "created_at": "2026-09-02T09:00:00+00:00",
    }
    correction.update(overrides)
    return correction


def _projected(corrections: list[dict], document: dict | None = None) -> dict:
    semantic = {
        "architecture_charter": document or _charter_with_concern(),
        "charter_corrections": corrections,
    }
    return architecture_charter({"id": 3, "name": "Sample"}, _overview(), semantic)


def _scanned(tmp_path, database) -> tuple[dict, int]:
    root = tmp_path / "refuted"
    root.mkdir()
    (root / "app.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
    stats = RepositoryScanner(database).scan(root)
    row = database.repository(stats.repository_id)
    assert row is not None
    return row, stats.repository_id


def _stored_corrections(database, repository_id: int) -> list[dict]:
    with database.transaction() as connection:
        return read_charter_corrections(connection, repository_id)


def test_refuted_concern_is_marked_and_preserved_and_can_be_withdrawn():
    result = _projected([_refutation()])

    concern = result["coherence_concerns"][0]
    assert concern["disposition"] == "refuted"
    assert concern["statement"] == _CONCERN
    assert "presented_statement" not in concern
    assert concern["declared_overlay"]["rationale"] == _WHY
    overlay = result["declared_context"][0]
    assert overlay["mode"] == "refutation"
    assert overlay["inferred_statement"] == _CONCERN
    assert overlay["author"] == "repository owner"

    withdrawn = _projected([_refutation(active=False)])
    assert withdrawn["declared_context"] == []
    assert "disposition" not in withdrawn["coherence_concerns"][0]
    assert withdrawn["coherence_concerns"][0]["statement"] == _CONCERN


def test_refutation_may_replace_the_wording_or_name_a_claim_the_charter_no_longer_infers():
    replacement = "The temporary table is dropped inside the same transaction."
    result = _projected([_refutation(statement=replacement)])

    concern = result["coherence_concerns"][0]
    assert concern["disposition"] == "refuted"
    assert concern["presented_statement"] == replacement
    assert concern["statement"] == _CONCERN

    unmatched = _projected([_refutation(key="renamed-after-regeneration")])
    assert unmatched["declared_context"][0]["mode"] == "refutation"
    assert unmatched["declared_context"][0]["inferred_statement"] is None
    assert "disposition" not in unmatched["coherence_concerns"][0]


def test_legacy_corrections_without_disposition_still_load(tmp_path, database):
    row, repository_id = _scanned(tmp_path, database)
    snapshot = database.latest_snapshot(repository_id)
    assert snapshot is not None
    legacy = {
        "contract_version": CORRECTION_VERSION,
        "section": "coherence_concerns",
        "key": "temp-tables",
        "statement": "Temporary tables are worth watching during projection.",
        "author": "repository owner",
        "rationale": "Saved before the disposition field existed.",
        "active": True,
    }
    with database.transaction() as connection:
        _insert_correction(
            connection, repository_id, int(snapshot["id"]), legacy, "2026-08-01T00:00:00+00:00"
        )

    corrections = _stored_corrections(database, repository_id)
    assert "disposition" not in corrections[0]

    result = architecture_charter(
        row,
        database.overview(repository_id),
        {"architecture_charter": _charter_with_concern(), "charter_corrections": corrections},
    )
    concern = result["coherence_concerns"][0]
    assert concern["presented_statement"] == legacy["statement"]
    assert "disposition" not in concern
    assert result["declared_context"][0]["mode"] == "correction"


def test_a_refutation_and_a_wording_correction_on_one_key_cannot_coexist(tmp_path, database):
    _row, repository_id = _scanned(tmp_path, database)
    target = {"section": "coherence_concerns", "key": "temp-tables", "author": "owner"}
    save_charter_correction(
        database,
        repository_id,
        statement="Temporary tables need a documented owner.",
        rationale="The inferred wording was vague.",
        **target,
    )

    save_charter_correction(database, repository_id, rationale=_WHY, disposition="refute", **target)
    corrections = _stored_corrections(database, repository_id)
    assert len(corrections) == 1
    assert corrections[0]["disposition"] == "refute"
    assert corrections[0]["statement"] == ""

    save_charter_correction(
        database,
        repository_id,
        statement="Temporary tables need a documented owner.",
        rationale="The refutation was premature.",
        **target,
    )
    corrections = _stored_corrections(database, repository_id)
    assert len(corrections) == 1
    assert corrections[0]["disposition"] == "correct"
    assert _projected(corrections)["coherence_concerns"][0].get("disposition") is None


def test_refute_makes_the_statement_optional_and_rejects_an_unknown_disposition(tmp_path, database):
    _row, repository_id = _scanned(tmp_path, database)
    target = {"section": "coherence_concerns", "key": "temp-tables", "author": "owner"}

    saved = save_charter_correction(
        database, repository_id, rationale=_WHY, disposition="refute", **target
    )
    assert saved["disposition"] == "refute"
    assert saved["statement"] == ""

    with pytest.raises(ValueError, match="disposition must be one of"):
        save_charter_correction(
            database, repository_id, rationale=_WHY, disposition="ignore", **target
        )
    with pytest.raises(ValueError, match="statement is required"):
        save_charter_correction(database, repository_id, rationale=_WHY, **target)


def test_charter_cli_refutes_a_concern_without_a_replacement_statement(
    repository, tmp_path, capsys
):
    arguments = [
        "charter",
        str(repository),
        "--db",
        str(tmp_path / "refute.db"),
        "--json",
        "--correct-section",
        "coherence_concerns",
        "--key",
        "temp-tables",
        "--refute",
        "--author",
        "test owner",
        "--rationale",
        _WHY,
    ]
    main(["scan", str(repository), "--db", str(tmp_path / "refute.db"), "--json"])
    capsys.readouterr()
    main(arguments)

    charter = json.loads(capsys.readouterr().out)
    overlay = charter["declared_context"][0]
    assert overlay["mode"] == "refutation"
    assert overlay["rationale"] == _WHY
    assert overlay["statement"] == ""


def _dirty_overview() -> dict:
    overview = _overview()
    overview["snapshot"] = {
        "id": 42,
        "dirty": 1,
        "commit_sha": "a" * 40,
        "branch": "main",
        "metadata_json": json.dumps({"working_tree_fingerprint": "f" * 64}),
    }
    return overview


@pytest.mark.parametrize("status", ["current", "stale"])
def test_charter_carries_snapshot_provenance_and_dirty_caveat(status):
    repository = {"id": 3, "name": "Sample"}
    document = {"status": status, "document_id": 91, "value": _agent_charter()}

    provisional = architecture_charter(repository, _dirty_overview(), {})
    saved = architecture_charter(repository, _dirty_overview(), {"architecture_charter": document})

    for charter in (provisional, saved):
        assert charter["snapshot"]["commit_sha"] == "a" * 40
        assert charter["snapshot"]["dirty"] is True
        assert charter["snapshot"]["working_tree_fingerprint"] == "f" * 64
        assert any("dirty checkout" in caveat for caveat in charter["caveats"])
    assert "dirty checkout" in provisional["caveats"][0]
    if status == "stale":
        assert "changed" in saved["caveats"][0]
        assert "dirty checkout" in saved["caveats"][1]
    else:
        assert "dirty checkout" in saved["caveats"][0]

    clean = _dirty_overview()
    clean["snapshot"]["dirty"] = 0
    for charter in (
        architecture_charter(repository, clean, {}),
        architecture_charter(repository, clean, {"architecture_charter": document}),
        architecture_charter(repository, _overview(), {}),
    ):
        assert charter["snapshot"]["dirty"] is False
        assert not any("dirty checkout" in caveat for caveat in charter["caveats"])
    assert architecture_charter(repository, _overview(), {})["snapshot"]["snapshot_id"] == 42
