"""Machine-readable Phase 0 baseline for scans, history, APIs, scope, and tests."""

from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.analyzers import builtin_registry
from anaxigraph.analyzers.base import AnalyzerRegistry, LanguageAnalyzer
from anaxigraph.history import import_git_history
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import SCHEMA_VERSION, AnaxiIndex
from benchmarks.repository_factory import (
    DEFAULT_COMMITS,
    DEFAULT_FILE_COUNT,
    DEFAULT_SEED,
    create_history_repository,
)
from benchmarks.runtime_metrics import (
    api_metrics,
    dashboard_metrics,
    environment,
    measure,
    scope_metrics,
    test_metrics,
)

REPORT_SCHEMA_VERSION = 1


class _CountingAnalyzer:
    def __init__(self, delegate: LanguageAnalyzer, counts: Counter[str]) -> None:
        self._delegate = delegate
        self._counts = counts
        self.name = delegate.name
        self.languages = delegate.languages

    def analyze(self, path: str, content: str):
        self._counts["total"] += 1
        self._counts[f"language:{self._language(path)}"] += 1
        return self._delegate.analyze(path, content)

    def _language(self, path: str) -> str:
        suffix = Path(path).suffix.lower().removeprefix(".")
        return suffix or "none"


def _counting_registry(counts: Counter[str]) -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    for analyzer in builtin_registry().analyzers:
        registry.register(_CountingAnalyzer(analyzer, counts))
    return registry


@contextlib.contextmanager
def _counted_revision_reads() -> Iterator[Counter[str]]:
    counts: Counter[str] = Counter()
    original = git.read_at_revision

    def counted(root: Path, revision: str, path: str, *, max_bytes: int) -> bytes | None:
        counts["attempted"] += 1
        value = original(root, revision, path, max_bytes=max_bytes)
        if value is not None:
            counts["returned"] += 1
            counts["bytes"] += len(value)
        return value

    git.read_at_revision = counted
    try:
        yield counts
    finally:
        git.read_at_revision = original


def _scan_repository(repository: Path, database_path: Path) -> tuple[AnaxiIndex, dict[str, Any]]:
    database = AnaxiIndex(database_path)
    analyzer_counts: Counter[str] = Counter()
    scanner = RepositoryScanner(database, registry=_counting_registry(analyzer_counts))
    stats, timing = measure(lambda: scanner.scan(repository))
    return database, {
        **timing,
        **stats.as_dict(),
        "analyzer_invocations": analyzer_counts["total"],
        "analyzer_invocations_by_suffix": _prefixed_counts(analyzer_counts, "language:"),
    }


def _history_repository(
    repository: Path,
    database_path: Path,
    *,
    frames: int,
    manifest: dict[str, Any],
) -> tuple[AnaxiIndex, dict[str, Any]]:
    database = AnaxiIndex(database_path)
    analyzer_counts: Counter[str] = Counter()
    scanner = RepositoryScanner(database, registry=_counting_registry(analyzer_counts))
    progress: list[dict[str, Any]] = []

    def run():
        return import_git_history(
            database,
            repository,
            max_snapshots=frames,
            progress=lambda index, total, sha: progress.append(
                {"index": index, "total": total, "commit_sha": sha}
            ),
            scanner=scanner,
        )

    with _counted_revision_reads() as read_counts:
        result, timing = measure(run)
    store = _store_metrics(database)
    _assert_fixture_invariants(store, manifest, frames)
    with database.connect() as connection:
        run_counts = dict(
            connection.execute(
                """
                SELECT COALESCE(SUM(discovered_count), 0), COALESCE(SUM(analyzed_count), 0),
                       COALESCE(SUM(reused_count), 0), COUNT(*)
                FROM analysis_runs
                """
            ).fetchone()
        )
    return database, {
        **timing,
        **result.as_dict(),
        "milliseconds_per_selected_frame": round(timing["wall_time_ms"] / max(frames, 1), 2),
        "source_blob_reads": dict(read_counts),
        "analyzer_invocations": analyzer_counts["total"],
        "analyzer_invocations_by_suffix": _prefixed_counts(analyzer_counts, "language:"),
        "analysis_run_totals": {
            "discovered": run_counts["COALESCE(SUM(discovered_count), 0)"],
            "analyzed": run_counts["COALESCE(SUM(analyzed_count), 0)"],
            "reused": run_counts["COALESCE(SUM(reused_count), 0)"],
            "runs": run_counts["COUNT(*)"],
        },
        "progress_events": len(progress),
        "store_before_vacuum": store,
    }


def _prefixed_counts(counts: Counter[str], prefix: str) -> dict[str, int]:
    return {
        key.removeprefix(prefix): value
        for key, value in sorted(counts.items())
        if key.startswith(prefix)
    }


def _store_metrics(database: AnaxiIndex) -> dict[str, Any]:
    with database.connect() as connection:
        tables = (
            "repositories",
            "snapshots",
            "artifacts",
            "file_versions",
            "symbols",
            "relationships",
            "findings",
            "analysis_runs",
        )
        rows = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
        distinct = {
            "artifact_raw": _group_count(connection, "artifact_id, raw_hash"),
            "artifact_structural": _group_count(connection, "artifact_id, structural_hash"),
            "raw_hashes": _group_count(connection, "raw_hash"),
            "structural_hashes": _group_count(connection, "structural_hash"),
        }
        latest_files = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM file_versions
                WHERE snapshot_id = (SELECT MAX(id) FROM snapshots)
                """
            ).fetchone()[0]
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "rows": rows,
        "distinct_file_versions": distinct,
        "latest_snapshot_files": latest_files,
        "relationship_bundles": None,
        "relationship_bundle_note": "Schema 6 rematerializes edges and has no bundle table.",
        "index_bytes": _database_bytes(database.path),
    }


def _group_count(connection: sqlite3.Connection, columns: str) -> int:
    query = f"SELECT COUNT(*) FROM (SELECT {columns} FROM file_versions GROUP BY {columns})"
    return int(connection.execute(query).fetchone()[0])


def _database_bytes(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
        if candidate.exists()
    )


def _vacuum_metrics(database: AnaxiIndex) -> dict[str, int]:
    before = _database_bytes(database.path)
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"before_bytes": before, "after_bytes": _database_bytes(database.path)}


def _assert_fixture_invariants(
    store: dict[str, Any], manifest: dict[str, Any], frames: int
) -> None:
    if frames != manifest["commits"]:
        return
    expected = {
        "snapshots": frames,
        "latest_snapshot_files": manifest["final_files"],
        "artifact_raw": manifest["expected_distinct_artifact_raw_versions"],
        "artifact_structural": manifest["expected_distinct_artifact_structural_versions"],
    }
    actual = {
        "snapshots": store["rows"]["snapshots"],
        "latest_snapshot_files": store["latest_snapshot_files"],
        "artifact_raw": store["distinct_file_versions"]["artifact_raw"],
        "artifact_structural": store["distinct_file_versions"]["artifact_structural"],
    }
    if actual != expected:
        raise RuntimeError(f"benchmark fixture drifted: expected {expected}, got {actual}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-files", type=int, default=DEFAULT_FILE_COUNT)
    parser.add_argument("--history-frames", type=int, default=DEFAULT_COMMITS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-dashboard", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = args.repository.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anaxigraph-baseline-") as temporary:
        work = Path(temporary)
        synthetic = work / "synthetic"
        manifest = create_history_repository(
            synthetic,
            file_count=args.synthetic_files,
            commits=args.history_frames,
            seed=args.seed,
        )
        current_db, current_scan = _scan_repository(project_root, work / "current.db")
        history_db, history_report = _history_repository(
            synthetic,
            work / "history.db",
            frames=args.history_frames,
            manifest=manifest,
        )
        report = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "environment": environment(project_root),
            "fixture": manifest,
            "current_repository": {
                "scan": current_scan,
                "api": api_metrics(current_db, project_root),
                "vacuum": _vacuum_metrics(current_db),
            },
            "synthetic_history": {
                "import": history_report,
                "api": api_metrics(history_db, synthetic),
                "scope": scope_metrics(
                    history_db,
                    synthetic,
                    manifest["scope_goal"],
                    manifest["scope_expected_candidates"],
                ),
                "dashboard": (
                    {"status": "skipped"}
                    if args.skip_dashboard
                    else dashboard_metrics(history_db, synthetic, project_root)
                ),
                "vacuum": _vacuum_metrics(history_db),
            },
            "tests": (
                {"status": "skipped"} if args.skip_tests else test_metrics(project_root, work)
            ),
        }
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps({"status": "complete", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
