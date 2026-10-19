"""Keep saved workflow work visible when its source evidence needs refreshing."""

from __future__ import annotations

import json
from typing import Any


def workflow_history(connection: Any, snapshot_id: int) -> dict[str, Any]:
    snapshot = connection.execute(
        "SELECT repository_id, commit_sha FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    modules = _module_history(connection, snapshot_id)
    if not sum(modules["intrinsic"].values()):
        modules.update(_pending_history(connection, snapshot["repository_id"], snapshot_id))
    return {
        "commit_sha": snapshot["commit_sha"],
        "modules": modules,
        "taxonomy": _taxonomy_history(connection, snapshot["repository_id"], snapshot_id),
    }


def _module_history(connection: Any, snapshot_id: int) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT ss.scope_key, ss.status,
          ss.intrinsic_document_id IS NOT NULL AND ss.status NOT IN
            ('pending_intrinsic', 'failed_intrinsic') AS intrinsic_current,
          EXISTS(SELECT 1 FROM semantic_documents d WHERE d.repository_id = ss.repository_id
            AND d.scope_type = 'module' AND d.scope_key = ss.scope_key
            AND d.document_kind = 'intrinsic' AND d.snapshot_id <= ss.snapshot_id) AS intrinsic_saved,
          EXISTS(SELECT 1 FROM semantic_documents d WHERE d.repository_id = ss.repository_id
            AND d.scope_type = 'module' AND d.scope_key = ss.scope_key
            AND d.document_kind = 'context' AND d.snapshot_id <= ss.snapshot_id) AS context_saved
        FROM semantic_scope_states ss
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module' AND ss.status != 'excluded'
        ORDER BY ss.scope_key
        """,
        (snapshot_id,),
    ).fetchall()
    result: dict[str, Any] = {
        "intrinsic": {"current": 0, "refresh": 0, "new": 0},
        "context": {"current": 0, "refresh": 0, "new": 0},
        "affected": [],
    }
    for row in rows:
        changes = {}
        for stage, current in (
            ("intrinsic", row["intrinsic_current"]),
            ("context", row["status"] == "current"),
        ):
            state = "current" if current else "refresh" if row[f"{stage}_saved"] else "new"
            result[stage][state] += 1
            changes[stage] = state
        if any(state != "current" for state in changes.values()):
            result["affected"].append({"path": row["scope_key"], **changes})
    result["affected_count"] = len(result["affected"])
    result["affected"] = result["affected"][:100]
    return result


def _pending_history(connection: Any, repository_id: int, snapshot_id: int) -> dict[str, Any]:
    prior = connection.execute(
        """SELECT MAX(snapshot_id) FROM semantic_scope_states WHERE repository_id = ?
           AND snapshot_id < ? AND scope_type = 'module' AND intrinsic_document_id IS NOT NULL
           AND NOT EXISTS(SELECT 1 FROM semantic_scope_states current
             WHERE current.snapshot_id = ? AND current.scope_type = 'module')""",
        (repository_id, snapshot_id, snapshot_id),
    ).fetchone()[0]
    if prior is None:
        return {}
    previous = _module_history(connection, prior)
    return {
        "reuse_pending": True,
        "previous_snapshot_id": prior,
        "saved": {
            stage: previous[stage]["current"] + previous[stage]["refresh"]
            for stage in ("intrinsic", "context")
        },
    }


def _taxonomy_history(connection: Any, repository_id: int, snapshot_id: int) -> Any:
    row = connection.execute(
        """
        SELECT t.id, t.snapshot_id, t.status, t.created_at, s.commit_sha,
          COALESCE(NULLIF(t.executor_model, ''), t.model) AS proposal_model,
          (SELECT COUNT(*) FROM semantic_taxonomy_reviews r
            WHERE r.taxonomy_id = t.id) AS reviews
        FROM semantic_taxonomies t JOIN snapshots s ON s.id = t.snapshot_id
        WHERE t.repository_id = ? AND t.snapshot_id < ? AND t.candidate_document_id IS NOT NULL
        ORDER BY t.snapshot_id DESC, t.id DESC LIMIT 1
        """,
        (repository_id, snapshot_id),
    ).fetchone()
    if row is None:
        return None
    value = dict(row)
    jobs = connection.execute(
        """SELECT executor_model, status, error, metadata_json FROM semantic_jobs
           WHERE snapshot_id = ? AND job_kind = 'taxonomy_review' ORDER BY id""",
        (row["snapshot_id"],),
    ).fetchall()
    value["required_reviews"] = max(
        (
            json.loads(job["metadata_json"]).get("taxonomy_settings", {}).get("review_passes", 0)
            for job in jobs
        ),
        default=row["reviews"],
    )
    value["failed_reviews"] = sum(job["status"] == "failed" for job in jobs)
    value["review_models"] = sorted(
        {job["executor_model"] for job in jobs if job["executor_model"]}
    )
    value["error"] = next(
        (job["error"] for job in reversed(jobs) if job["status"] == "failed"), None
    )
    return value
