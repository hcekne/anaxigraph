"""Semantic queue execution, concurrency, budgets, and worker leases."""

from __future__ import annotations

import contextlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from anaxigraph.clock import utc_now
from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.semantic import create_semantic_provider
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_request_analysis import analyze_semantic_request


class SemanticRunnerMixin:
    def run_jobs(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        limit: int | None = None,
        execution_semantic: SemanticConfig | None = None,
    ) -> dict[str, Any]:
        semantic = config.semantic
        if not semantic.enabled:
            raise ValueError("Semantic analysis is disabled in .anaxigraph.yml")
        if semantic.provider == "agent" and execution_semantic is None:
            raise ValueError(
                "Agent-funded semantic jobs are executed through AnaxiMCP, not the local "
                "semantic worker; pass a local agent executor or use the MCP work loop"
            )
        if execution_semantic is not None and semantic.provider != "agent":
            raise ValueError("A local agent executor can only bridge semantic.provider=agent")
        # Validate provider configuration before claiming a job.
        create_semantic_provider(execution_semantic or semantic)
        bounded = max(1, limit if limit is not None else semantic.max_jobs_per_run)
        workers = min(semantic.max_parallel_jobs, bounded)
        completed = failed = retried = superseded = 0
        processed = 0
        root = Path(repository).expanduser().resolve()
        while processed < bounded:
            wave = min(workers, bounded - processed)
            with ThreadPoolExecutor(max_workers=wave) as executor:
                results = list(
                    executor.map(
                        lambda _: self._work_one(
                            repository_id,
                            root,
                            config,
                            execution_semantic=execution_semantic,
                        ),
                        range(wave),
                    )
                )
            active = [result for result in results if result is not None]
            if not active:
                break
            processed += len(active)
            for result in active:
                completed += int(result == "completed")
                failed += int(result == "failed")
                retried += int(result == "retry")
                superseded += int(result == "superseded")
        return {
            "processed": processed,
            "completed": completed,
            "failed": failed,
            "retry": retried,
            "superseded": superseded,
            "semantic": self.status(repository_id, semantic),
        }

    def bootstrap(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        limit: int | None = None,
        force: bool = False,
        retry_failed: bool = False,
        plan_only: bool = False,
        execution_semantic: SemanticConfig | None = None,
        until_complete: bool = False,
    ) -> dict[str, Any]:
        semantic = config.semantic
        if semantic.provider == "agent" and execution_semantic is None:
            # In agent-funded mode the server owns planning and persistence while the connected
            # coding agent owns inference. Dashboard/scan refreshes therefore prepare work only.
            plan_only = True
        if execution_semantic is not None and semantic.provider != "agent":
            raise ValueError("A local agent executor can only bridge semantic.provider=agent")
        bounded = max(1, limit if limit is not None else semantic.max_jobs_per_run)
        remaining = None if until_complete else bounded
        total = {"planned": 0, "processed": 0, "completed": 0, "failed": 0, "retry": 0}
        stages = []
        first = True
        for _ in range(10 + semantic.taxonomy.review_passes):
            plan = self.plan(
                repository_id,
                repository,
                config,
                force=force and first,
                retry_failed=retry_failed,
            )
            first = False
            total["planned"] += plan.enqueued
            stages.append(plan.stage)
            if plan_only or plan.active_jobs == 0 or (remaining is not None and remaining <= 0):
                break
            run_limit = plan.active_jobs if remaining is None else min(remaining, plan.active_jobs)
            run = self.run_jobs(
                repository_id,
                repository,
                config,
                limit=run_limit,
                execution_semantic=execution_semantic,
            )
            for key in ("processed", "completed", "failed", "retry"):
                total[key] += int(run[key])
            if remaining is not None:
                remaining -= int(run["processed"])
            if run["processed"] == 0:
                break
        total["stages"] = list(dict.fromkeys(stages))
        total["semantic"] = self.status(repository_id, semantic)
        return total

    def _work_one(
        self,
        repository_id: int,
        root: Path,
        config: AnaxiGraphConfig,
        *,
        execution_semantic: SemanticConfig | None = None,
    ) -> str | None:
        runtime_semantic = execution_semantic or config.semantic
        job = self._claim_job(
            repository_id,
            config.semantic,
            executor_id=(f"cli:{runtime_semantic.provider}" if execution_semantic else None),
            executor_model=(runtime_semantic.model or None) if execution_semantic else None,
        )
        if job is None:
            return None
        try:
            with self._job_lease(job, config.semantic):
                request = self._job_request(job, root, config.semantic)
                provider = create_semantic_provider(runtime_semantic)
                result = self._analyze_request(provider, request, runtime_semantic)
                recorded_provider = (
                    config.semantic.provider if execution_semantic else provider.name
                )
                self._complete_job(job, result, recorded_provider, config.semantic)
            return "completed"
        except SupersededSemanticJob as exc:
            self._mark_superseded(int(job["id"]), str(exc))
            return "superseded"
        except Exception as exc:
            retry = self._fail_job(job, exc)
            return "retry" if retry else "failed"

    def _analyze_request(
        self,
        provider: Any,
        request: dict[str, Any],
        semantic: SemanticConfig,
    ) -> Any:
        """Compatibility shim for callers testing provider-side request reduction."""

        return analyze_semantic_request(provider, request, semantic)

    @contextlib.contextmanager
    def _job_lease(self, job: dict[str, Any], semantic: SemanticConfig):
        stopped = threading.Event()
        lease_seconds = max(90, semantic.timeout_seconds + 60)

        def heartbeat() -> None:
            while not stopped.wait(min(30, max(10, lease_seconds // 3))):
                expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
                with self.database.connect() as connection:
                    connection.execute(
                        """
                        UPDATE semantic_jobs SET lease_expires_at = ?
                        WHERE id = ? AND status = 'running' AND worker_id = ?
                        """,
                        (expires, job["id"], job["worker_id"]),
                    )

        thread = threading.Thread(
            target=heartbeat,
            name=f"anaxigraph-semantic-lease-{job['id']}",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=1)

    def _claim_job(
        self,
        repository_id: int,
        semantic: SemanticConfig,
        *,
        worker_id: str | None = None,
        lease_seconds: int | None = None,
        lease_token_hash: str | None = None,
        executor_id: str | None = None,
        executor_model: str | None = None,
    ) -> dict[str, Any] | None:
        with self.database.transaction() as connection:
            repository = connection.execute(
                "SELECT current_snapshot_id FROM repositories WHERE id = ?", (repository_id,)
            ).fetchone()
            if repository is None or repository["current_snapshot_id"] is None:
                return None
            now = utc_now()
            active_workers = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM semantic_jobs
                    WHERE repository_id = ? AND status = 'running'
                      AND lease_expires_at IS NOT NULL AND lease_expires_at >= ?
                    """,
                    (repository_id, now),
                ).fetchone()[0]
            )
            if active_workers >= semantic.max_parallel_jobs:
                return None
            spent = 0.0
            if semantic.daily_budget_usd is not None:
                today = datetime.now(UTC).date().isoformat()
                spent = float(
                    connection.execute(
                        """
                        SELECT COALESCE(SUM(
                            CASE WHEN status = 'running'
                                 THEN COALESCE(estimated_cost_usd, 0)
                                 ELSE COALESCE(actual_cost_usd, estimated_cost_usd, 0)
                            END
                        ), 0)
                        FROM semantic_jobs WHERE repository_id = ? AND (
                            status = 'running'
                            OR (status = 'completed' AND substr(completed_at, 1, 10) = ?)
                        )
                        """,
                        (repository_id, today),
                    ).fetchone()[0]
                )
            row = connection.execute(
                """
                SELECT * FROM semantic_jobs
                WHERE repository_id = ? AND snapshot_id = ?
                  AND status IN ('pending', 'retry') AND available_at <= ?
                ORDER BY priority DESC, id LIMIT 1
                """,
                (repository_id, int(repository["current_snapshot_id"]), now),
            ).fetchone()
            if row is None:
                return None
            if (
                semantic.daily_budget_usd is not None
                and spent + float(row["estimated_cost_usd"] or 0) > semantic.daily_budget_usd
            ):
                return None
            selected_worker_id = worker_id or (
                f"{os.getpid()}:{threading.get_ident()}:{int(row['id'])}"
            )
            selected_lease_seconds = lease_seconds or max(90, semantic.timeout_seconds + 60)
            lease_expires = (
                datetime.now(UTC) + timedelta(seconds=selected_lease_seconds)
            ).isoformat()
            connection.execute(
                """
                UPDATE semantic_jobs SET status = 'running', attempts = attempts + 1,
                    started_at = ?, worker_id = ?, lease_expires_at = ?, error = NULL,
                    lease_token_hash = ?, executor_id = ?, executor_model = ?
                WHERE id = ?
                """,
                (
                    now,
                    selected_worker_id,
                    lease_expires,
                    lease_token_hash,
                    executor_id,
                    executor_model,
                    int(row["id"]),
                ),
            )
            result = dict(row)
            result["attempts"] = int(result["attempts"]) + 1
            result["worker_id"] = selected_worker_id
            result["lease_expires_at"] = lease_expires
            result["lease_token_hash"] = lease_token_hash
            result["executor_id"] = executor_id
            result["executor_model"] = executor_model
            result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
            return result
