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
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION, SemanticResult, create_semantic_provider
from anaxigraph.semantic_graph import SupersededSemanticJob, _source_chunks
from anaxigraph.semantic_requests import _compact_dossier


class SemanticRunnerMixin:
    def run_jobs(
        self,
        repository_id: int,
        repository: str | Path,
        config: AnaxiGraphConfig,
        *,
        limit: int | None = None,
    ) -> dict[str, Any]:
        semantic = config.semantic
        if not semantic.enabled:
            raise ValueError("Semantic analysis is disabled in .anaxigraph.yml")
        if semantic.provider == "agent":
            raise ValueError(
                "Agent-funded semantic jobs are executed through AnaxiMCP, not the local "
                "semantic worker"
            )
        # Validate provider configuration before claiming a job.
        create_semantic_provider(semantic)
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
                        lambda _: self._work_one(repository_id, root, config),
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
    ) -> dict[str, Any]:
        semantic = config.semantic
        if semantic.provider == "agent":
            # In agent-funded mode the server owns planning and persistence while the connected
            # coding agent owns inference. Dashboard/scan refreshes therefore prepare work only.
            plan_only = True
        bounded = max(1, limit if limit is not None else semantic.max_jobs_per_run)
        remaining = bounded
        total = {"planned": 0, "processed": 0, "completed": 0, "failed": 0, "retry": 0}
        stages = []
        first = True
        for _ in range(8):
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
            if plan_only or plan.active_jobs == 0 or remaining <= 0:
                break
            run = self.run_jobs(
                repository_id,
                repository,
                config,
                limit=min(remaining, plan.active_jobs),
            )
            for key in ("processed", "completed", "failed", "retry"):
                total[key] += int(run[key])
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
    ) -> str | None:
        job = self._claim_job(repository_id, config.semantic)
        if job is None:
            return None
        try:
            with self._job_lease(job, config.semantic):
                request = self._job_request(job, root, config.semantic)
                provider = create_semantic_provider(config.semantic)
                result = self._analyze_request(provider, request, config.semantic)
                self._complete_job(job, result, provider.name, config.semantic)
            return "completed"
        except SupersededSemanticJob as exc:
            self._mark_superseded(int(job["id"]), str(exc))
            return "superseded"
        except Exception as exc:
            retry = self._fail_job(job, exc)
            return "retry" if retry else "failed"

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

    def _analyze_request(
        self,
        provider: Any,
        request: dict[str, Any],
        semantic: SemanticConfig,
    ) -> SemanticResult:
        if request["analysis_kind"] == "synthesis":
            return self._analyze_synthesis(provider, request, semantic)
        source = str(request.get("source") or "")
        if request["analysis_kind"] != "intrinsic" or len(source) <= semantic.max_source_chars:
            return provider.analyze(request)

        symbols = request.get("deterministic_facts", {}).get("symbols") or []
        chunks = _source_chunks(source, symbols, semantic.max_source_chars)
        partials = []
        input_tokens = output_tokens = 0
        for index, (start, end, content) in enumerate(chunks, start=1):
            partial = dict(request)
            partial["analysis_kind"] = "intrinsic_chunk"
            partial["chunk"] = {
                "index": index,
                "total": len(chunks),
                "start_line": start,
                "end_line": end,
            }
            partial["source"] = content
            result = provider.analyze(partial)
            partials.append(result.value)
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
        synthesis = {
            "contract": request["contract"],
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "analysis_kind": "intrinsic_synthesis",
            "path": request.get("path"),
            "language": request.get("language"),
            "deterministic_facts": request.get("deterministic_facts"),
            "chunk_dossiers": partials,
        }
        result = provider.analyze(synthesis)
        return SemanticResult(
            value=result.value,
            confidence=result.confidence,
            evidence=result.evidence,
            input_tokens=input_tokens + result.input_tokens,
            output_tokens=output_tokens + result.output_tokens,
        )

    def _analyze_synthesis(
        self,
        provider: Any,
        request: dict[str, Any],
        semantic: SemanticConfig,
    ) -> SemanticResult:
        children = list(request.get("child_dossiers") or [])
        if len(json.dumps(request, default=str)) <= semantic.max_source_chars or len(children) < 2:
            return provider.analyze(request)

        base = {key: value for key, value in request.items() if key != "child_dossiers"}
        batches = _payload_batches(children, semantic.max_source_chars, base)
        partials, input_tokens, output_tokens = _run_synthesis_chunks(provider, base, batches)
        reduction_width = max(2, min(20, semantic.max_context_modules))
        partials, reduction_input, reduction_output = _reduce_synthesis_partials(
            provider, base, partials, reduction_width
        )

        final_request = {**base, "analysis_kind": "synthesis", "child_dossiers": partials}
        result = provider.analyze(final_request)
        return SemanticResult(
            value=result.value,
            confidence=result.confidence,
            evidence=result.evidence,
            input_tokens=input_tokens + reduction_input + result.input_tokens,
            output_tokens=output_tokens + reduction_output + result.output_tokens,
        )

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


def _payload_batches(
    children: list[dict[str, Any]], max_chars: int, base: dict[str, Any]
) -> list[list[dict[str, Any]]]:
    overhead = len(json.dumps(base, default=str)) + 500
    budget = max(1_000, max_chars - overhead)
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for child in children:
        child_size = len(json.dumps(child, default=str)) + 1
        if current and size + child_size > budget:
            batches.append(current)
            current = []
            size = 0
        current.append(child)
        size += child_size
    if current:
        batches.append(current)
    return batches


def _run_synthesis_chunks(
    provider: Any, base: dict[str, Any], batches: list[list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], int, int]:
    partials = []
    input_tokens = output_tokens = 0
    for index, batch in enumerate(batches, start=1):
        request = {
            **base,
            "analysis_kind": "synthesis_chunk",
            "chunk": {"index": index, "total": len(batches)},
            "child_dossiers": batch,
        }
        result = provider.analyze(request)
        partials.append(_partial_dossier(index, result))
        input_tokens += result.input_tokens
        output_tokens += result.output_tokens
    return partials, input_tokens, output_tokens


def _reduce_synthesis_partials(
    provider: Any,
    base: dict[str, Any],
    partials: list[dict[str, Any]],
    width: int,
) -> tuple[list[dict[str, Any]], int, int]:
    input_tokens = output_tokens = 0
    level = 1
    while len(partials) > width:
        groups = [partials[index : index + width] for index in range(0, len(partials), width)]
        reduced = []
        for index, batch in enumerate(groups, start=1):
            request = {
                **base,
                "analysis_kind": "synthesis_reduction",
                "reduction": {"level": level, "index": index, "total": len(groups)},
                "child_dossiers": batch,
            }
            result = provider.analyze(request)
            reduced.append(_partial_dossier(index, result))
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
        partials = reduced
        level += 1
    return partials, input_tokens, output_tokens


def _partial_dossier(index: int, result: SemanticResult) -> dict[str, Any]:
    return {
        "scope": f"semantic-chunk-{index}",
        "kind": "synthesis",
        "confidence": result.confidence,
        "value": _compact_dossier(result.value),
    }
