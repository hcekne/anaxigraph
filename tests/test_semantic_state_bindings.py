"""Snapshot bindings share validated state bodies and preserve independent historical edits."""

from dataclasses import replace

import pytest
import yaml
from semantic_support import _agent_dossier, _enable_agent_semantics
from test_legacy_obligations import _legacy

from anaxigraph.config import load_config
from anaxigraph.knowledge_detail import entity_detail
from anaxigraph.persistence.semantic_state_carry import carry_compatible_states
from anaxigraph.persistence.semantic_state_storage import collect_semantic_states
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_records import _upsert_state
from anaxigraph.understanding import SemanticEngine


def _mapped(repository, database):
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    wanted = {"pkg/core.py", "web/helper.ts"}
    for _ in range(40):
        packet = engine.claim_agent_work(
            stats.repository_id, repository, config, agent_id="fixture"
        )
        assert packet["status"] == "work"
        request = packet["analysis_request"]
        engine.submit_agent_work(
            stats.repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(request),
        )
        if request["analysis_kind"] == "annotation":
            wanted.discard(request["path"])
        if not wanted:
            return stats, config
    raise AssertionError("The controlled fixture did not receive its annotations")


def _state(database, snapshot, path="pkg/core.py"):
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM semantic_scope_states WHERE snapshot_id=? AND scope_type='module' AND scope_key=?",
            (snapshot, path),
        ).fetchone()
    return dict(row) if row else None


def _paid_rows(database):
    with database.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute("SELECT * FROM semantic_document_values ORDER BY id")
        ]


def test_one_file_edit_reuses_compact_bindings_before_planning_without_paid_row_changes(
    repository, database
):
    baseline, _config = _mapped(repository, database)
    before = _state(database, baseline.snapshot_id)
    originals = _paid_rows(database)
    with database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM semantic_state_records").fetchone()[0]
    path = repository / "web/helper.ts"
    path.write_text(path.read_text().replace("Sample", "Different"))
    current = RepositoryScanner(database).scan(repository)
    after = _state(database, current.snapshot_id)
    assert after["status"] == "current"
    assert after["intrinsic_document_id"] == before["intrinsic_document_id"]
    assert after["context_document_id"] == before["context_document_id"]
    assert _state(database, current.snapshot_id, "web/helper.ts") is None
    assert _state(database, baseline.snapshot_id) == before
    with database.connect() as connection:
        ids = [
            row[0]
            for row in connection.execute(
                "SELECT state_id FROM semantic_state_bindings WHERE scope_key='pkg/core.py' ORDER BY snapshot_id"
            )
        ]
        assert len(ids) == 2 and ids[0] == ids[1]
        assert (
            connection.execute("SELECT COUNT(*) FROM semantic_state_records").fetchone()[0] == count
        )
    assert (
        entity_detail(database, current.repository_id, "module:pkg/core.py")["node"]["readiness"]
        == "annotated"
    )
    assert _paid_rows(database) == originals


def test_changed_callee_invalidates_its_unchanged_client_but_keeps_unrelated_binding(
    repository, database
):
    baseline, _config = _mapped(repository, database)
    old = _state(database, baseline.snapshot_id)
    path = repository / "pkg/util.py"
    path.write_text(path.read_text().replace("value * 2", "value * 3"))
    current = RepositoryScanner(database).scan(repository)
    assert _state(database, current.snapshot_id) is None
    assert _state(database, current.snapshot_id, "web/helper.ts")["status"] == "current"
    assert _state(database, baseline.snapshot_id) == old


def test_planning_retains_original_paired_legacy_hashes_and_shared_state_body(repository, database):
    _enable_agent_semantics(repository)
    stats, _statements, intrinsic = _legacy(repository, database)
    context = {key: value for key, value in intrinsic.items() if key != "id"}
    context.update(document_kind="context", input_hash="original-context-hash")
    with database.transaction() as connection:
        context_id = connection.execute(
            f"INSERT INTO semantic_documents({','.join(context)}) VALUES({','.join('?' for _ in context)})",
            list(context.values()),
        ).lastrowid
        _upsert_state(
            connection,
            repository_id=stats.repository_id,
            snapshot_id=stats.snapshot_id,
            scope_type="module",
            scope_key="pkg/util.py",
            artifact_id=intrinsic["artifact_id"],
            file_fact_id=intrinsic["file_fact_id"],
            status="current",
            reason="Original reviewed pair",
            intrinsic_document_id=intrinsic["id"],
            context_document_id=context_id,
            intrinsic_input_hash=intrinsic["input_hash"],
            context_input_hash=context["input_hash"],
        )
        binding = connection.execute(
            "SELECT state_id FROM semantic_state_bindings WHERE snapshot_id=? AND scope_key='pkg/util.py'",
            (stats.snapshot_id,),
        ).fetchone()[0]
    original = _state(database, stats.snapshot_id, "pkg/util.py")
    paid = _paid_rows(database)
    config = load_config(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    with database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM semantic_state_records").fetchone()[0]
    for _ in range(3):
        engine.plan(stats.repository_id, repository, config)
    assert _state(database, stats.snapshot_id, "pkg/util.py") == original
    assert _paid_rows(database) == paid
    with database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM semantic_state_records").fetchone()[0] == count
        )
        assert (
            connection.execute(
                "SELECT state_id FROM semantic_state_bindings WHERE snapshot_id=? AND scope_key='pkg/util.py'",
                (stats.snapshot_id,),
            ).fetchone()[0]
            == binding
        )
        assert connection.execute(
            "SELECT 1 FROM semantic_scope_states s JOIN semantic_documents d "
            "ON d.id=s.intrinsic_document_id AND d.input_hash=s.intrinsic_input_hash "
            "WHERE s.snapshot_id=? AND s.scope_key='pkg/util.py'",
            (stats.snapshot_id,),
        ).fetchone()


@pytest.mark.parametrize("status", ["pending_annotation", "stale", "failed_annotation", "excluded"])
def test_binding_copy_on_write_and_explicit_override_preserve_historical_state(
    repository, database, status
):
    baseline, config = _mapped(repository, database)
    old = _state(database, baseline.snapshot_id)
    path = repository / "web/helper.ts"
    path.write_text(path.read_text() + "\n// unrelated edit\n")
    current = RepositoryScanner(database).scan(repository)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_scope_states SET status=?,reason='explicit override' WHERE snapshot_id=? AND scope_key='pkg/core.py'",
            (status, current.snapshot_id),
        )
        carry_compatible_states(
            connection, current.repository_id, current.snapshot_id, baseline.snapshot_id, config
        )
    assert _state(database, current.snapshot_id)["status"] == status
    assert _state(database, baseline.snapshot_id) == old
    with database.transaction() as connection:
        connection.execute(
            "DELETE FROM semantic_scope_states WHERE snapshot_id=?", (current.snapshot_id,)
        )
        assert collect_semantic_states(connection) >= 1
    assert _state(database, baseline.snapshot_id) == old


@pytest.mark.parametrize("changed", ["prompt", "age", "resolver"])
def test_incompatible_prompt_age_or_resolver_never_carries_module_understanding(
    repository, database, changed
):
    baseline, config = _mapped(repository, database)
    if changed == "age":
        with database.transaction() as connection:
            connection.execute(
                "UPDATE semantic_documents SET created_at='2000-01-01T00:00:00+00:00'"
            )
    if changed == "resolver":
        policy_path = repository / ".anaxigraph.yml"
        policy = yaml.safe_load(policy_path.read_text())
        policy["aliases"]["@/"] = "different/"
        policy_path.write_text(yaml.safe_dump(policy))
    path = repository / "web/helper.ts"
    path.write_text(path.read_text() + "\n// unrelated edit\n")
    current = RepositoryScanner(database).scan(repository)
    with database.transaction() as connection:
        connection.execute(
            "DELETE FROM semantic_scope_states WHERE snapshot_id=?", (current.snapshot_id,)
        )
        semantic = replace(
            config.semantic,
            prompt_version="different" if changed == "prompt" else config.semantic.prompt_version,
            max_age_days=1 if changed == "age" else 0,
        )
        carry_compatible_states(
            connection,
            current.repository_id,
            current.snapshot_id,
            baseline.snapshot_id,
            replace(config, semantic=semantic),
        )
    assert _state(database, current.snapshot_id) is None
    assert _state(database, baseline.snapshot_id)["status"] == "current"
