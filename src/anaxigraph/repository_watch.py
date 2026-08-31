"""Supervised repository watching for the single AnaxiGraph service lifecycle."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

import anaxigraph.git as git
from anaxigraph.history_jobs import ACTIVE_STATES, HistoryJobService

WatchResult = Callable[[Any, dict[str, Any]], None]
ServiceFactory = Callable[[Any], Any]
ConfigLoader = Callable[[Any, Any], Any]


class RepositoryWatchService:
    """Keep registered repository maps current under one supervised process."""

    def __init__(
        self,
        database: Any,
        targets: Iterable[Any],
        *,
        interval_seconds: float,
        scanner_factory: ServiceFactory,
        config_loader: ConfigLoader,
        semantic_factory: ServiceFactory,
        history_service: HistoryJobService | None = None,
        on_change: WatchResult | None = None,
    ) -> None:
        if interval_seconds < 0.2:
            raise ValueError("Watch interval must be at least 0.2 seconds")
        self.database = database
        self.targets = tuple(targets)
        self.interval_seconds = interval_seconds
        self.scanner_factory = scanner_factory
        self.config_loader = config_loader
        self.semantic_factory = semantic_factory
        self.history_service = history_service or HistoryJobService(database)
        self.on_change = on_change
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._observed_heads: dict[str, str] = {}
        self._targets: dict[str, dict[str, Any]] = {
            target.key: {"status": "idle", "path": str(target.path)} for target in self.targets
        }

    def start(self) -> bool:
        """Start the supervised background loop once."""

        if not self.targets:
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self.run_forever,
                name="anaxigraph-repository-watch",
                daemon=True,
            )
            self._thread.start()
        return True

    def stop(self, timeout_seconds: float = 4.0) -> bool:
        """Stop future cycles and cancel the active watcher scan at a safe checkpoint."""

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        stopped = thread is None or not thread.is_alive()
        if stopped:
            with self._lock:
                self._thread = None
        return stopped and self.history_service.close(max(0.0, deadline - time.monotonic()))

    def run_forever(self) -> None:
        """Run cycles in the current thread; used by both service and compatibility CLI."""

        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval_seconds)

    def run_once(self) -> None:
        self.history_service.recover(self.targets)
        for target in self.targets:
            if self._stop.is_set():
                return
            self._watch_target(target)

    def status(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
            targets = {key: dict(value) for key, value in self._targets.items()}
        return {
            "enabled": bool(self.targets),
            "running": bool(thread and thread.is_alive()),
            "interval_seconds": self.interval_seconds,
            "targets": targets,
        }

    def _watch_target(self, target: Any) -> None:
        repository = self.database.repository(target.path)
        if (
            repository
            and self.history_service.status(int(repository["id"]))["status"] in ACTIVE_STATES
        ):
            self._update(target, status="waiting_for_history")
            return
        self._update(target, status="scanning", error=None)
        try:
            stats = self.scanner_factory(self.database).scan(
                target.path,
                config_path=target.config_path,
                run_type="watch",
                is_cancelled=self._stop.is_set,
            )
        except Exception as exc:  # A broken target must not stop the other registered repositories.
            if self._stop.is_set():
                self._update(target, status="stopped")
            else:
                self._update(target, status="failed", error=f"{type(exc).__name__}: {exc}"[:2_000])
            return
        result = stats.as_dict()
        self._update(target, status="current", scan=result)
        if (stats.analyzed or stats.deleted) and self.on_change is not None:
            self.on_change(target, result)
        self._refresh_history(target)
        config = self.config_loader(target.path, target.config_path)
        if config.semantic.enabled and config.semantic.refresh in {"watch", "on_scan"}:
            self.semantic_factory(self.database).bootstrap(stats.repository_id, target.path, config)

    def _refresh_history(self, target: Any) -> None:
        if target.history_snapshots == 0 or not git.has_commits(target.path):
            return
        head = git.metadata(target.path).commit_sha
        repository = self.database.repository(target.path)
        imported = (
            self.history_service.latest_imported_commit(int(repository["id"]))
            if repository
            else None
        )
        if self._observed_heads.get(target.key, imported) == head:
            self._observed_heads[target.key] = head
            return
        self.history_service.start(target, after_revision=imported)
        self._observed_heads[target.key] = head

    def _update(self, target: Any, **values: Any) -> None:
        with self._lock:
            self._targets[target.key].update(values, updated_at=datetime.now(UTC).isoformat())
