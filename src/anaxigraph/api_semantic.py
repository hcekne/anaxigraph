"""Background semantic-refresh coordination for the REST application."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anaxigraph.config import load_config
from anaxigraph.registry import RepositoryTarget
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_settings import required_steps


class SemanticRefreshCoordinator:
    def __init__(self, database: AnaxiIndex) -> None:
        self.database = database
        self.jobs: dict[tuple, dict[str, Any]] = {}
        self.threads: dict[tuple, threading.Thread] = {}
        self.lock = threading.Lock()
        self.step_locks: dict[tuple, Any] = {}

    def start(
        self,
        target: RepositoryTarget,
        *,
        force: bool = False,
        retry_failed: bool = False,
        run: Callable[[], dict[str, Any]] | None = None,
        workflow: str = "mapping",
        step: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> bool:
        key = (str(target.path.resolve()), workflow, step)
        config = load_config(target.path, target.config_path)
        if not config.semantic.enabled:
            return False
        if settings is None and self._durable_workers_running(target, config):
            return False
        with self.lock:
            active = self._active_runs(key[0])
            if any(
                item["workflow"] == workflow
                and item["step"] == step
                or settings is None
                or item.get("settings") is None
                for item in active
            ):
                return False
            self.jobs[key] = {
                "status": "queued",
                "workflow": workflow,
                "step": step,
                "settings": settings,
                "steps": required_steps(workflow, step) if settings is not None else [],
                "phase": "preparing",
                "message": "Checking saved results and preparing pending jobs.",
                "started_at": time.time(),
            }
        thread = threading.Thread(
            target=self._worker,
            args=(key, target, force, retry_failed, run),
            name=f"anaxigraph-semantic-{target.key}",
            daemon=True,
        )
        with self.lock:
            self.threads[key] = thread
        thread.start()
        return True

    def _durable_workers_running(self, target: RepositoryTarget, config: Any) -> bool:
        repository = self.database.repository(target.path)
        if repository is None:
            return False
        durable = SemanticEngine(self.database).status(int(repository["id"]), config.semantic)
        jobs = durable.get("jobs", {})
        return int(jobs.get("running_live", jobs.get("running", 0))) > 0

    def status_for(self, path: Path) -> dict[str, Any]:
        with self.lock:
            runs = [dict(job) for key, job in self.jobs.items() if key[0] == str(path.resolve())]
        if not runs:
            return {"status": "idle", "runs": []}
        active = [job for job in runs if job["status"] in {"queued", "running"}]
        primary = max(active or runs, key=lambda job: job["started_at"])
        return {**primary, "runs": runs, "active_count": len(active)}

    def _active_runs(self, path: str) -> list[dict[str, Any]]:
        return [
            job
            for key, job in self.jobs.items()
            if key[0] == path and job["status"] in {"queued", "running"}
        ]

    def update_run(self, path: Path, workflow: str, step: str | None, **fields: Any) -> None:
        with self.lock:
            self.jobs[(str(path.resolve()), workflow, step)].update(fields)

    def step_lock(self, path: Path, step: str) -> Any:
        with self.lock:
            return self.step_locks.setdefault((str(path.resolve()), step), threading.Lock())

    def report_pool_error(
        self, path: Path, error: dict[str, Any], workflow: str = "mapping", step: str | None = None
    ) -> None:
        with self.lock:
            job = self.jobs[(str(path.resolve()), workflow, step)]
            job["pool_errors"] = [*job.get("pool_errors", []), error]

    def close(self, timeout_seconds: float = 4.0) -> bool:
        """Wait boundedly for in-process semantic planning to finish before index release."""

        with self.lock:
            threads = list(self.threads.values())
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        return all(not thread.is_alive() for thread in threads)

    def _worker(
        self,
        key: tuple,
        target: RepositoryTarget,
        force: bool,
        retry_failed: bool,
        run: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        with self.lock:
            self.jobs[key] = {**self.jobs[key], "status": "running"}
        try:
            config = load_config(target.path, target.config_path)
            repository = self.database.repository(target.path)
            if repository is None or self.database.latest_snapshot(int(repository["id"])) is None:
                raise RuntimeError("A current structural snapshot is required")
            result = (
                run()
                if run is not None
                else SemanticEngine(self.database).bootstrap(
                    int(repository["id"]),
                    target.path,
                    config,
                    force=force,
                    retry_failed=retry_failed,
                )
            )
            status = {"status": "complete", **result}
        except Exception as exc:  # Background failures are intentionally visible in the UI.
            status = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:2_000],
            }
        with self.lock:
            self.jobs[key] = {**self.jobs[key], **status, "phase": status["status"]}
