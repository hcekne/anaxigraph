"""Snapshot coverage for the interactive workflow view, including reused documents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def workflow_coverage(connection: Any, snapshot_id: int) -> dict[str, Any]:
    return {
        "scopes": _scopes(connection, snapshot_id),
        **_execution(connection, snapshot_id),
        "scan": _scan(connection, snapshot_id),
        "failures": _failures(connection, snapshot_id),
    }


def _scopes(connection: Any, snapshot_id: int) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT ss.scope_type, COUNT(*) AS total,
          SUM(ss.status = 'current') AS current,
          SUM(ss.status = 'excluded') AS excluded,
          SUM(i.id IS NOT NULL AND ss.status NOT IN
            ('pending_intrinsic', 'failed_intrinsic', 'excluded')) AS intrinsic,
          SUM(i.snapshot_id != ss.snapshot_id AND ss.status NOT IN
            ('pending_intrinsic', 'failed_intrinsic', 'excluded')) AS intrinsic_reused,
          SUM(c.snapshot_id != ss.snapshot_id AND ss.status = 'current') AS reused
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents i ON i.id = ss.intrinsic_document_id
        LEFT JOIN semantic_documents c ON c.id = ss.context_document_id
        WHERE ss.snapshot_id = ? GROUP BY ss.scope_type
        """,
        (snapshot_id,),
    ).fetchall()
    return {
        row["scope_type"]: {key: int(row[key] or 0) for key in row.keys() if key != "scope_type"}
        for row in rows
    }


def _execution(connection: Any, snapshot_id: int) -> dict[str, Any]:
    live = connection.execute(
        """
        SELECT job_kind, scope_type,
          SUM(status = 'running' AND lease_expires_at >= ?) AS running,
          SUM(status = 'running' AND (lease_expires_at < ? OR lease_expires_at IS NULL))
            AS interrupted
        FROM semantic_jobs WHERE snapshot_id = ? GROUP BY job_kind, scope_type
        """,
        (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), snapshot_id),
    ).fetchall()
    models = connection.execute(
        """
        SELECT ss.scope_type, d.document_kind,
          GROUP_CONCAT(DISTINCT COALESCE(NULLIF(d.executor_model, ''), NULLIF(d.model, '')))
            AS models
        FROM semantic_scope_states ss JOIN semantic_documents d
          ON d.id IN (ss.intrinsic_document_id, ss.context_document_id)
        WHERE ss.snapshot_id = ? AND (ss.status = 'current' OR
          (d.id = ss.intrinsic_document_id AND ss.status NOT IN
            ('pending_intrinsic', 'failed_intrinsic', 'excluded')))
        GROUP BY ss.scope_type, d.document_kind
        """,
        (snapshot_id,),
    ).fetchall()
    return {
        "live_jobs": [dict(row) for row in live],
        "document_models": [dict(row) for row in models],
    }


def _scan(connection: Any, snapshot_id: int) -> dict[str, Any] | None:
    scan = connection.execute(
        """SELECT status, discovered_count, analyzed_count, reused_count, error_count,
                  started_at, completed_at
           FROM analysis_runs WHERE snapshot_id = ? AND run_type = 'scan'
           ORDER BY id DESC LIMIT 1""",
        (snapshot_id,),
    ).fetchone()
    return dict(scan) if scan else None


def _failures(connection: Any, snapshot_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT job_kind, scope_type, scope_key, substr(error, 1, 1000) AS error
           FROM semantic_jobs WHERE snapshot_id = ? AND status = 'failed'
           ORDER BY id DESC LIMIT 20""",
        (snapshot_id,),
    ).fetchall()
    return [dict(row) for row in rows]
