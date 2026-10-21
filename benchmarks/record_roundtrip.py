"""Measure portable record size, no-op writes and a Git/cloud/local cache round trip."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from anaxigraph.portable_record import save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from benchmarks.repository_factory import create_history_repository


def git(root, *arguments):
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)


def measure(files=1000):
    with tempfile.TemporaryDirectory(prefix="anaxigraph-record-benchmark-") as temporary:
        root = Path(temporary)
        cloud = root / "cloud"
        create_history_repository(cloud, file_count=files, commits=1)
        database = AnaxiIndex(root / "cloud.db")
        scanned = RepositoryScanner(database).scan(cloud)
        started = time.perf_counter()
        saved = save_record(database, scanned.repository_id)
        save_seconds = time.perf_counter() - started
        started = time.perf_counter()
        unchanged = save_record(database, scanned.repository_id)
        noop_seconds = time.perf_counter() - started
        assert unchanged["changed_files"] == 0
        git(cloud, "add", "anaxigraph")
        git(cloud, "commit", "-qm", "Publish architecture record")
        local = root / "local"
        git(root, "clone", "-q", str(cloud), str(local))
        local_database = AnaxiIndex(root / "local.db")
        started = time.perf_counter()
        imported = RepositoryScanner(local_database).scan(local)
        import_seconds = time.perf_counter() - started
        assert imported.analyzed == 0 and imported.discovered == scanned.discovered
        return {
            "fixture": "Synthetic source, real Git, SQLite and portable JSON; no model calls.",
            "files": files,
            "record_bytes": saved["bytes"],
            "partitions": saved["parts"],
            "save_seconds": round(save_seconds, 3),
            "unchanged_save_seconds": round(noop_seconds, 3),
            "unchanged_changed_files": unchanged["changed_files"],
            "clone_load_and_source_verification_seconds": round(import_seconds, 3),
            "reused_files": imported.reused,
            "reanalyzed_files": imported.analyzed,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", nargs="+", type=int, default=[120, 1000])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"recorded_at": "2026-10-21", "runs": [measure(files) for files in args.files]}
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded)


if __name__ == "__main__":
    main()
