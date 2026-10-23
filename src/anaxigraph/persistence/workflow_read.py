"""Snapshot coverage for the interactive workflow view, including reused documents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from anaxigraph.persistence.workflow_history import workflow_history
from anaxigraph.semantic_timeouts import readable_failure


def workflow_coverage(connection: Any, snapshot_id: int) -> dict[str, Any]:
    return {
        "graph": _graph_coverage(connection, snapshot_id),
        "scopes": _scopes(connection, snapshot_id),
        **_execution(connection, snapshot_id),
        "scan": _scan(connection, snapshot_id),
        "failures": _failures(connection, snapshot_id),
        "workers": _workers(connection, snapshot_id),
        "history": workflow_history(connection, snapshot_id),
        "taxonomy_review": _taxonomy_review(connection, snapshot_id),
    }


def _graph_coverage(connection: Any, snapshot_id: int) -> dict[str, Any]:
    kinds = dict(
        connection.execute(
            "SELECT kind,COUNT(*) FROM graph_entities WHERE snapshot_id=? GROUP BY kind",
            (snapshot_id,),
        ).fetchall()
    )
    annotations = connection.execute(
        """SELECT COUNT(*),COALESCE(SUM(status='current'),0) FROM semantic_scope_states
        WHERE snapshot_id=? AND scope_type='module' AND status!='excluded'""",
        (snapshot_id,),
    ).fetchone()
    brief = connection.execute(
        "SELECT 1 FROM semantic_scope_states WHERE snapshot_id=? AND scope_type='repository' "
        "AND status='current' LIMIT 1",
        (snapshot_id,),
    ).fetchone()
    return {
        "module_count": kinds.get("module", 0),
        "function_count": kinds.get("function", 0),
        "interface_count": kinds.get("interface", 0),
        "contract_count": kinds.get("contract", 0),
        "annotation_total": annotations[0],
        "annotation_current": annotations[1],
        "contracts_ready": annotations[0] > 0 and annotations[0] == annotations[1],
        "functional_brief_ready": bool(brief),
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
        LEFT JOIN semantic_document_values i ON i.id = ss.intrinsic_document_id
        LEFT JOIN semantic_document_values c ON c.id = ss.context_document_id
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
        FROM semantic_scope_states ss JOIN semantic_document_values d
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
        """SELECT job_kind, scope_type, scope_key, status, executor_id, executor_model,
                  available_at, error
           FROM semantic_jobs WHERE snapshot_id = ? AND status IN ('retry', 'failed')
           AND error IS NOT NULL AND error != ''
           ORDER BY id DESC LIMIT 20""",
        (snapshot_id,),
    ).fetchall()
    return [{**dict(row), "error": readable_failure(row["error"])} for row in rows]


def _workers(connection: Any, snapshot_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT job_kind, scope_type, executor_id, executor_model, COUNT(*) AS running
           FROM semantic_jobs WHERE snapshot_id = ? AND status = 'running'
           AND lease_expires_at >= ?
           GROUP BY job_kind, scope_type, executor_id, executor_model""",
        (snapshot_id, datetime.now(UTC).isoformat()),
    ).fetchall()
    return [dict(row) for row in rows]


def _taxonomy_review(connection: Any, snapshot_id: int) -> dict[str, Any]:
    rows = connection.execute(
        """SELECT json_extract(j.metadata_json, '$.review_pass') AS pass,
           json_extract(j.metadata_json, '$.review_phase') AS phase,
           json_extract(j.metadata_json, '$.taxonomy_settings.review_passes') AS required,
           COUNT(*) AS total, SUM(j.status = 'completed') AS completed,
           SUM(j.status = 'running' AND j.lease_expires_at >= ?) AS running,
           SUM(j.status = 'failed') AS failed, MIN(j.started_at) AS started,
           MAX(j.completed_at) AS finished
           FROM semantic_jobs j WHERE j.snapshot_id = ? AND j.job_kind = 'taxonomy_review'
           AND j.status != 'superseded' AND json_extract(j.metadata_json, '$.taxonomy_input_hash') =
             (SELECT input_hash FROM semantic_taxonomy_values WHERE snapshot_id = ? ORDER BY id DESC LIMIT 1)
           GROUP BY pass, phase ORDER BY pass, phase""",
        (datetime.now(UTC).isoformat(), snapshot_id, snapshot_id),
    ).fetchall()
    passes: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row["pass"] is None:
            continue
        index = int(row["pass"])
        value = passes.setdefault(
            index,
            {
                "pass": index,
                "completed_batches": 0,
                "total_batches": 0,
                "active_workers": 0,
                "elapsed_seconds": 0,
                "reconciliation": "not_started",
                "final": False,
            },
        )
        _review_progress_row(value, row)
    for value in passes.values():
        _review_elapsed(value)
    return {"passes": list(passes.values())}


def _review_progress_row(value: dict[str, Any], row: Any) -> None:
    value["active_workers"] += int(row["running"] or 0)
    value["final"] = value["final"] or value["pass"] == row["required"]
    if row["phase"] == "batch":
        value["completed_batches"] = int(row["completed"] or 0)
        value["total_batches"] = int(row["total"])
    else:
        value["reconciliation"] = (
            "complete"
            if row["completed"] == row["total"]
            else "running"
            if row["running"]
            else "failed"
            if row["failed"]
            else "queued"
        )
    if row["started"]:
        value["started_at"] = min(value.get("started_at", row["started"]), row["started"])
    if row["finished"]:
        value["finished_at"] = max(value.get("finished_at", row["finished"]), row["finished"])


def _review_elapsed(value: dict[str, Any]) -> None:
    start, finish = value.pop("started_at", None), value.pop("finished_at", None)
    if start:
        end = (
            datetime.fromisoformat(finish)
            if value["reconciliation"] == "complete" and finish
            else datetime.now(UTC)
        )
        value["elapsed_seconds"] = max(
            0, int((end - datetime.fromisoformat(start)).total_seconds())
        )
