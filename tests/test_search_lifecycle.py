"""Search keeps one bounded projection, with immutable deletion evidence and honest freshness."""

import json
import zlib

import pytest
from semantic_support import _agent_dossier, _enable_agent_semantics

import anaxigraph.persistence.search_read as search_read
import anaxigraph.persistence.search_storage as search_storage
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine

_PATH = "pkg/core.py"
_OLD = "auroraprototype"
_NEW = "nebulareplacement"


def _annotate_target(repository, database, repository_id, marker):
    engine = SemanticEngine(database)
    config = load_config(repository)
    for _ in range(40):
        packet = engine.claim_agent_work(repository_id, repository, config, agent_id="fixture")
        assert packet["status"] == "work"
        request = packet["analysis_request"]
        value = _agent_dossier(request)
        target = request.get("path") == _PATH and request["analysis_kind"] == "annotation"
        if target:
            value["overview"] = f"Provides the {marker} behavior."
        assert (
            engine.submit_agent_work(
                repository_id,
                repository,
                config,
                job_id=packet["job"]["id"],
                lease_token=packet["lease"]["token"],
                dossier=value,
            )["status"]
            == "completed"
        )
        if target:
            return
    raise AssertionError("Fixture did not receive its module annotation")


def _baseline(repository, database):
    _enable_agent_semantics(repository)
    scan = RepositoryScanner(database).scan(repository)
    _annotate_target(repository, database, scan.repository_id, _OLD)
    assert _PATH in _paths(database, scan.repository_id, _OLD)
    return scan


def _paths(database, repository_id, term, snapshot=None):
    if snapshot is None:
        return {item["path"] for item in database.search(repository_id, term)}
    with database.transaction() as connection:
        return {
            item["path"]
            for item in search_read.search_module_hits(
                connection, repository_id, snapshot, term, limit=100
            )
        }


def _row(database, path=_PATH):
    with database.connect() as connection:
        return dict(
            connection.execute(
                "SELECT rowid,* FROM module_search_rows WHERE path=?", (path,)
            ).fetchone()
        )


def _unrelated_edit(repository):
    path = repository / "web/helper.ts"
    path.write_text(path.read_text().replace("Sample", "Different"))


def test_unchanged_scans_do_not_rewrite_fts_tokens_or_identity_rows(
    repository, database, monkeypatch
):
    baseline = _baseline(repository, database)
    before = _row(database)
    writes = []
    original = search_read.insert_search_rows

    def recorded(connection, rows):
        writes.extend(rows)
        return original(connection, rows)

    monkeypatch.setattr(search_read, "insert_search_rows", recorded)
    for _ in range(2):
        scan = RepositoryScanner(database).scan(repository)
        assert scan.snapshot_id == baseline.snapshot_id
        assert _PATH in _paths(database, scan.repository_id, _OLD)
    assert writes == []
    assert _row(database) == before


def test_unrelated_snapshot_carries_proven_unchanged_semantic_terms_without_a_planner(
    repository, database
):
    baseline = _baseline(repository, database)
    before = _row(database)
    original_document = json.loads(before["provenance"])["semantic_document_id"]
    with database.connect() as connection:
        paid_rows = connection.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0]
    _unrelated_edit(repository)
    changed = RepositoryScanner(database).scan(repository)
    assert changed.snapshot_id != baseline.snapshot_id
    with database.connect() as connection:
        state = connection.execute(
            "SELECT status,context_document_id FROM semantic_scope_states "
            "WHERE snapshot_id=? AND scope_key=?",
            (changed.snapshot_id, _PATH),
        ).fetchone()
        assert tuple(state) == ("current", original_document)
        assert (
            connection.execute("SELECT COUNT(*) FROM semantic_documents").fetchone()[0] == paid_rows
        )
    assert _PATH in _paths(database, changed.repository_id, _OLD)
    assert _PATH in _paths(database, changed.repository_id, "Calculator")
    after = _row(database)
    assert after["snapshot_id"] == changed.snapshot_id
    for key in ("rowid", "provenance", "delete_payload"):
        assert after[key] == before[key]
    assert json.loads(after["provenance"])["semantic_document_id"] is not None


def test_new_incoming_context_invalidates_semantic_terms_despite_identical_module_source(
    repository, database
):
    baseline = _baseline(repository, database)
    before = (repository / _PATH).read_bytes()
    (repository / "pkg/new_consumer.py").write_text(
        "from pkg.core import Calculator\n\ndef invoke():\n    return Calculator().calculate(1)\n"
    )
    changed = RepositoryScanner(database).scan(repository)
    assert changed.snapshot_id != baseline.snapshot_id
    assert (repository / _PATH).read_bytes() == before
    assert _PATH not in _paths(database, changed.repository_id, _OLD)
    assert _PATH in _paths(database, changed.repository_id, "Calculator")


@pytest.mark.parametrize("status", ["pending_annotation", "stale", "failed_annotation", "excluded"])
def test_explicit_noncurrent_state_never_keeps_ai_search_terms(repository, database, status):
    baseline = _baseline(repository, database)
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT artifact_id FROM semantic_scope_states WHERE snapshot_id=? AND scope_key=?",
            (baseline.snapshot_id, _PATH),
        ).fetchone()
        connection.execute(
            "UPDATE semantic_scope_states SET status=? WHERE snapshot_id=? AND scope_key=?",
            (status, baseline.snapshot_id, _PATH),
        )
        search_read.refresh_search_projection(
            connection, baseline.repository_id, baseline.snapshot_id, artifact_ids=(row[0],)
        )
    assert _PATH not in _paths(database, baseline.repository_id, _OLD)
    assert _PATH in _paths(database, baseline.repository_id, "Calculator")


def test_historical_queries_rebuild_one_projection_and_restore_current_terms(repository, database):
    baseline = _baseline(repository, database)
    path = repository / _PATH
    path.write_text(path.read_text().replace("return double(value)", "return double(value) + 1"))
    changed = RepositoryScanner(database).scan(repository)
    assert _PATH not in _paths(database, changed.repository_id, _OLD)
    _annotate_target(repository, database, changed.repository_id, _NEW)
    assert _PATH in _paths(database, changed.repository_id, _NEW)
    assert _PATH in _paths(database, baseline.repository_id, _OLD, baseline.snapshot_id)
    assert _PATH not in _paths(database, baseline.repository_id, _NEW, baseline.snapshot_id)
    assert _PATH in _paths(database, changed.repository_id, _NEW)
    assert _PATH not in _paths(database, changed.repository_id, _OLD)
    with database.connect() as connection:
        rows = connection.execute("SELECT snapshot_id FROM module_search_rows").fetchall()
        assert len(rows) == 8
        assert {row[0] for row in rows} == {changed.snapshot_id}


def test_mixed_add_delete_and_last_row_edit_reserves_existing_identities(repository, database):
    _baseline(repository, database)
    with database.connect() as connection:
        before = {
            row["path"]: row["rowid"]
            for row in connection.execute("SELECT rowid,path FROM module_search_rows")
        }
    edited = "web/helper.ts"
    assert before[edited] == max(before.values())
    path = repository / edited
    path.write_text(path.read_text() + "\nexport function cosmicMutationHandle() { return 1; }\n")
    (repository / "aaa_new.py").write_text('"""Owns the pulsaraddition behavior."""\n')
    (repository / "docs/architecture.md").unlink()
    current = RepositoryScanner(database).scan(repository)
    assert _paths(database, current.repository_id, "pulsaraddition") == {"aaa_new.py"}
    assert edited in _paths(database, current.repository_id, "cosmic mutation handle")
    assert _PATH in _paths(database, current.repository_id, _OLD)
    with database.transaction() as connection:
        after = {
            row["path"]: row["rowid"]
            for row in connection.execute("SELECT rowid,path FROM module_search_rows")
        }
        assert len(after) == 8
        assert "docs/architecture.md" not in after
        assert after[edited] == before[edited]
        assert after["aaa_new.py"] not in before.values()
        assert all(after[path] == value for path, value in before.items() if path in after)
        connection.execute("INSERT INTO module_search(module_search) VALUES ('integrity-check')")


def test_pre343_delete_payload_survives_rebind_and_removes_old_terms_on_real_edit(
    repository, database, monkeypatch
):
    baseline = _baseline(repository, database)
    monkeypatch.setattr(search_storage.sqlite3, "sqlite_version_info", (3, 42, 0))
    with database.transaction() as connection:
        search_storage.clear_search_cache(connection)
        search_read.refresh_search_projection(
            connection, baseline.repository_id, baseline.snapshot_id, force=True
        )
    before = _row(database)
    payload = json.loads(zlib.decompress(before["delete_payload"]))
    assert payload[1] == baseline.snapshot_id
    _unrelated_edit(repository)
    carried = RepositoryScanner(database).scan(repository)
    assert _PATH in _paths(database, carried.repository_id, _OLD)
    after = _row(database)
    assert after["snapshot_id"] == carried.snapshot_id
    assert after["rowid"] == before["rowid"]
    assert after["delete_payload"] == before["delete_payload"]
    path = repository / _PATH
    path.write_text(path.read_text() + "\n\ndef solarAliasDispatch():\n    return 1\n")
    current = RepositoryScanner(database).scan(repository)
    assert _PATH not in _paths(database, current.repository_id, _OLD)
    assert _PATH in _paths(database, current.repository_id, "solar alias dispatch")
    assert _PATH in _paths(database, current.repository_id, "Calculator")
    with database.transaction() as connection:
        connection.execute("INSERT INTO module_search(module_search) VALUES ('integrity-check')")
        assert connection.execute("SELECT COUNT(*) FROM module_search_rows").fetchone()[0] == 8
