"""Semantic coverage, budget, and dossier reporting."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_records import _document_by_id

_TERMINAL_FAILURES = (
    "failed_intrinsic",
    "failed_context",
    "failed_synthesis",
    "failed_taxonomy",
)


class SemanticReportingMixin:
    def status(self, repository_id: int, semantic: SemanticConfig | None = None) -> dict[str, Any]:
        snapshot = self.database.latest_snapshot(repository_id)
        configured = bool(semantic and semantic.enabled)
        if snapshot is None:
            return {
                "enabled": configured,
                "state": "not_indexed",
                "semantically_ready": False,
                "baseline_complete": False,
            }
        snapshot_id = int(snapshot["id"])
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count FROM semantic_scope_states
                WHERE snapshot_id = ? AND scope_type = 'module' GROUP BY status
                """,
                (snapshot_id,),
            ).fetchall()
            counts = {str(row["status"]): int(row["count"]) for row in rows}
            scope_rows = connection.execute(
                """
                SELECT scope_type, status, COUNT(*) AS count FROM semantic_scope_states
                WHERE snapshot_id = ? GROUP BY scope_type, status
                """,
                (snapshot_id,),
            ).fetchall()
            scope_counts: dict[str, dict[str, int]] = {}
            for row in scope_rows:
                scope_counts.setdefault(str(row["scope_type"]), {})[str(row["status"])] = int(
                    row["count"]
                )
            job_rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count FROM semantic_jobs
                WHERE repository_id = ? AND snapshot_id = ? GROUP BY status
                """,
                (repository_id, snapshot_id),
            ).fetchall()
            jobs = {str(row["status"]): int(row["count"]) for row in job_rows}
            usage = connection.execute(
                """
                SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd, 0)), 0) AS cost
                FROM semantic_jobs WHERE repository_id = ? AND status = 'completed'
                """,
                (repository_id,),
            ).fetchone()
            today = datetime.now(UTC).date().isoformat()
            daily_spend = float(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd, 0)), 0)
                    FROM semantic_jobs WHERE repository_id = ? AND status = 'completed'
                      AND substr(completed_at, 1, 10) = ?
                    """,
                    (repository_id, today),
                ).fetchone()[0]
            )
            reserved_spend = float(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(estimated_cost_usd, 0)), 0)
                    FROM semantic_jobs WHERE repository_id = ? AND status = 'running'
                    """,
                    (repository_id,),
                ).fetchone()[0]
            )
            next_job = connection.execute(
                """
                SELECT COALESCE(estimated_cost_usd, 0) AS estimated_cost_usd
                FROM semantic_jobs WHERE repository_id = ? AND snapshot_id = ?
                  AND status IN ('pending', 'retry')
                ORDER BY priority DESC, id LIMIT 1
                """,
                (repository_id, snapshot_id),
            ).fetchone()
            next_estimated_cost = float(next_job["estimated_cost_usd"] if next_job else 0)
            last_checked = connection.execute(
                "SELECT MAX(last_checked_at) FROM semantic_scope_states WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()[0]
            repository_state = connection.execute(
                """
                SELECT ss.status, sd.value_json, sd.confidence, sd.provider, sd.model,
                       sd.executor_id, sd.executor_model, sd.prompt_version, sd.created_at
                FROM semantic_scope_states ss
                LEFT JOIN semantic_documents sd ON sd.id = ss.context_document_id
                WHERE ss.snapshot_id = ? AND ss.scope_type = 'repository'
                """,
                (snapshot_id,),
            ).fetchone()
            taxonomy_row = connection.execute(
                """
                SELECT st.*,
                       (SELECT COUNT(*) FROM semantic_taxonomy_reviews str
                        WHERE str.taxonomy_id = st.id) AS stored_reviews
                FROM semantic_taxonomies st WHERE st.snapshot_id = ?
                ORDER BY CASE st.status WHEN 'current' THEN 0 ELSE 1 END, st.id DESC LIMIT 1
                """,
                (snapshot_id,),
            ).fetchone()
        excluded = counts.get("excluded", 0)
        total = sum(counts.values())
        eligible = max(0, total - excluded)
        current = counts.get("current", 0)
        failed = sum(counts.get(key, 0) for key in _TERMINAL_FAILURES)
        pending = sum(
            count
            for key, count in counts.items()
            if key.startswith("pending_") or key == "intrinsic_current"
        )
        non_module_counts = {
            scope_type: values
            for scope_type, values in scope_counts.items()
            if scope_type != "module"
        }
        pending_scopes = sum(
            count
            for values in non_module_counts.values()
            for key, count in values.items()
            if key.startswith("pending_") or key == "intrinsic_current"
        )
        failed_scopes = sum(
            count
            for values in non_module_counts.values()
            for key, count in values.items()
            if key in _TERMINAL_FAILURES
        )
        repository_ready = bool(repository_state and repository_state["status"] == "current")
        taxonomy_enabled = bool(semantic and semantic.enabled and semantic.taxonomy.enabled)
        taxonomy_ready = bool(taxonomy_row and taxonomy_row["status"] == "current")
        baseline_complete = total > 0 and pending == 0 and pending_scopes == 0
        semantically_ready = (
            eligible > 0
            and current == eligible
            and failed == 0
            and failed_scopes == 0
            and repository_ready
            and (taxonomy_ready or not taxonomy_enabled)
        )
        repository_document = None
        if repository_state and repository_state["value_json"]:
            repository_document = {
                "status": repository_state["status"],
                "value": json.loads(repository_state["value_json"]),
                "confidence": repository_state["confidence"],
                "provider": repository_state["provider"],
                "model": repository_state["model"],
                "executor_id": repository_state["executor_id"],
                "executor_model": repository_state["executor_model"],
                "prompt_version": repository_state["prompt_version"],
                "created_at": repository_state["created_at"],
            }
        taxonomy_document = None
        if taxonomy_row:
            taxonomy_document = {
                "id": taxonomy_row["id"],
                "status": taxonomy_row["status"],
                "confidence": taxonomy_row["confidence"],
                "provider": taxonomy_row["provider"],
                "model": taxonomy_row["model"],
                "executor_id": taxonomy_row["executor_id"],
                "executor_model": taxonomy_row["executor_model"],
                "prompt_version": taxonomy_row["prompt_version"],
                "review_passes": taxonomy_row["review_passes"],
                "stored_reviews": taxonomy_row["stored_reviews"],
                "validation": json.loads(taxonomy_row["validation_json"] or "{}"),
                "facets": json.loads(taxonomy_row["facets_json"] or "[]"),
                "changes": json.loads(taxonomy_row["change_json"] or "[]"),
                "created_at": taxonomy_row["created_at"],
                "updated_at": taxonomy_row["updated_at"],
            }
        return {
            "enabled": configured,
            "provider": semantic.provider if semantic else None,
            "model": semantic.model if semantic else None,
            "execution_mode": (
                "coding_agent" if semantic and semantic.provider == "agent" else "worker"
            ),
            "refresh": semantic.refresh if semantic else None,
            "snapshot_id": snapshot_id,
            "state": (
                "ready"
                if semantically_ready
                else "complete_with_failures"
                if baseline_complete
                else "pending"
                if total
                else "not_started"
            ),
            "semantically_ready": semantically_ready,
            "baseline_complete": baseline_complete,
            "total_modules": total,
            "eligible_modules": eligible,
            "current": current,
            "intrinsic_current": counts.get("intrinsic_current", 0),
            "pending": pending,
            "failed": failed,
            "failed_scopes": failed_scopes,
            "excluded": excluded,
            "coverage": current / eligible if eligible else None,
            "counts": counts,
            "scope_counts": scope_counts,
            "pending_scopes": pending_scopes,
            "jobs": jobs,
            "last_reconciled_at": last_checked,
            "usage": {
                "input_tokens": int(usage["input_tokens"]),
                "output_tokens": int(usage["output_tokens"]),
                "cost_usd": round(float(usage["cost"]), 6),
            },
            "budget": {
                "daily_limit_usd": semantic.daily_budget_usd if semantic else None,
                "spent_today_usd": round(daily_spend, 6),
                "reserved_running_usd": round(reserved_spend, 6),
                "remaining_today_usd": (
                    round(max(0.0, semantic.daily_budget_usd - daily_spend - reserved_spend), 6)
                    if semantic and semantic.daily_budget_usd is not None
                    else None
                ),
                "next_job_estimated_usd": round(next_estimated_cost, 6),
                "paused": bool(
                    semantic
                    and semantic.daily_budget_usd is not None
                    and daily_spend + reserved_spend + next_estimated_cost
                    > semantic.daily_budget_usd
                    and (pending > 0 or pending_scopes > 0)
                ),
            },
            "repository_dossier": repository_document,
            "taxonomy": {
                "enabled": taxonomy_enabled,
                "ready": taxonomy_ready,
                "required_review_passes": (
                    semantic.taxonomy.review_passes if semantic and taxonomy_enabled else 0
                ),
                "current": taxonomy_document,
            },
        }

    def dossier(
        self, repository_id: int, path: str, snapshot_id: int | None = None
    ) -> dict[str, Any] | None:
        snapshot = (
            self.database.latest_snapshot(repository_id)
            if snapshot_id is None
            else self.database._resolve_snapshot(repository_id, snapshot_id)
        )
        if snapshot is None:
            return None
        with self.database.connect() as connection:
            state = connection.execute(
                """
                SELECT * FROM semantic_scope_states
                WHERE snapshot_id = ? AND scope_type = 'module' AND scope_key = ?
                """,
                (int(snapshot["id"]), path),
            ).fetchone()
            if state is None:
                return None
            result = dict(state)
            for key, label in (
                ("intrinsic_document_id", "intrinsic"),
                ("context_document_id", "context"),
            ):
                document_id = result.get(key)
                result[label] = (
                    _document_by_id(connection, int(document_id)) if document_id else None
                )
            return result
