"""Bounded SQLite queries for semantic status reporting."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.architecture_charter_corrections import read_charter_corrections
from anaxigraph.persistence.lock_holds import read_lock_holds


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
    charter_corrections: list[dict[str, Any]]
    taxonomy: dict[str, Any] | None
    current_semantic_actions: list[dict[str, Any]]
    lifetime_semantic_actions: list[dict[str, Any]]
    architecture_actions: list[dict[str, Any]]
    lock_holds: dict[str, Any]


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
        charter_corrections=read_charter_corrections(connection, repository_id),
        taxonomy=_taxonomy(connection, snapshot_id),
        current_semantic_actions=_semantic_actions(connection, repository_id, snapshot_id),
        lifetime_semantic_actions=_semantic_actions(connection, repository_id),
        architecture_actions=_architecture_actions(connection, repository_id),
        lock_holds=read_lock_holds(connection, snapshot_id),
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
               COALESCE(SUM(cache_read_input_tokens), 0) AS cache_read_input_tokens,
               COALESCE(SUM(cache_creation_input_tokens), 0) AS cache_creation_input_tokens,
               COALESCE(SUM(CASE WHEN status = 'completed'
                   THEN COALESCE(actual_cost_usd, estimated_cost_usd, 0)
                   ELSE COALESCE(actual_cost_usd, 0) END), 0) AS cost
        FROM semantic_jobs WHERE repository_id = ?
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
        SELECT ss.status, sd.id AS document_id, sd.value_json, sd.confidence, sd.provider, sd.model,
               sd.executor_id, sd.executor_model, sd.executor_effort, sd.prompt_version,
               sd.created_at
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
        SELECT st.*, ss.reason AS refresh_reason,
               (SELECT COUNT(*) FROM semantic_taxonomy_reviews str
                WHERE str.taxonomy_id = st.id) AS stored_reviews
        FROM semantic_taxonomies st
        LEFT JOIN semantic_scope_states ss
          ON ss.snapshot_id = st.snapshot_id AND ss.scope_type = 'taxonomy'
         AND ss.scope_key = CAST(st.repository_id AS TEXT)
        WHERE st.snapshot_id = ?
        ORDER BY CASE st.status WHEN 'current' THEN 0 ELSE 1 END, st.id DESC LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    return dict(row) if row else None


_SEMANTIC_ACTION_SQL = """
SELECT scope_type, job_kind,
       COUNT(*) AS jobs,
       SUM(status = 'completed') AS completed,
       SUM(status = 'running') AS running,
       SUM(status = 'pending') AS pending,
       SUM(status = 'retry') AS retry,
       SUM(status = 'failed') AS failed,
       SUM(status = 'superseded') AS superseded,
       SUM(usage_source = 'reported') AS token_counts_reported,
       SUM(usage_source = 'estimated') AS token_counts_estimated,
       SUM(status = 'completed' AND usage_source = 'unknown')
           AS token_counts_missing,
       COALESCE(SUM(input_tokens), 0) AS input_tokens,
       COALESCE(SUM(output_tokens), 0) AS output_tokens,
       COALESCE(SUM(cache_read_input_tokens), 0) AS cache_read_input_tokens,
       COALESCE(SUM(cache_creation_input_tokens), 0) AS cache_creation_input_tokens,
       COALESCE(SUM(CASE WHEN status = 'completed'
           THEN COALESCE(actual_cost_usd, estimated_cost_usd, 0) ELSE 0 END), 0)
           AS cost_usd,
       COALESCE(SUM(CASE WHEN started_at IS NOT NULL AND completed_at IS NOT NULL
           THEN (julianday(completed_at) - julianday(started_at)) * 86400000
           ELSE 0 END), 0) AS total_duration_ms,
       AVG(CASE WHEN started_at IS NOT NULL AND completed_at IS NOT NULL
           THEN (julianday(completed_at) - julianday(started_at)) * 86400000 END)
           AS average_duration_ms,
       MAX(CASE WHEN started_at IS NOT NULL AND completed_at IS NOT NULL
           THEN (julianday(completed_at) - julianday(started_at)) * 86400000 END)
           AS maximum_duration_ms,
       GROUP_CONCAT(DISTINCT COALESCE(NULLIF(executor_model, ''), NULLIF(model, ''),
           'unspecified')) AS models,
       GROUP_CONCAT(DISTINCT NULLIF(executor_effort, '')) AS efforts,
       MIN(started_at) AS first_started_at,
       MAX(completed_at) AS last_completed_at
FROM semantic_jobs WHERE repository_id = ?{snapshot_filter}
GROUP BY scope_type, job_kind ORDER BY scope_type, job_kind
"""

# Counted columns that are always whole numbers, so one reader handles every NULL the same way.
_ACTION_COUNTS = (
    "completed",
    "running",
    "pending",
    "retry",
    "failed",
    "superseded",
    "token_counts_reported",
    "token_counts_estimated",
    "token_counts_missing",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _semantic_actions(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int | None = None,
) -> list[dict[str, Any]]:
    snapshot_filter = " AND snapshot_id = ?" if snapshot_id is not None else ""
    parameters = (repository_id, snapshot_id) if snapshot_id is not None else (repository_id,)
    rows = connection.execute(
        _SEMANTIC_ACTION_SQL.format(snapshot_filter=snapshot_filter),
        parameters,
    ).fetchall()
    return [_semantic_action_row(row) for row in rows]


def _semantic_action_row(row: sqlite3.Row) -> dict[str, Any]:
    """Report one action group, including which efforts produced it and how usage was learned."""

    return {
        "scope_type": str(row["scope_type"]),
        "job_kind": str(row["job_kind"]),
        "jobs": int(row["jobs"]),
        **{name: int(row[name] or 0) for name in _ACTION_COUNTS},
        "cost_usd": round(float(row["cost_usd"] or 0), 6),
        "total_duration_ms": round(max(0.0, float(row["total_duration_ms"] or 0)), 3),
        "average_duration_ms": _duration(row["average_duration_ms"]),
        "maximum_duration_ms": _duration(row["maximum_duration_ms"]),
        "models": sorted(str(row["models"] or "").split(",")) if row["models"] else [],
        "efforts": sorted(str(row["efforts"] or "").split(",")) if row["efforts"] else [],
        "first_started_at": row["first_started_at"],
        "last_completed_at": row["last_completed_at"],
    }


def _architecture_actions(
    connection: sqlite3.Connection, repository_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT run_type,
               COUNT(*) AS runs,
               SUM(status IN ('complete', 'completed', 'completed_with_errors', 'unchanged'))
                   AS completed,
               SUM(status = 'running') AS running,
               SUM(status = 'failed') AS failed,
               SUM(status = 'interrupted') AS interrupted,
               SUM(status = 'cancelled') AS cancelled,
               SUM(discovered_count) AS discovered,
               SUM(analyzed_count) AS analyzed,
               SUM(reused_count) AS reused,
               SUM(error_count) AS errors,
               COALESCE(SUM(CASE WHEN completed_at IS NOT NULL AND status != 'interrupted'
                   THEN (julianday(completed_at) - julianday(started_at)) * 86400000
                   ELSE 0 END), 0) AS total_duration_ms,
               AVG(CASE WHEN completed_at IS NOT NULL AND status != 'interrupted'
                   THEN (julianday(completed_at) - julianday(started_at)) * 86400000 END)
                   AS average_duration_ms,
               MAX(CASE WHEN completed_at IS NOT NULL AND status != 'interrupted'
                   THEN (julianday(completed_at) - julianday(started_at)) * 86400000 END)
                   AS maximum_duration_ms,
               MIN(started_at) AS first_started_at,
               MAX(completed_at) AS last_completed_at
        FROM analysis_runs WHERE repository_id = ?
        GROUP BY run_type ORDER BY run_type
        """,
        (repository_id,),
    ).fetchall()
    return [_architecture_action_row(row) for row in rows]


def _architecture_action_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_type": str(row["run_type"]),
        "runs": int(row["runs"]),
        "completed": int(row["completed"] or 0),
        "running": int(row["running"] or 0),
        "failed": int(row["failed"] or 0),
        "interrupted": int(row["interrupted"] or 0),
        "cancelled": int(row["cancelled"] or 0),
        "discovered": int(row["discovered"] or 0),
        "analyzed": int(row["analyzed"] or 0),
        "reused": int(row["reused"] or 0),
        "errors": int(row["errors"] or 0),
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "total_duration_ms": round(max(0.0, float(row["total_duration_ms"] or 0)), 3),
        "average_duration_ms": _duration(row["average_duration_ms"]),
        "maximum_duration_ms": _duration(row["maximum_duration_ms"]),
        "first_started_at": row["first_started_at"],
        "last_completed_at": row["last_completed_at"],
    }


def _duration(value: Any) -> float | None:
    return round(max(0.0, float(value)), 3) if value is not None else None
