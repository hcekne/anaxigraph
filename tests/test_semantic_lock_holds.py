"""Measured lock waits and holds for the one semantic plan transaction."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import yaml

from anaxigraph.config import load_config
from anaxigraph.persistence.lock_holds import (
    EMPTY_LOCK_HOLDS,
    LockHold,
    measured_plan_transaction,
    read_lock_holds,
    record_lock_hold,
)
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine

HOLD_SECONDS = 0.25
WRITE_BACK_JOBS = 30


class _LockHolder:
    """Hold the index write lock until a contender has opened its connection, then a bit longer.

    The release is driven by the contender rather than by a bare sleep, so the wait the
    contender measures is a fact of the fixture and not of the machine's scheduling.
    """

    def __init__(self, database: AnaxiIndex, hold_seconds: float = HOLD_SECONDS) -> None:
        self._database = database
        self._hold_seconds = hold_seconds
        self.holding = threading.Event()
        self.release = threading.Event()
        self._thread = threading.Thread(target=self._hold, daemon=True)

    def __enter__(self) -> _LockHolder:
        self._thread.start()
        assert self.holding.wait(timeout=10)
        return self

    def __exit__(self, *_: object) -> None:
        self.release.set()
        self._thread.join(timeout=30)

    def _hold(self) -> None:
        with self._database.transaction() as connection:
            connection.execute("SELECT COUNT(*) FROM metrics")
            self.holding.set()
            self.release.wait(timeout=30)
            time.sleep(self._hold_seconds)


def _releasing_connect(
    database: AnaxiIndex, holder: _LockHolder
) -> Callable[[], sqlite3.Connection]:
    """Start the holder's countdown exactly when the measured transaction connects."""

    def connect() -> sqlite3.Connection:
        connection = database.connect()
        holder.release.set()
        return connection

    return connect


def _main_thread_releasing_connect(
    database: AnaxiIndex, holder: _LockHolder
) -> Callable[[], sqlite3.Connection]:
    """Release only for the planning thread, so parallel write-backs never trigger it."""

    original = database.connect
    planner = threading.current_thread()

    def connect() -> sqlite3.Connection:
        connection = original()
        if threading.current_thread() is planner:
            holder.release.set()
        return connection

    return connect


def _semantic_repository(repository: Path) -> None:
    path = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent", "max_parallel_jobs": 4}
    path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")


def _write_back(database: AnaxiIndex, repository_id: int, snapshot_id: int, index: int) -> None:
    """Write one sidecar-shaped scope-state row through the shared index write lock."""

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO semantic_scope_states(
                repository_id, snapshot_id, scope_type, scope_key, status, reason, last_checked_at
            ) VALUES (?, ?, 'module', ?, 'current', 'parallel write-back fixture', ?)
            """,
            (repository_id, snapshot_id, f"fixture/write_back_{index}.py", "2026-01-01T00:00:00Z"),
        )


def _stored(database: AnaxiIndex, snapshot_id: int) -> dict[str, Any]:
    with database.connect() as connection:
        return read_lock_holds(connection, snapshot_id)


def test_unmeasured_snapshot_reports_zeroed_lock_holds(repository, database) -> None:
    snapshot_id = RepositoryScanner(database).scan(repository).snapshot_id

    assert _stored(database, snapshot_id) == EMPTY_LOCK_HOLDS


def test_measured_transaction_records_its_wait_and_hold(repository, database) -> None:
    stats = RepositoryScanner(database).scan(repository)

    with _LockHolder(database) as holder:
        connect = _releasing_connect(database, holder)
        with measured_plan_transaction(connect, stats.snapshot_id) as connection:
            connection.execute("SELECT COUNT(*) FROM metrics")
            time.sleep(0.05)

    measured = _stored(database, stats.snapshot_id)
    assert measured["measured_transactions"] == 1
    assert measured["waiting_transactions"] == 1
    assert measured["maximum_lock_wait_ms"] >= 50
    assert measured["maximum_lock_wait_ms"] == measured["total_lock_wait_ms"]
    assert measured["maximum_hold_ms"] >= 50
    assert measured["locked_transactions"] == 0


def test_uncontended_transactions_accumulate_their_holds(repository, database) -> None:
    stats = RepositoryScanner(database).scan(repository)

    for _ in range(3):
        with measured_plan_transaction(database.connect, stats.snapshot_id) as connection:
            connection.execute("SELECT COUNT(*) FROM metrics")

    measured = _stored(database, stats.snapshot_id)
    assert measured["measured_transactions"] == 3
    assert measured["total_hold_ms"] >= measured["maximum_hold_ms"] > 0
    assert measured["locked_transactions"] == 0


def test_a_rolled_back_transaction_records_no_measurement(repository, database) -> None:
    stats = RepositoryScanner(database).scan(repository)

    with pytest.raises(RuntimeError, match="planning failed"):
        with measured_plan_transaction(database.connect, stats.snapshot_id):
            raise RuntimeError("planning failed")

    assert _stored(database, stats.snapshot_id) == EMPTY_LOCK_HOLDS


def test_a_refused_transaction_is_counted_as_locked(repository, database) -> None:
    stats = RepositoryScanner(database).scan(repository)

    with _LockHolder(database, hold_seconds=0.05) as holder:
        releasing = _releasing_connect(database, holder)

        def impatient() -> sqlite3.Connection:
            connection = releasing()
            connection.execute("PRAGMA busy_timeout = 20")
            return connection

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            with measured_plan_transaction(impatient, stats.snapshot_id):
                pytest.fail("the write lock should have refused this transaction")

    measured = _stored(database, stats.snapshot_id)
    assert measured["locked_transactions"] == 1
    assert measured["measured_transactions"] == 0
    assert measured["maximum_hold_ms"] == 0.0


def test_thirty_parallel_write_backs_measure_the_plan_lock_hold(
    repository, database, monkeypatch
) -> None:
    """Drive 30 concurrent write-backs against one index while a plan takes the write lock."""

    _semantic_repository(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)

    with _LockHolder(database) as holder:
        monkeypatch.setattr(database, "connect", _main_thread_releasing_connect(database, holder))
        with ThreadPoolExecutor(max_workers=8) as pool:
            writes = [
                pool.submit(_write_back, database, stats.repository_id, stats.snapshot_id, index)
                for index in range(WRITE_BACK_JOBS)
            ]
            plan = engine.plan(stats.repository_id, repository, config)
            for write in writes:
                write.result(timeout=60)

    assert plan.enqueued > 0
    measured = engine.status(stats.repository_id, config.semantic)["telemetry"]["lock_holds"]
    assert measured["measured_transactions"] == 1
    assert measured["waiting_transactions"] == 1
    assert measured["maximum_lock_wait_ms"] >= 50
    assert measured["maximum_hold_ms"] > 0
    assert "not budgets or limits" in measured["measurement_note"]


def test_status_telemetry_reports_lock_holds_beside_action_totals(repository, database) -> None:
    _semantic_repository(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)

    telemetry = engine.status(stats.repository_id, config.semantic)["telemetry"]
    measured = telemetry["lock_holds"]

    assert telemetry["contract_version"] == "action-telemetry-v1"
    assert set(telemetry["semantic"]["current_snapshot"]["totals"]) >= {"jobs", "completed"}
    assert set(measured) == set(EMPTY_LOCK_HOLDS) | {"measurement_note"}
    assert measured["measured_transactions"] == 1
    assert measured["maximum_hold_ms"] > 0
    assert measured["locked_transactions"] == 0


def test_locked_and_measured_counts_accumulate_independently(repository, database) -> None:
    stats = RepositoryScanner(database).scan(repository)

    with database.transaction() as connection:
        record_lock_hold(connection, stats.snapshot_id, LockHold(0.0, 0.0, locked=True))
        record_lock_hold(connection, stats.snapshot_id, LockHold(4.0, 12.0))
        record_lock_hold(connection, stats.snapshot_id, LockHold(0.5, 7.0))

    measured = _stored(database, stats.snapshot_id)
    assert measured["locked_transactions"] == 1
    assert measured["measured_transactions"] == 2
    assert measured["waiting_transactions"] == 1
    assert measured["total_lock_wait_ms"] == 4.5
    assert measured["maximum_lock_wait_ms"] == 4.0
    assert measured["maximum_hold_ms"] == 12.0
    assert measured["total_hold_ms"] == 19.0
