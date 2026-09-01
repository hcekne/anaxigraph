"""Repository-scale JavaScript/TypeScript scan, history, and reuse benchmark."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from anaxigraph.history import import_git_history
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from benchmarks.runtime_metrics import environment, measure

REPORT_SCHEMA_VERSION = "javascript-analysis-v1"
DEFAULT_SIZES = (120, 1_000, 3_000)


def run_matrix(
    output: Path,
    *,
    sizes: tuple[int, ...] = DEFAULT_SIZES,
    history_frames: int = 3,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="anaxigraph-js-analysis-") as temporary:
        work = Path(temporary)
        cases = {str(size): _measure_case(work / str(size), size, history_frames) for size in sizes}
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "environment": environment(Path.cwd()),
        "history_frames": history_frames,
        "cases": cases,
        "passed": all(item["passed"] for item in cases.values()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _measure_case(root: Path, source_files: int, history_frames: int) -> dict[str, Any]:
    paths = _create_repository(root, source_files)
    current = AnaxiIndex(root.parent / f"current-{source_files}.db")
    scanner = RepositoryScanner(current)
    cold, cold_timing = measure(lambda: scanner.scan(root))
    unchanged, unchanged_timing = measure(lambda: scanner.scan(root))
    target = paths[-1]
    with target.open("a", encoding="utf-8") as stream:
        stream.write("\nexport const workingTreeChange = true;\n")
    incremental, incremental_timing = measure(lambda: scanner.scan(root))

    history = AnaxiIndex(root.parent / f"history-{source_files}.db")
    imported, history_timing = measure(
        lambda: import_git_history(history, root, max_snapshots=history_frames)
    )
    current_quality = current.overview(incremental.repository_id)["graph_quality"]
    with history.connect() as connection:
        runs = [
            {
                "discovered": int(row["discovered_count"]),
                "analyzed": int(row["analyzed_count"]),
                "reused": int(row["reused_count"]),
            }
            for row in connection.execute(
                """
                SELECT discovered_count, analyzed_count, reused_count
                FROM analysis_runs ORDER BY id
                """
            )
        ]
    indexed_files = source_files + 2
    checks = {
        "cold_indexed_every_file": cold.discovered == cold.analyzed == indexed_files,
        "all_source_files_parser_backed": current_quality["parser_files"] == source_files,
        "no_parser_errors": current_quality["parse_error_files"] == 0,
        "unchanged_scan_reanalyzed_nothing": unchanged.analyzed == 0,
        "one_file_change_reanalyzed_one": incremental.analyzed == 1,
        "history_selected_requested_frames": imported.imported_snapshots == history_frames,
        "history_reused_unchanged_files": (
            len(runs) in {history_frames, history_frames + 1}
            and runs[0]["analyzed"] == indexed_files
            and all(item["analyzed"] <= 1 for item in runs[1:])
        ),
    }
    return {
        "source_files": source_files,
        "indexed_files": indexed_files,
        "cold_scan": {**cold.as_dict(), **cold_timing},
        "unchanged_scan": {**unchanged.as_dict(), **unchanged_timing},
        "one_file_incremental_scan": {**incremental.as_dict(), **incremental_timing},
        "history_import": {**imported.as_dict(), **history_timing, "analysis_runs": runs},
        "graph_quality": current_quality,
        "index_bytes": _index_bytes(current.path),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _create_repository(root: Path, source_files: int) -> list[Path]:
    if source_files < 4:
        raise ValueError("source_files must be at least 4")
    (root / "src").mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "branch", "-M", "main")
    _git(root, "config", "user.email", "benchmark@example.invalid")
    _git(root, "config", "user.name", "AnaxiGraph Benchmark")
    _write_repository_configuration(root)
    paths = [root / "src" / "config.ts"]
    paths[0].write_text("export const settings = {enabled: true};\n", encoding="utf-8")
    previous = ""
    for index in range(1, source_files):
        suffix = (".ts", ".tsx", ".js", ".jsx")[index % 4]
        path = root / "src" / f"module_{index:05d}{suffix}"
        target = (
            "#config" if index == 1 else f"@modules/{previous}" if index == 2 else f"./{previous}"
        )
        path.write_text(_module_source(index, suffix, target), encoding="utf-8")
        paths.append(path)
        previous = path.stem
    _commit(root, "Initial parser-backed repository", 1)
    with paths[1].open("a", encoding="utf-8") as stream:
        stream.write("\nexport const revisionValue = 2;\n")
    _commit(root, "Change one module", 2)
    paths[2].write_text(
        paths[2].read_text(encoding="utf-8").replace("Module 2", "Updated module 2"),
        encoding="utf-8",
    )
    _commit(root, "Change one comment", 3)
    return paths


def _write_repository_configuration(root: Path) -> None:
    (root / ".anaxigraph.yml").write_text(
        """project:\n  name: Parser benchmark\ninclude:\n  - src/**\n  - package.json\n  - tsconfig.json\nsemantic:\n  enabled: false\n""",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"private": True, "imports": {"#config": "./src/config.ts"}}) + "\n",
        encoding="utf-8",
    )
    (root / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@modules/*": ["src/*"]}}})
        + "\n",
        encoding="utf-8",
    )


def _module_source(index: int, suffix: str, target: str) -> str:
    annotation = ": number" if suffix in {".ts", ".tsx"} else ""
    jsx = (
        f"\nexport const Module{index} = () => <span>{{transform({index})}}</span>;\n"
        if suffix in {".jsx", ".tsx"}
        else ""
    )
    imported = "settings" if index == 1 else "transform as previous"
    expression = "Number(settings.enabled)" if index == 1 else f"previous(value) + {index % 97}"
    return (
        f"// Module {index}\n"
        f"import {{{imported}}} from '{target}';\n"
        f"export function transform(value{annotation}){annotation} {{ return {expression}; }}\n"
        f"{jsx}"
    )


def _commit(root: Path, message: str, day: int) -> None:
    timestamp = f"2026-06-{day:02d}T12:00:00+00:00"
    commit_environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    _git(root, "add", "-A", environment=commit_environment)
    _git(root, "commit", "-qm", message, environment=commit_environment)


def _git(root: Path, *arguments: str, environment: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _index_bytes(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
        if candidate.exists()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=list(DEFAULT_SIZES))
    parser.add_argument("--history-frames", type=int, default=3)
    args = parser.parse_args(argv)
    report = run_matrix(
        args.output.expanduser().resolve(),
        sizes=tuple(args.sizes),
        history_frames=args.history_frames,
    )
    print(json.dumps({"output": str(args.output), "passed": report["passed"]}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
