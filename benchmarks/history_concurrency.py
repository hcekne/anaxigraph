"""Measure dashboard responsiveness while a synthetic history import is active."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from anaxigraph.history_jobs import ACTIVE_STATES, HistoryJobService
from anaxigraph.registry import RepositoryTarget
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from benchmarks.repository_factory import (
    DEFAULT_COMMITS,
    DEFAULT_FILE_COUNT,
    create_history_repository,
)
from benchmarks.runtime_metrics import dashboard_metrics


def concurrent_dashboard_profile(
    project_root: Path,
    *,
    file_count: int = DEFAULT_FILE_COUNT,
    frames: int = DEFAULT_COMMITS,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="anaxigraph-concurrency-") as temporary:
        work = Path(temporary)
        repository = work / "repository"
        create_history_repository(repository, file_count=file_count, commits=frames)
        database = AnaxiIndex(work / "anaxi-index.db")
        RepositoryScanner(database).scan(repository, run_type="benchmark_current")
        service = HistoryJobService(database)
        target = RepositoryTarget("benchmark", repository, history_snapshots=frames)
        started = service.start(target)
        repository_row = database.repository(repository)
        assert repository_row is not None
        repository_id = int(repository_row["id"])
        active = _wait_for(service, repository_id, ACTIVE_STATES - {"queued", "enumerating"})
        dashboard = dashboard_metrics(database, repository, project_root)
        service.cancel(repository_id)
        terminal = _wait_for(service, repository_id, {"complete", "cancelled", "failed"})
        return {
            "fixture": {"files": file_count, "frames": frames},
            "job_at_measurement": active,
            "job_after_measurement": terminal,
            "dashboard": dashboard,
            "start": started,
        }


def _wait_for(
    service: HistoryJobService,
    repository_id: int,
    statuses: set[str] | frozenset[str],
    *,
    timeout: float = 180,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.status(repository_id)
        if status["status"] in statuses:
            return status
        time.sleep(0.05)
    raise TimeoutError(f"history job did not reach {sorted(statuses)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--synthetic-files", type=int, default=DEFAULT_FILE_COUNT)
    parser.add_argument("--history-frames", type=int, default=DEFAULT_COMMITS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = concurrent_dashboard_profile(
        args.repository.expanduser().resolve(),
        file_count=args.synthetic_files,
        frames=args.history_frames,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
