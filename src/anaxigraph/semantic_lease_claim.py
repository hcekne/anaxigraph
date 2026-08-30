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
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_job_state import semantic_job_bulk_transition, semantic_job_transition


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
) -> dict[str, Any] | None:
    """Claim one eligible job while enforcing concurrency and spend admission."""

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
        row = _next_job(connection, repository_id, snapshot_id, now)
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


def _next_job(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    now: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM semantic_jobs
        WHERE repository_id = ? AND snapshot_id = ?
          AND status IN ('pending', 'retry') AND available_at <= ?
        ORDER BY priority DESC, id LIMIT 1
        """,
        (repository_id, snapshot_id, now),
    ).fetchone()


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
) -> dict[str, Any]:
    selected_worker = worker_id or f"{os.getpid()}:{threading.get_ident()}:{int(row['id'])}"
    seconds = lease_seconds or max(90, semantic.timeout_seconds + 60)
    expires = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
    target = semantic_job_transition(str(row["status"]), "claim")
    connection.execute(
        """
        UPDATE semantic_jobs SET status = ?, attempts = attempts + 1,
            started_at = ?, worker_id = ?, lease_expires_at = ?, error = NULL,
            lease_token_hash = ?, executor_id = ?, executor_model = ?
        WHERE id = ?
        """,
        (
            target,
            now,
            selected_worker,
            expires,
            lease_token_hash,
            executor_id,
            executor_model,
            int(row["id"]),
        ),
    )
    result = dict(row)
    result.update(
        status=target,
        attempts=int(result["attempts"]) + 1,
        worker_id=selected_worker,
        lease_expires_at=expires,
        lease_token_hash=lease_token_hash,
        executor_id=executor_id,
        executor_model=executor_model,
    )
    result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    return result
