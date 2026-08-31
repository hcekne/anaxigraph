"""Durable coordination for resumable background Git history imports."""

from __future__ import annotations

import json
import os
import socket
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.clock import utc_now
from anaxigraph.history import HistoryImportCancelled, import_git_history
from anaxigraph.registry import RepositoryTarget
from anaxigraph.storage import AnaxiIndex

ACTIVE_STATES = frozenset({"queued", "enumerating", "importing", "finalizing"})
JOB_TYPE = "history_import"
CLAIM_STALE_SECONDS = 300


class HistoryJobService:
    """Run history imports while keeping their control plane in AnaxiIndex."""

    def __init__(self, database: AnaxiIndex) -> None:
        self.database = database
        self._lock = threading.Lock()
        self._threads: dict[int, threading.Thread] = {}

    def status(self, repository_id: int) -> dict[str, Any]:
        row = self._latest(repository_id)
        if row is None:
            return {"status": "not_started"}
        metadata = json.loads(row.pop("metadata_json") or "{}")
        value = {**row, **metadata}
        value["elapsed_seconds"] = _elapsed_seconds(row["started_at"], row["completed_at"])
        if value.get("eta_seconds") is not None:
            value["eta_label"] = "estimated remaining"
        value.setdefault("last_complete_snapshot_id", self._latest_snapshot_id(repository_id))
        return value

    def start(self, target: RepositoryTarget) -> dict[str, Any]:
        record = self.start_record(target)
        job_id = record.get("job_id")
        if job_id is None:
            return {"started": False, "reason": record["status"]}
        resumed = bool(record["resumed"])
        launched = self._launch(job_id, target, resumed=resumed)
        repository = self.database.repository(target.path)
        assert repository is not None
        repository_id = int(repository["id"])
        return {
            "started": not resumed and launched,
            "resumed": resumed and launched,
            "already_running": not launched,
            "job": self.status(repository_id),
        }

    def run_inline(
        self,
        target: RepositoryTarget,
        *,
        every_commit: bool = False,
        since: str | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        started = self.start_record(target)
        if not started["job_id"]:
            return started
        if not self._claim(int(started["job_id"])):
            repository = self.database.repository(target.path)
            assert repository is not None
            return self.status(int(repository["id"]))
        self._worker(
            int(started["job_id"]),
            target,
            resumed=bool(started["resumed"]),
            every_commit=every_commit,
            since=since,
            progress=progress,
        )
        repository = self.database.repository(target.path)
        assert repository is not None
        return self.status(int(repository["id"]))

    def start_record(self, target: RepositoryTarget) -> dict[str, Any]:
        """Create or claim a job without starting a daemon thread."""

        if target.history_snapshots == 0 or not git.has_commits(target.path):
            return {"job_id": None, "resumed": False, "status": "not_configured"}
        repository = self.database.repository(target.path)
        if repository is None:
            repository_id = self.database.ensure_repository(
                path=target.path,
                name=target.path.name,
                git=git.metadata(target.path),
            )
        else:
            repository_id = int(repository["id"])
        with self.database.transaction() as connection:
            active = connection.execute(
                """
                SELECT id FROM analysis_runs WHERE repository_id = ? AND run_type = ?
                  AND status IN ('queued', 'enumerating', 'importing', 'finalizing')
                ORDER BY id DESC LIMIT 1
                """,
                (repository_id, JOB_TYPE),
            ).fetchone()
            if active is not None:
                return {"job_id": int(active["id"]), "resumed": True}
            cursor = connection.execute(
                """
                INSERT INTO analysis_runs(repository_id, run_type, status, started_at, metadata_json)
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (
                    repository_id,
                    JOB_TYPE,
                    utc_now(),
                    json.dumps(_initial_metadata(target), sort_keys=True),
                ),
            )
            return {"job_id": int(cursor.lastrowid), "resumed": False}

    def cancel(self, repository_id: int) -> dict[str, Any]:
        row = self._active(repository_id)
        if row is None:
            return {
                "cancelled": False,
                "reason": "no_active_job",
                "job": self.status(repository_id),
            }
        self._update(int(row["id"]), cancel_requested=True, cancel_requested_at=utc_now())
        return {"cancelled": True, "job": self.status(repository_id)}

    def recover(self, targets: tuple[RepositoryTarget, ...] | list[RepositoryTarget]) -> int:
        recovered = 0
        for target in targets:
            repository = self.database.repository(target.path)
            if repository is None or target.history_snapshots == 0:
                continue
            active = self._active(int(repository["id"]))
            if active is None:
                continue
            recovered += int(self._launch(int(active["id"]), target, resumed=True))
        return recovered

    def _launch(self, job_id: int, target: RepositoryTarget, *, resumed: bool) -> bool:
        with self._lock:
            current = self._threads.get(job_id)
            if current is not None and current.is_alive():
                return False
            if not self._claim(job_id):
                return False
            thread = threading.Thread(
                target=self._worker,
                args=(job_id, target),
                kwargs={"resumed": resumed},
                name=f"anaxigraph-history-{target.key}",
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()
            return True

    def _claim(self, job_id: int) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT status, metadata_json FROM analysis_runs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] not in ACTIVE_STATES:
                return False
            metadata = json.loads(row["metadata_json"] or "{}")
            owner_pid = int(metadata.get("worker_pid") or 0)
            same_host = metadata.get("worker_host") == socket.gethostname()
            heartbeat = metadata.get("heartbeat_at") or metadata.get("claimed_at")
            if owner_pid and (
                (same_host and _pid_is_running(owner_pid))
                or (heartbeat and _elapsed_seconds(heartbeat, None) < CLAIM_STALE_SECONDS)
            ):
                return False
            metadata.update(
                worker_pid=os.getpid(),
                worker_host=socket.gethostname(),
                claimed_at=utc_now(),
                heartbeat_at=utc_now(),
            )
            connection.execute(
                "UPDATE analysis_runs SET metadata_json = ? WHERE id = ?",
                (json.dumps(metadata, sort_keys=True), job_id),
            )
            return True

    def _worker(
        self,
        job_id: int,
        target: RepositoryTarget,
        *,
        resumed: bool,
        every_commit: bool = False,
        since: str | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        prior = self._job(job_id)
        measured = self._measure()
        baseline = (
            int(prior.get("baseline_rows", measured[0])),
            int(prior.get("baseline_bytes", measured[1])),
        )
        resume_count = int(prior.get("resume_count") or 0) + int(resumed)
        reset_cancel = {"cancel_requested": False} if not resumed else {}
        self._transition(
            job_id,
            "enumerating",
            resume_count=resume_count,
            baseline_rows=baseline[0],
            baseline_bytes=baseline[1],
            **reset_cancel,
        )
        try:
            result = self._execute_import(
                job_id, target, baseline, every_commit=every_commit, since=since, progress=progress
            )
            self._complete(job_id, baseline, result)
        except HistoryImportCancelled as exc:
            self._finish(job_id, "cancelled", error=str(exc), eta_seconds=None)
        except Exception as exc:  # Durable error detail is the operator-facing failure report.
            self._finish(
                job_id,
                "failed",
                error=f"{type(exc).__name__}: {exc}"[:4_000],
                eta_seconds=None,
            )
        finally:
            with self._lock:
                self._threads.pop(job_id, None)

    def _execute_import(
        self,
        job_id: int,
        target: RepositoryTarget,
        baseline: tuple[int, int],
        *,
        every_commit: bool,
        since: str | None,
        progress: Callable[[int, int, str], None] | None,
    ) -> Any:
        return import_git_history(
            self.database,
            target.path,
            config_path=target.config_path,
            max_snapshots=target.history_snapshots,
            every_commit=every_commit,
            since=since,
            progress=progress,
            job_progress=lambda event: self._record_progress(job_id, event, baseline),
            should_cancel=lambda: self._cancel_requested(job_id),
        )

    def _complete(self, job_id: int, baseline: tuple[int, int], result: Any) -> None:
        rows, size = self._measure()
        self._finish(
            job_id,
            "complete",
            snapshot_id=result.current_snapshot_id,
            result=result.as_dict(),
            work=result.work,
            rows_added=max(0, rows - baseline[0]),
            bytes_added=max(0, size - baseline[1]),
            last_complete_snapshot_id=result.current_snapshot_id,
            eta_seconds=0,
        )

    def _record_progress(
        self, job_id: int, event: dict[str, Any], baseline: tuple[int, int]
    ) -> None:
        stage = str(event.pop("stage"))
        status = "finalizing" if stage == "finalizing" else "importing"
        rows, size = self._measure()
        completed = int(event.get("completed_frames") or 0)
        total = int(event.get("total_frames") or 0)
        elapsed = self._elapsed(job_id)
        eta = (elapsed / completed * (total - completed)) if completed and total else None
        work = event.get("work") or {}
        current_commit = {}
        if event.get("commit_sha"):
            current_commit = {
                "current_commit_sha": event.get("commit_sha"),
                "current_commit_subject": event.get("commit_subject"),
                "current_commit_date": event.get("commit_date"),
            }
        self._transition(
            job_id,
            status,
            phase=stage,
            **event,
            **current_commit,
            changed_files=int(work.get("source_reads") or 0),
            analyzed_files=int(work.get("analyzed_files") or 0),
            re_resolved_files=int(work.get("relationship_sources_resolved") or 0),
            reused_files=int(work.get("carried_forward") or 0)
            + int(work.get("reused_analysis") or 0),
            rows_added=max(0, rows - baseline[0]),
            bytes_added=max(0, size - baseline[1]),
            eta_seconds=round(eta, 1) if eta is not None else None,
        )

    def _transition(self, job_id: int, status: str, **metadata: Any) -> None:
        metadata["heartbeat_at"] = utc_now()
        self._update(job_id, status=status, **metadata)

    def _finish(
        self,
        job_id: int,
        status: str,
        *,
        snapshot_id: int | None = None,
        error: str | None = None,
        **metadata: Any,
    ) -> None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM analysis_runs WHERE id = ?", (job_id,)
            ).fetchone()
            current = json.loads(row["metadata_json"] or "{}") if row else {}
            current.update(metadata)
            connection.execute(
                """
                UPDATE analysis_runs SET status = ?, snapshot_id = COALESCE(?, snapshot_id),
                    completed_at = ?, metadata_json = ?, error = ? WHERE id = ?
                """,
                (
                    status,
                    snapshot_id,
                    utc_now(),
                    json.dumps(current, sort_keys=True),
                    error,
                    job_id,
                ),
            )

    def _update(self, job_id: int, *, status: str | None = None, **metadata: Any) -> None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM analysis_runs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return
            current = json.loads(row["metadata_json"] or "{}")
            current.update(metadata)
            connection.execute(
                """
                UPDATE analysis_runs SET status = COALESCE(?, status), metadata_json = ?
                WHERE id = ?
                """,
                (status, json.dumps(current, sort_keys=True), job_id),
            )

    def _job(self, job_id: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE id = ? AND run_type = ?", (job_id, JOB_TYPE)
            ).fetchone()
        if row is None:
            return {}
        value = dict(row)
        value.update(json.loads(value.pop("metadata_json") or "{}"))
        return value

    def _latest(self, repository_id: int) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM analysis_runs WHERE repository_id = ? AND run_type = ?
                ORDER BY id DESC LIMIT 1
                """,
                (repository_id, JOB_TYPE),
            ).fetchone()
        return dict(row) if row else None

    def _active(self, repository_id: int) -> dict[str, Any] | None:
        row = self._latest(repository_id)
        return row if row and row["status"] in ACTIVE_STATES else None

    def _cancel_requested(self, job_id: int) -> bool:
        return bool(self._job(job_id).get("cancel_requested"))

    def _elapsed(self, job_id: int) -> float:
        value = self._job(job_id)
        return _elapsed_seconds(value.get("started_at"), None)

    def _latest_snapshot_id(self, repository_id: int) -> int | None:
        snapshot = self.database.latest_snapshot(repository_id)
        return int(snapshot["id"]) if snapshot else None

    def _measure(self) -> tuple[int, int]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM snapshots) +
                  (SELECT COUNT(*) FROM file_facts) +
                  (SELECT COUNT(*) FROM fact_symbols) +
                  (SELECT COUNT(*) FROM relationship_edges) +
                  (SELECT COUNT(*) FROM metrics) AS rows
                """
            ).fetchone()
        size = sum(
            path.stat().st_size
            for path in (self.database.path, Path(f"{self.database.path}-wal"))
            if path.exists()
        )
        return int(row["rows"]), size


def _initial_metadata(target: RepositoryTarget) -> dict[str, Any]:
    return {
        "job_schema": "history-import-v1",
        "repository_path": str(target.path.resolve()),
        "history_snapshots": target.history_snapshots,
        "completed_frames": 0,
        "total_frames": 0,
        "cancel_requested": False,
        "resume_count": 0,
        "work": {},
    }


def _elapsed_seconds(started_at: str | None, completed_at: str | None) -> float:
    if not started_at:
        return 0.0
    started = datetime.fromisoformat(started_at)
    ended = datetime.fromisoformat(completed_at) if completed_at else datetime.now(UTC)
    return round(max(0.0, (ended - started).total_seconds()), 1)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def open_history_service(path: str | Path) -> HistoryJobService:
    return HistoryJobService(AnaxiIndex(path))
