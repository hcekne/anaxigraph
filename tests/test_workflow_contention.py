"""Busy SQLite writers must not discard model results or stop a multi-wave workflow."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from semantic_support import _DeterministicLifecycleProvider
from test_semantic_lease_concurrency import _agent_queue
from test_workflow_steps import choice
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.storage import _begin_write
from anaxigraph.workflow_execution import WorkflowExecution


def impatient_connections(database, monkeypatch):
    busy, renewed = threading.Event(), threading.Event()

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            try:
                cursor = super().execute(sql, *args, **kwargs)
            except sqlite3.OperationalError as error:
                if error.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                    busy.set()
                raise
            if "UPDATE semantic_jobs SET lease_expires_at" in sql:
                renewed.set()
            return cursor

    def connect():
        connection = sqlite3.connect(database.path, timeout=0.01, factory=Connection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    monkeypatch.setattr(database, "connect", connect)
    return busy, renewed


def test_claim_retries_busy_admission_without_consuming_an_attempt(
    repository, database, monkeypatch
):
    config, repository_id, engine = _agent_queue(repository, database)
    busy, _ = impatient_connections(database, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.transaction():
            claim = pool.submit(engine._services.leases.claim_job, repository_id, config.semantic)
            assert busy.wait(5)
        job = claim.result(timeout=5)
    assert job["attempts"] == 1
    assert job["status"] == "running"


def test_heartbeat_recovers_from_busy_writer(repository, database, monkeypatch):
    config, repository_id, engine = _agent_queue(repository, database)
    leases = engine._services.leases
    job = leases.claim_job(repository_id, config.semantic)
    busy, renewed = impatient_connections(database, monkeypatch)
    monkeypatch.setattr("anaxigraph.semantic_leases._HEARTBEAT_INTERVAL_SECONDS", 0.01)
    with leases.job_lease(job, config.semantic):
        with database.transaction():
            assert busy.wait(5)
        assert renewed.wait(5)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM semantic_jobs WHERE id = ?", (job["id"],)
        ).fetchone()
    assert row["lease_expires_at"] > job["lease_expires_at"]
    assert row["attempts"] == 1


def test_busy_wait_is_bounded(database, monkeypatch):
    busy, _ = impatient_connections(database, monkeypatch)
    monkeypatch.setattr("anaxigraph.storage._WRITE_LOCK_WAIT_SECONDS", 0.06)

    def attempt():
        with database.transaction():
            pytest.fail("A held write lock must eventually raise, never enter the transaction")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.transaction():
            started = time.monotonic()
            pending = pool.submit(attempt)
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                pending.result(timeout=5)
            assert busy.is_set()
            assert time.monotonic() - started < 2


def test_transaction_body_error_rolls_back_without_replaying(database):
    calls = []
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        with database.transaction() as connection:
            calls.append(1)
            connection.execute("INSERT INTO schema_meta VALUES ('rollback-fixture', '1')")
            connection.execute("INSERT INTO missing_table VALUES (1)")
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT * FROM schema_meta WHERE key = 'rollback-fixture'"
            ).fetchone()
            is None
        )
    assert calls == [1]


@pytest.mark.parametrize("already_started", [False, True])
def test_admission_restores_timeout_and_does_not_retry_non_busy_errors(
    database, monkeypatch, already_started
):
    monkeypatch.setattr("anaxigraph.storage._WRITE_LOCK_WAIT_SECONDS", 0.01)

    def unexpected_retry(*args):
        pytest.fail("Only a busy writer is retryable")

    monkeypatch.setattr("anaxigraph.storage.time.sleep", unexpected_retry)
    connection = database.connect()
    try:
        if already_started:
            connection.execute("BEGIN IMMEDIATE")
            with pytest.raises(sqlite3.OperationalError, match="within a transaction"):
                _begin_write(connection)
        else:
            _begin_write(connection)
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        connection.rollback()
        connection.close()


def test_sixteen_context_workers_drain_all_jobs_after_contended_saves(
    repository, database, monkeypatch
):
    for index in range(88):
        (repository / "pkg" / f"module_{index}.py").write_text(f"VALUE = {index}\n")
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    config = replace(config, semantic=replace(config.semantic, max_parallel_jobs=16))
    row = database.repository(repository)
    settings = {step: [choice(workers=16)] for step in ("intrinsic", "context")}

    def run(step):
        return WorkflowExecution(
            database, row, config, WorkflowRequest(workflow="mapping", step=step), settings
        ).run()

    assert run("intrinsic")["processed"] == 96
    ready, release = threading.Event(), threading.Event()
    barrier = threading.Barrier(16, action=ready.set)
    calls, lock = [], threading.Lock()

    class Provider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            with lock:
                calls.append(request["path"])
                first_wave = len(calls) <= 16
            if first_wave:
                barrier.wait(15)
                assert release.wait(15)
            return super().analyze(request)

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", lambda _: Provider())
    busy, _ = impatient_connections(database, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(run, "context")
        try:
            assert ready.wait(20)
            with database.transaction():
                release.set()
                assert busy.wait(5)
        finally:
            release.set()
        result = pending.result(timeout=30)
    assert result["status"] == "complete"
    assert result["processed"] == 96
    assert len(calls) == len(set(calls)) == 96
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT status, attempts FROM semantic_jobs WHERE job_kind = 'context'"
        ).fetchall()
        documents = connection.execute(
            "SELECT COUNT(*) FROM semantic_documents WHERE document_kind = 'context'"
        ).fetchone()[0]
    assert Counter(tuple(row) for row in rows) == {("completed", 1): 96}
    assert documents == 96
