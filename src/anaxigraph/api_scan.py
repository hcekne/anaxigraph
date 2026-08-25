"""Asynchronous structural-scan coordination with observable cancellation."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from anaxigraph.scanner import RepositoryScanner, ScanCancelled

TerminalCallback = Callable[[], None]
CompletedCallback = Callable[[], None]


@dataclass(slots=True)
class _ScanJob:
    target: Any
    cancel: threading.Event
    thread: threading.Thread
    state: dict[str, Any]


class ScanCoordinator:
    """Own one nonblocking structural scan per mounted repository."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self._jobs: dict[str, _ScanJob] = {}
        self._lock = threading.Lock()

    def start(
        self,
        target: Any,
        repository_id: int,
        *,
        on_complete: CompletedCallback | None = None,
        on_terminal: TerminalCallback | None = None,
    ) -> dict[str, Any]:
        key = self._key(target.path)
        now = _now()
        cancel = threading.Event()
        state = {
            "status": "queued",
            "active": True,
            "scan_id": str(uuid.uuid4()),
            "repository_id": repository_id,
            "phase": "queued",
            "completed": 0,
            "total": None,
            "current_path": None,
            "analysis_run_id": None,
            "started_at": now,
            "updated_at": now,
        }
        thread = threading.Thread(
            target=self._worker,
            args=(key, cancel, on_complete, on_terminal),
            name=f"anaxigraph-scan-{target.key}",
            daemon=True,
        )
        job = _ScanJob(target, cancel, thread, state)
        with self._lock:
            current = self._jobs.get(key)
            if current and current.state.get("active"):
                return dict(current.state) | {"status": "already_running"}
            self._jobs[key] = job
        try:
            thread.start()
        except Exception:
            with self._lock:
                state.update(status="failed", active=False, updated_at=_now())
            if on_terminal is not None:
                on_terminal()
            raise
        return dict(state)

    def status_for(self, path: Path) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(self._key(path))
            return dict(job.state) if job else _idle_status()

    def cancel(self, path: Path) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(self._key(path))
            if job is None or not job.state.get("active"):
                return (dict(job.state) if job else _idle_status()) | {"cancel_requested": False}
            job.cancel.set()
            job.state.update(
                status="cancelling",
                phase="cancelling",
                cancel_requested=True,
                updated_at=_now(),
            )
            return dict(job.state)

    def close(self, timeout_seconds: float = 4.0) -> None:
        """Request cancellation without holding application shutdown indefinitely."""

        with self._lock:
            jobs = [job for job in self._jobs.values() if job.state.get("active")]
            for job in jobs:
                job.cancel.set()
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        for job in jobs:
            job.thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _worker(
        self,
        key: str,
        cancel: threading.Event,
        on_complete: CompletedCallback | None,
        on_terminal: TerminalCallback | None,
    ) -> None:
        self._update(key, status="running", phase="starting")
        try:
            job = self._job(key)
            stats = RepositoryScanner(self.database).scan(
                job.target.path,
                config_path=job.target.config_path,
                progress=lambda value: self._progress(key, value),
                is_cancelled=cancel.is_set,
            )
        except ScanCancelled:
            self._update(
                key,
                status="cancelled",
                active=False,
                phase="cancelled",
                current_path=None,
            )
        except Exception as exc:  # Background failures must stay visible to operators.
            self._update(
                key,
                status="failed",
                active=False,
                phase="failed",
                current_path=None,
                error=f"{type(exc).__name__}: {exc}"[:2_000],
            )
        else:
            self._update(
                key,
                status="complete",
                active=False,
                phase="complete",
                current_path=None,
                scan=stats.as_dict(),
            )
            if on_complete is not None:
                try:
                    on_complete()
                except Exception as exc:  # The completed structural snapshot remains valid.
                    self._update(key, follow_up_error=f"{type(exc).__name__}: {exc}"[:2_000])
        finally:
            if on_terminal is not None:
                on_terminal()

    def _progress(self, key: str, value: dict[str, Any]) -> None:
        job = self._job(key)
        status = "cancelling" if job.cancel.is_set() else "running"
        self._update(key, status=status, active=True, **value)

    def _job(self, key: str) -> _ScanJob:
        with self._lock:
            return self._jobs[key]

    def _update(self, key: str, **values: Any) -> None:
        with self._lock:
            self._jobs[key].state.update(values, updated_at=_now())

    @staticmethod
    def _key(path: Path) -> str:
        return str(path.resolve())


def _idle_status() -> dict[str, Any]:
    return {"status": "idle", "active": False, "phase": "idle"}


def _now() -> str:
    return datetime.now(UTC).isoformat()
