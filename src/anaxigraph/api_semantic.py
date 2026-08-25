"""Background semantic-refresh coordination for the REST application."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from anaxigraph.config import load_config
from anaxigraph.registry import RepositoryTarget
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


class SemanticRefreshCoordinator:
    def __init__(self, database: AnaxiIndex) -> None:
        self.database = database
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start(
        self,
        target: RepositoryTarget,
        *,
        force: bool = False,
        retry_failed: bool = False,
    ) -> bool:
        key = str(target.path.resolve())
        config = load_config(target.path, target.config_path)
        if not config.semantic.enabled:
            return False
        repository = self.database.repository(target.path)
        if repository is not None:
            durable = SemanticEngine(self.database).status(int(repository["id"]), config.semantic)
            jobs = durable.get("jobs", {})
            if int(jobs.get("running_live", jobs.get("running", 0))) > 0:
                return False
        with self.lock:
            if self.jobs.get(key, {}).get("status") in {"queued", "running"}:
                return False
            self.jobs[key] = {"status": "queued"}
        threading.Thread(
            target=self._worker,
            args=(target, force, retry_failed),
            name=f"anaxigraph-semantic-{target.key}",
            daemon=True,
        ).start()
        return True

    def status_for(self, path: Path) -> dict[str, Any]:
        with self.lock:
            return dict(self.jobs.get(str(path.resolve()), {"status": "idle"}))

    def _worker(
        self,
        target: RepositoryTarget,
        force: bool,
        retry_failed: bool,
    ) -> None:
        key = str(target.path.resolve())
        with self.lock:
            self.jobs[key] = {"status": "running"}
        try:
            config = load_config(target.path, target.config_path)
            repository = self.database.repository(target.path)
            if repository is None or self.database.latest_snapshot(int(repository["id"])) is None:
                raise RuntimeError("A current structural snapshot is required")
            result = SemanticEngine(self.database).bootstrap(
                int(repository["id"]),
                target.path,
                config,
                force=force,
                retry_failed=retry_failed,
            )
            status = {"status": "complete", **result}
        except Exception as exc:  # Background failures are intentionally visible in the UI.
            status = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:2_000],
            }
        with self.lock:
            self.jobs[key] = status
