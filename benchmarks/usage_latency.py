"""Measure local interaction latency and payloads without model calls or network services."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

from anaxigraph.api import create_app
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from benchmarks.repository_factory import create_history_repository


def measure_usage_latency(*, files: int = 1000, trials: int = 10) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="anaxigraph-usage-latency-") as temporary:
        root = Path(temporary)
        repository = root / "repo"
        create_history_repository(repository, file_count=files, commits=1)
        database = AnaxiIndex(root / "index.db")
        scanner = RepositoryScanner(database)
        started = time.perf_counter()
        scanner.scan(repository)
        cold = time.perf_counter() - started
        started = time.perf_counter()
        scanner.scan(repository)
        warm = time.perf_counter() - started
        with TestClient(
            create_app(database=database, repository=repository, enable_mcp=False)
        ) as client:
            results = _interactions(client, trials)
            count = _all_pages(client)
            assert count == files
    return {
        "fixture": f"Deterministic synthetic Git repository; {files} files, one commit; no model calls.",
        "transport": "In-process HTTP through the real ASGI application and SQLite index.",
        "trials": trials,
        "statistics": "One excluded warmup per interaction; p95 is the nearest-rank percentile.",
        "cold_scan_seconds": round(cold, 3),
        "unchanged_scan_seconds": round(warm, 3),
        "indexed_files": files,
        "all_pages_count": count,
        "results": results,
    }


def _interactions(client: TestClient, trials: int) -> dict[str, Any]:
    results = {}
    for path in (
        "/api/overview",
        "/api/workflows",
        "/api/workflows?details=true",
        "/api/semantic",
        "/api/modules?limit=250",
        "/api/modules?limit=250&compact=true",
    ):
        results[path] = _measure(lambda: client.get(path), trials)
    results["guidance"] = _measure(
        lambda: client.post(
            "/api/guidance",
            json={"goal": "Change analyzer selection behavior in the existing analysis service"},
        ),
        trials,
    )
    results["impact"] = _measure(
        lambda: client.post("/api/impact", json={"target": "src/sample/service.py"}), trials
    )
    assert results["guidance"]["response_bytes"] <= 8000
    assert results["impact"]["response_bytes"] <= 8000
    return results


def _measure(call: Any, trials: int) -> dict[str, Any]:
    values = []
    for _ in range(trials + 1):
        started = time.perf_counter()
        response = call()
        values.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200, response.text
    samples = sorted(values[1:])
    return {
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[max(0, (95 * trials + 99) // 100 - 1)], 3),
        "response_bytes": len(response.content),
    }


def _all_pages(client: TestClient) -> int:
    total = client.get("/api/overview").json()["files"]
    items = []
    for offset in range(0, total, 250):
        items.extend(
            client.get(
                "/api/modules", params={"offset": offset, "limit": 250, "compact": True}
            ).json()
        )
    assert len(items) == len({item["path"] for item in items}) == total
    return len(items)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=1000)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.files < 100 or args.trials < 1:
        parser.error("Use at least 100 files and one trial")
    result = measure_usage_latency(files=args.files, trials=args.trials)
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
