"""Full search allocation rolls back once, then rebuilds only disposable search state."""

import sqlite3

import pytest
from test_semantic_state_bindings import _mapped, _paid_rows

import anaxigraph.persistence.search_read as search
from anaxigraph.understanding import SemanticEngine


def _rows(database, table):
    with database.connect() as connection:
        return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1,2,3")]


def test_full_search_allocation_recovers_once_before_returning_a_valid_plan(
    repository, database, monkeypatch
):
    stats, config = _mapped(repository, database)
    originals = _paid_rows(database)
    inserts, maintenance = [], []
    insert = search.insert_search_rows
    finish = database.finish_cache_maintenance

    def full_once(connection, rows, **options):
        inserts.append(len(rows))
        if len(inserts) == 1:
            error = sqlite3.OperationalError("injected full FTS allocation")
            error.sqlite_errorcode = sqlite3.SQLITE_FULL
            raise error
        return insert(connection, rows, **options)

    def finish_actual_maintenance():
        maintenance.append(True)
        return finish()

    monkeypatch.setattr(search, "insert_search_rows", full_once)
    monkeypatch.setattr(database, "finish_cache_maintenance", finish_actual_maintenance)
    plan = SemanticEngine(database).plan(stats.repository_id, repository, config, force=True)

    assert maintenance == [True] and len(inserts) == 2
    assert plan.enqueued > 0 and plan.active_jobs == plan.enqueued
    assert _paid_rows(database) == originals
    assert database.search(stats.repository_id, "Calculator")[0]["path"] == "pkg/core.py"
    with database.connect() as connection:
        pending = connection.execute(
            "SELECT COUNT(*) FROM semantic_jobs WHERE status='pending' AND job_kind='annotation'"
        ).fetchone()[0]
        assert pending == plan.enqueued
        assert not connection.execute(
            "SELECT 1 FROM schema_meta WHERE key IN ('index-compaction-pending','graph-import-pending')"
        ).fetchone()
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_non_capacity_search_failure_does_not_retry_or_change_canonical_state(
    repository, database, monkeypatch
):
    stats, config = _mapped(repository, database)
    originals = _paid_rows(database)
    states = _rows(database, "semantic_scope_states")
    bindings = _rows(database, "semantic_state_bindings")
    calls = []

    def fail_io(*_args, **_options):
        calls.append(True)
        error = sqlite3.OperationalError("injected I/O failure")
        error.sqlite_errorcode = sqlite3.SQLITE_IOERR
        raise error

    monkeypatch.setattr(search, "insert_search_rows", fail_io)
    with pytest.raises(sqlite3.OperationalError, match="injected I/O failure"):
        SemanticEngine(database).plan(stats.repository_id, repository, config, force=True)
    assert calls == [True]
    assert _paid_rows(database) == originals
    assert _rows(database, "semantic_scope_states") == states
    assert _rows(database, "semantic_state_bindings") == bindings
