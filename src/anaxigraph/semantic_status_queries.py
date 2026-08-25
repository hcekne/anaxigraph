"""Bounded SQLite queries for semantic status reporting."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class SemanticStatusRows:
    counts: dict[str, int]
    scope_counts: dict[str, dict[str, int]]
    jobs: dict[str, int]
    usage: dict[str, Any]
    daily_spend: float
    reserved_spend: float
    next_estimated_cost: float
    last_checked: str | None
    repository_state: dict[str, Any] | None
    taxonomy: dict[str, Any] | None


def read_semantic_status(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    timeout_seconds: int = 300,
) -> SemanticStatusRows:
    counts = _module_counts(connection, snapshot_id)
    scope_counts = _scope_counts(connection, snapshot_id)
    jobs = _job_counts(connection, repository_id, snapshot_id, timeout_seconds)
    usage = dict(_usage(connection, repository_id))
    daily_spend, reserved_spend = _spend(connection, repository_id)
    return SemanticStatusRows(
        counts=counts,
        scope_counts=scope_counts,
        jobs=jobs,
        usage=usage,
        daily_spend=daily_spend,
        reserved_spend=reserved_spend,
        next_estimated_cost=_next_cost(connection, repository_id, snapshot_id),
        last_checked=_last_checked(connection, snapshot_id),
        repository_state=_repository_state(connection, snapshot_id),
        taxonomy=_taxonomy(connection, snapshot_id),
    )


def _module_counts(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT status, COUNT(*) AS count FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'module' GROUP BY status
        """,
        (snapshot_id,),
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _scope_counts(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, dict[str, int]]:
    rows = connection.execute(
        """
        SELECT scope_type, status, COUNT(*) AS count FROM semantic_scope_states
        WHERE snapshot_id = ? GROUP BY scope_type, status
        """,
        (snapshot_id,),
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        counts.setdefault(str(row["scope_type"]), {})[str(row["status"])] = int(row["count"])
    return counts


def _job_counts(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    timeout_seconds: int,
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT status, COUNT(*) AS count FROM semantic_jobs
        WHERE repository_id = ? AND snapshot_id = ? GROUP BY status
        """,
        (repository_id, snapshot_id),
    ).fetchall()
    counts = {str(row["status"]): int(row["count"]) for row in rows}
    live, expired = _running_counts(connection, repository_id, snapshot_id, timeout_seconds)
    counts.update(running_live=live, running_expired=expired, reclaimable=expired)
    return counts


def _running_counts(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    timeout_seconds: int,
) -> tuple[int, int]:
    now = datetime.now(UTC)
    stale_before = (now - timedelta(seconds=max(90, timeout_seconds + 60))).isoformat()
    row = connection.execute(
        """
        SELECT
          SUM(CASE WHEN lease_expires_at >= ? THEN 1 ELSE 0 END) AS live,
          SUM(CASE WHEN lease_expires_at < ? OR
             (lease_expires_at IS NULL AND started_at < ?) THEN 1 ELSE 0 END) AS expired
        FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ? AND status = 'running'
        """,
        (now.isoformat(), now.isoformat(), stale_before, repository_id, snapshot_id),
    ).fetchone()
    return int(row["live"] or 0), int(row["expired"] or 0)


def _usage(connection: sqlite3.Connection, repository_id: int) -> sqlite3.Row:
    return connection.execute(
        """
        SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
               COALESCE(SUM(output_tokens), 0) AS output_tokens,
               COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd, 0)), 0) AS cost
        FROM semantic_jobs WHERE repository_id = ? AND status = 'completed'
        """,
        (repository_id,),
    ).fetchone()


def _spend(connection: sqlite3.Connection, repository_id: int) -> tuple[float, float]:
    today = datetime.now(UTC).date().isoformat()
    daily = connection.execute(
        """
        SELECT COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd, 0)), 0)
        FROM semantic_jobs WHERE repository_id = ? AND status = 'completed'
          AND substr(completed_at, 1, 10) = ?
        """,
        (repository_id, today),
    ).fetchone()[0]
    reserved = connection.execute(
        """
        SELECT COALESCE(SUM(COALESCE(estimated_cost_usd, 0)), 0)
        FROM semantic_jobs WHERE repository_id = ? AND status = 'running'
        """,
        (repository_id,),
    ).fetchone()[0]
    return float(daily), float(reserved)


def _next_cost(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
) -> float:
    row = connection.execute(
        """
        SELECT COALESCE(estimated_cost_usd, 0) AS estimated_cost_usd
        FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ?
          AND status IN ('pending', 'retry')
        ORDER BY priority DESC, id LIMIT 1
        """,
        (repository_id, snapshot_id),
    ).fetchone()
    return float(row["estimated_cost_usd"] if row else 0)


def _last_checked(connection: sqlite3.Connection, snapshot_id: int) -> str | None:
    return connection.execute(
        "SELECT MAX(last_checked_at) FROM semantic_scope_states WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()[0]


def _repository_state(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT ss.status, sd.value_json, sd.confidence, sd.provider, sd.model,
               sd.executor_id, sd.executor_model, sd.prompt_version, sd.created_at
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents sd ON sd.id = ss.context_document_id
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'repository'
        """,
        (snapshot_id,),
    ).fetchone()
    return dict(row) if row else None


def _taxonomy(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT st.*,
               (SELECT COUNT(*) FROM semantic_taxonomy_reviews str
                WHERE str.taxonomy_id = st.id) AS stored_reviews
        FROM semantic_taxonomies st WHERE st.snapshot_id = ?
        ORDER BY CASE st.status WHEN 'current' THEN 0 ELSE 1 END, st.id DESC LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    return dict(row) if row else None
