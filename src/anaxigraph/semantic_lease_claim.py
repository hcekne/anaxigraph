"""Admission and atomic claiming for semantic jobs."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_fresh_eyes_contract import ANY_EXECUTOR
from anaxigraph.semantic_fresh_eyes_diversity import executor_family as identity_family
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_job_state import semantic_job_bulk_transition, semantic_job_transition

CANDIDATE_PAGE = 50


def claim_next_job(
    database: SemanticIndex,
    repository_id: int,
    semantic: SemanticConfig,
    *,
    worker_id: str | None,
    lease_seconds: int | None,
    lease_token_hash: str | None,
    executor_id: str | None,
    executor_model: str | None,
    executor_effort: str | None = None,
    executor_family: str | None = None,
) -> dict[str, Any] | None:
    """Claim one eligible job while enforcing concurrency, spend, and executor admission."""

    with database.transaction() as connection:
        snapshot_id = _current_snapshot_id(connection, repository_id)
        if snapshot_id is None:
            return None
        now = utc_now()
        reconcile_claimable_jobs(
            connection,
            repository_id,
            snapshot_id,
            semantic,
            now=now,
        )
        if _active_workers(connection, repository_id, now) >= semantic.max_parallel_jobs:
            return None
        spent = _reserved_daily_spend(connection, repository_id, semantic)
        family = claimant_family(executor_id, executor_family)
        row = _next_job(connection, repository_id, snapshot_id, now, family)
        if row is None or _exceeds_budget(row, spent, semantic):
            return None
        return _claim_row(
            connection,
            row,
            semantic,
            now=now,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            lease_token_hash=lease_token_hash,
            executor_id=executor_id,
            executor_model=executor_model,
            executor_effort=executor_effort,
        )


def reconcile_claimable_jobs(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    semantic: SemanticConfig,
    *,
    now: str | None = None,
) -> None:
    """Atomically heal expired work and retire jobs from older snapshots."""

    current = now or utc_now()
    stale_before = (
        datetime.now(UTC) - timedelta(seconds=max(90, semantic.timeout_seconds + 60))
    ).isoformat()
    retry = semantic_job_transition("running", "lease_expired")
    superseded = semantic_job_bulk_transition(("pending", "retry", "running"), "supersede")
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, available_at = ?,
            worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
            error = 'The previous worker lease expired; this job was safely requeued.'
        WHERE repository_id = ? AND status = 'running'
          AND (lease_expires_at < ? OR (lease_expires_at IS NULL AND started_at < ?))
        """,
        (retry, current, repository_id, current, stale_before),
    )
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, completed_at = ?, metadata_json = '{}',
            worker_id = NULL, lease_expires_at = NULL, lease_token_hash = NULL,
            error = 'A newer repository snapshot replaced this job.'
        WHERE repository_id = ? AND snapshot_id != ?
          AND status IN ('pending', 'retry', 'running')
        """,
        (superseded, current, repository_id, snapshot_id),
    )


def _current_snapshot_id(connection: sqlite3.Connection, repository_id: int) -> int | None:
    row = connection.execute(
        "SELECT current_snapshot_id FROM repositories WHERE id = ?", (repository_id,)
    ).fetchone()
    return int(row["current_snapshot_id"]) if row and row["current_snapshot_id"] else None


def _active_workers(connection: sqlite3.Connection, repository_id: int, now: str) -> int:
    return int(
        connection.execute(
            """
            SELECT COUNT(*) FROM semantic_jobs
            WHERE repository_id = ? AND status = 'running'
              AND lease_expires_at IS NOT NULL AND lease_expires_at >= ?
            """,
            (repository_id, now),
        ).fetchone()[0]
    )


def _reserved_daily_spend(
    connection: sqlite3.Connection,
    repository_id: int,
    semantic: SemanticConfig,
) -> float:
    if semantic.daily_budget_usd is None:
        return 0.0
    today = datetime.now(UTC).date().isoformat()
    return float(
        connection.execute(
            """
            SELECT COALESCE(SUM(
                CASE WHEN status = 'running' THEN COALESCE(estimated_cost_usd, 0)
                     ELSE COALESCE(actual_cost_usd, estimated_cost_usd, 0) END
            ), 0)
            FROM semantic_jobs WHERE repository_id = ? AND (
                status = 'running'
                OR (status = 'completed' AND substr(completed_at, 1, 10) = ?)
            )
            """,
            (repository_id, today),
        ).fetchone()[0]
    )


def claimant_family(executor_id: str | None, declared: str | None = None) -> str:
    """Name the executor family of one claimant: the declared one, else its ``cli:`` identity."""

    explicit = str(declared or "").strip().lower()
    return explicit or identity_family(executor_id)


def _next_job(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    now: str,
    family: str,
) -> sqlite3.Row | None:
    """Take the first job of a small candidate page this executor family may run.

    The index uses no SQLite JSON1 function anywhere, so the executor pin recorded in
    ``metadata_json`` is read in Python. Only the at most three proposal slots of one review
    carry a pin, so a page this size always holds an eligible job when one exists.
    """

    rows = connection.execute(
        """
        SELECT * FROM semantic_jobs
        WHERE repository_id = ? AND snapshot_id = ?
          AND status IN ('pending', 'retry') AND available_at <= ?
        ORDER BY priority DESC, id LIMIT ?
        """,
        (repository_id, snapshot_id, now, CANDIDATE_PAGE),
    ).fetchall()
    return next((row for row in rows if claimable_by(row, family)), None)


def claimable_by(row: Any, family: str) -> bool:
    """Skip a job pinned to a different executor family; unpinned work stays first-come."""

    pin = required_executor(row)
    return not pin or pin == ANY_EXECUTOR or pin == family


def required_executor(row: Any) -> str:
    """Read the executor family one queued job was pinned to, if any."""

    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return ""
    return str(metadata.get("required_executor") or "").strip().lower()


def _exceeds_budget(row: sqlite3.Row, spent: float, semantic: SemanticConfig) -> bool:
    return bool(
        semantic.daily_budget_usd is not None
        and spent + float(row["estimated_cost_usd"] or 0) > semantic.daily_budget_usd
    )


def _claim_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    semantic: SemanticConfig,
    *,
    now: str,
    worker_id: str | None,
    lease_seconds: int | None,
    lease_token_hash: str | None,
    executor_id: str | None,
    executor_model: str | None,
    executor_effort: str | None,
) -> dict[str, Any] | None:
    selected_worker = worker_id or f"{os.getpid()}:{threading.get_ident()}:{int(row['id'])}"
    seconds = lease_seconds or max(90, semantic.timeout_seconds + 60)
    claimed = {
        "status": semantic_job_transition(str(row["status"]), "claim"),
        "worker_id": selected_worker,
        "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
        "lease_token_hash": lease_token_hash,
        "executor_id": executor_id,
        "executor_model": executor_model,
        "executor_effort": executor_effort,
    }
    if not _apply_claim(connection, row, claimed, now):
        return None
    result = dict(row)
    result.update(claimed, attempts=int(result["attempts"]) + 1)
    result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    return result


def _apply_claim(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    claimed: dict[str, Any],
    now: str,
) -> bool:
    """Take the job only while it still holds the status the caller read."""

    cursor = connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, attempts = attempts + 1,
            started_at = ?, worker_id = ?, lease_expires_at = ?, error = NULL,
            lease_token_hash = ?, executor_id = ?, executor_model = ?, executor_effort = ?
        WHERE id = ? AND status = ?
        """,
        (
            claimed["status"],
            now,
            claimed["worker_id"],
            claimed["lease_expires_at"],
            claimed["lease_token_hash"],
            claimed["executor_id"],
            claimed["executor_model"],
            claimed["executor_effort"],
            int(row["id"]),
            str(row["status"]),
        ),
    )
    return cursor.rowcount == 1
