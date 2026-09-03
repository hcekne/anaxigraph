"""Measure how long an index write transaction waits for and holds the SQLite write lock."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

LOCK_HOLD_ENTITY = "semantic_plan_transaction"
LOCK_HOLD_METRIC = "semantic_plan_lock_hold"
_LOCKED_MARKER = "database is locked"
_WAIT_FLOOR_MS = 1.0
_REFUSAL_BUSY_TIMEOUT_MS = 250

EMPTY_LOCK_HOLDS: dict[str, Any] = {
    "measured_transactions": 0,
    "total_hold_ms": 0.0,
    "maximum_hold_ms": 0.0,
    "waiting_transactions": 0,
    "total_lock_wait_ms": 0.0,
    "maximum_lock_wait_ms": 0.0,
    "locked_transactions": 0,
}


@dataclass(frozen=True, slots=True)
class LockHold:
    """One measured write transaction: its wait for the write lock and its hold of it."""

    wait_ms: float
    hold_ms: float
    locked: bool = False


@contextlib.contextmanager
def measured_plan_transaction(
    connect: Callable[[], sqlite3.Connection], snapshot_id: int
) -> Iterator[sqlite3.Connection]:
    """Run one ``BEGIN IMMEDIATE`` transaction and store what its write lock cost.

    The wait is the time ``BEGIN IMMEDIATE`` spent acquiring the lock; the hold runs
    from that grant to the last statement before the commit, so the commit itself is
    not counted. A transaction that fails keeps its lock cost unrecorded, except a
    refusal after the busy timeout, which is counted on a separate connection.
    """

    connection = connect()
    try:
        wait_ms = _begin_immediate(connection)
    except sqlite3.OperationalError as error:
        connection.close()
        _record_refusal(connect, snapshot_id, error)
        raise
    granted = time.perf_counter()
    try:
        yield connection
        record_lock_hold(connection, snapshot_id, LockHold(wait_ms, _elapsed_ms(granted)))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def record_lock_hold(connection: sqlite3.Connection, snapshot_id: int, hold: LockHold) -> None:
    """Merge one measured transaction into the snapshot's stored lock-hold measurement."""

    measured = _merged(read_lock_holds(connection, snapshot_id), hold)
    encoded = json.dumps(measured, sort_keys=True)
    updated = connection.execute(
        """
        UPDATE metrics SET value = ?, metadata_json = ?
        WHERE snapshot_id = ? AND entity_type = ? AND name = ?
        """,
        (measured["maximum_hold_ms"], encoded, snapshot_id, LOCK_HOLD_ENTITY, LOCK_HOLD_METRIC),
    ).rowcount
    if not updated:
        connection.execute(
            """
            INSERT INTO metrics(snapshot_id, entity_type, entity_id, name, value, metadata_json)
            VALUES (?, ?, NULL, ?, ?, ?)
            """,
            (
                snapshot_id,
                LOCK_HOLD_ENTITY,
                LOCK_HOLD_METRIC,
                measured["maximum_hold_ms"],
                encoded,
            ),
        )


def read_lock_holds(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any]:
    """Read the lock-hold measurement stored for one snapshot."""

    row = connection.execute(
        """
        SELECT metadata_json FROM metrics
        WHERE snapshot_id = ? AND entity_type = ? AND name = ? LIMIT 1
        """,
        (snapshot_id, LOCK_HOLD_ENTITY, LOCK_HOLD_METRIC),
    ).fetchone()
    return _decoded(row[0] if row else None)


def _begin_immediate(connection: sqlite3.Connection) -> float:
    started = time.perf_counter()
    connection.execute("BEGIN IMMEDIATE")
    return _elapsed_ms(started)


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (time.perf_counter() - started) * 1_000), 3)


def _record_refusal(
    connect: Callable[[], sqlite3.Connection],
    snapshot_id: int,
    error: sqlite3.OperationalError,
) -> None:
    """Count a refused transaction without waiting out a second busy timeout."""

    if _LOCKED_MARKER not in str(error).lower():
        return
    with contextlib.suppress(sqlite3.Error):
        connection = connect()
        try:
            connection.execute(f"PRAGMA busy_timeout = {_REFUSAL_BUSY_TIMEOUT_MS}")
            connection.execute("BEGIN IMMEDIATE")
            record_lock_hold(connection, snapshot_id, LockHold(0.0, 0.0, locked=True))
            connection.commit()
        finally:
            connection.close()


def _decoded(encoded: str | None) -> dict[str, Any]:
    measured = dict(EMPTY_LOCK_HOLDS)
    if not encoded:
        return measured
    stored = json.loads(encoded)
    measured.update({key: stored[key] for key in EMPTY_LOCK_HOLDS if key in stored})
    return measured


def _merged(measured: dict[str, Any], hold: LockHold) -> dict[str, Any]:
    if hold.locked:
        return {**measured, "locked_transactions": int(measured["locked_transactions"]) + 1}
    waited = int(hold.wait_ms >= _WAIT_FLOOR_MS)
    return {
        **measured,
        "measured_transactions": int(measured["measured_transactions"]) + 1,
        "total_hold_ms": round(float(measured["total_hold_ms"]) + hold.hold_ms, 3),
        "maximum_hold_ms": round(max(float(measured["maximum_hold_ms"]), hold.hold_ms), 3),
        "waiting_transactions": int(measured["waiting_transactions"]) + waited,
        "total_lock_wait_ms": round(float(measured["total_lock_wait_ms"]) + hold.wait_ms, 3),
        "maximum_lock_wait_ms": round(
            max(float(measured["maximum_lock_wait_ms"]), hold.wait_ms), 3
        ),
    }
