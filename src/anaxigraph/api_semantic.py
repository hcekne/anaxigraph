"""Background semantic-refresh coordination for the REST application."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from anaxigraph.config import load_config
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner
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
            if int(durable.get("jobs", {}).get("running", 0)) > 0:
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
            stats = RepositoryScanner(self.database).scan(
                target.path,
                config_path=target.config_path,
                run_type="semantic_reconcile",
            )
            result = SemanticEngine(self.database).bootstrap(
                stats.repository_id,
                target.path,
                config,
                force=force,
                retry_failed=retry_failed,
            )
            status = {"status": "complete", "scan": stats.as_dict(), **result}
        except Exception as exc:  # Background failures are intentionally visible in the UI.
            status = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:2_000],
            }
        with self.lock:
            self.jobs[key] = status
