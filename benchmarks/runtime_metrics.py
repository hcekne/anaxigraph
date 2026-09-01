"""Runtime, API, browser, scope, and test measurements for benchmark reports."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn

try:
    import resource
except ImportError:  # pragma: no cover - native Windows is reported as unsupported in Phase 0.
    resource = None  # type: ignore[assignment]

from anaxigraph import __version__
from anaxigraph.agent import architecture_guidance
from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.storage import AnaxiIndex

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
from fastapi.testclient import TestClient  # noqa: E402

SCOPE_TOKEN_ESTIMATE_BYTES = 4


def measure(function: Callable[[], Any]) -> tuple[Any, dict[str, int]]:
    """Measure wall time and process resident memory without profiler-scale overhead."""

    baseline_rss = _resident_bytes()
    peak_rss = [baseline_rss]
    stopped = threading.Event()

    def sample_memory() -> None:
        while not stopped.wait(0.05):
            peak_rss[0] = max(peak_rss[0], _resident_bytes())

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    started = time.perf_counter()
    try:
        result = function()
    finally:
        peak_rss[0] = max(peak_rss[0], _resident_bytes())
        stopped.set()
        sampler.join(timeout=1)
    return result, {
        "wall_time_ms": round((time.perf_counter() - started) * 1_000),
        "peak_resident_bytes": peak_rss[0],
        "peak_resident_delta_bytes": max(0, peak_rss[0] - baseline_rss),
    }


def api_metrics(database: AnaxiIndex, repository: Path) -> dict[str, Any]:
    app = create_app(database=database, repository=repository, enable_mcp=False)
    targets = _graph_targets(database)
    with TestClient(app) as client:
        measurements = {
            name: _graph_request_metrics(client, snapshot_id)
            for name, snapshot_id in targets.items()
        }
    current = measurements["current"]
    return {
        "graph_payload_bytes": current["payload_bytes"],
        "graph_nodes": current["nodes"],
        "graph_edges": current["edges"],
        "cold_request_ms": current["cold_request_ms"],
        "warm_request_median_ms": current["warm_request_median_ms"],
        "reconstruction": current["reconstruction"],
        "temporal_reads": measurements,
    }


def _graph_targets(database: AnaxiIndex) -> dict[str, int | None]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT id FROM snapshots ORDER BY repository_id, sequence, id"
        ).fetchall()
        current = connection.execute(
            "SELECT current_snapshot_id FROM repositories ORDER BY id LIMIT 1"
        ).fetchone()
    snapshot_ids = [int(row["id"]) for row in rows]
    current_id = int(current[0]) if current and current[0] is not None else None
    if not snapshot_ids:
        return {"current": None, "oldest": None, "middle": None}
    return {
        "current": current_id or snapshot_ids[-1],
        "oldest": snapshot_ids[0],
        "middle": snapshot_ids[len(snapshot_ids) // 2],
    }


def _graph_request_metrics(client: TestClient, snapshot_id: int | None) -> dict[str, Any]:
    durations: list[float] = []
    params = {"snapshot_id": snapshot_id} if snapshot_id is not None else None
    for _ in range(4):
        started = time.perf_counter()
        response = client.get("/api/graph", params=params)
        response.raise_for_status()
        durations.append((time.perf_counter() - started) * 1_000)
    payload = response.json()
    return {
        "snapshot_id": snapshot_id,
        "payload_bytes": len(response.content),
        "nodes": len(payload["nodes"]),
        "edges": len(payload["edges"]),
        "cold_request_ms": round(durations[0], 2),
        "warm_request_median_ms": round(statistics.median(durations[1:]), 2),
        "reconstruction": payload.get("reconstruction"),
    }


def scope_metrics(
    database: AnaxiIndex, repository: Path, goal: str, expected: list[str]
) -> dict[str, Any]:
    row = database.repository(repository)
    if row is None:
        raise RuntimeError("benchmark repository was not indexed")
    payload, timing = measure(
        lambda: architecture_guidance(
            database,
            repository_id=int(row["id"]),
            goal=goal,
            config=load_config(repository),
        )
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    primary = [item["path"] for item in payload["primary_files"]]
    expected_set = set(expected)
    decision = payload["architecture_decision"]
    verification = decision.get("verification") or {}
    return {
        **timing,
        "goal": goal,
        "payload_bytes": len(encoded),
        "estimated_tokens": (len(encoded) + SCOPE_TOKEN_ESTIMATE_BYTES - 1)
        // SCOPE_TOKEN_ESTIMATE_BYTES,
        "primary_files": primary,
        "expected_candidate_hits": sorted(expected_set.intersection(primary)),
        "unexpected_primary_files": sorted(set(primary).difference(expected_set)),
        "architecture_decision": {
            "contract_version": decision.get("contract_version"),
            "status": decision.get("status"),
            "preferred_path": (decision.get("placement") or {}).get("preferred_path"),
            "task_path_status": (decision.get("task_path") or {}).get("status"),
            "task_path_module": ((decision.get("task_path") or {}).get("module") or {}).get("path"),
            "rescan_included": bool(verification.get("rescan_argv")),
            "focused_test_count": len(verification.get("focused_test_paths") or ()),
        },
        "payload_budget": payload["payload_budget"],
    }


def dashboard_metrics(database: AnaxiIndex, repository: Path, project_root: Path) -> dict[str, Any]:
    node = shutil.which("node")
    script = project_root / "benchmarks" / "dashboard_render.mjs"
    if node is None or not script.exists():
        return {"status": "unavailable", "reason": "Node or dashboard benchmark is missing"}
    app = create_app(database=database, repository=repository, enable_mcp=False)
    server_socket = socket.socket()
    server_socket.bind(("127.0.0.1", 0))
    port = int(server_socket.getsockname()[1])
    server_socket.close()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
        )
    )
    thread = threading.Thread(
        target=server.run,
        daemon=True,
    )
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(f"{url}/healthz")
        result = subprocess.run(
            [node, str(script), url],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            return {
                "status": "measured",
                "runner": "local-playwright",
                **json.loads(result.stdout.strip().splitlines()[-1]),
            }
        container_result = _container_dashboard_render(project_root, url)
        if container_result is not None and container_result.returncode == 0:
            return {
                "status": "measured",
                "runner": "playwright-container",
                **json.loads(container_result.stdout.strip().splitlines()[-1]),
            }
        reasons = [result.stderr.strip()[-750:]]
        if container_result is not None:
            reasons.append(container_result.stderr.strip()[-750:])
        return {"status": "unavailable", "reason": "\n---\n".join(reasons)}
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_metrics(project_root: Path, output: Path) -> dict[str, Any]:
    coverage_path = output / "coverage.json"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--cov=anaxigraph",
        f"--cov-report=json:{coverage_path}",
        "--cov-report=term",
    ]
    result = subprocess.run(command, cwd=project_root, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"baseline test run failed:\n{result.stdout}\n{result.stderr}")
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    match = re.search(r"(\d+) passed", result.stdout)
    return {
        "tests_passed": int(match.group(1)) if match else None,
        "total_coverage_percent": coverage["totals"]["percent_covered"],
        "path_coverage_percent": {
            "cli": _file_coverage(coverage, "src/anaxigraph/cli.py"),
            "history": _file_coverage(coverage, "src/anaxigraph/history.py"),
            "storage_and_migrations": _file_coverage(coverage, "src/anaxigraph/storage.py"),
        },
    }


def environment(project_root: Path) -> dict[str, Any]:
    revision = subprocess.check_output(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "-C", str(project_root), "status", "--porcelain"], text=True
        ).strip()
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "anaxigraph_version": __version__,
        "anaxigraph_revision": revision,
        "working_tree_dirty": dirty,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "sqlite": sqlite3.sqlite_version,
    }


def _resident_bytes() -> int:
    statm = Path("/proc/self/statm")
    if statm.exists():
        pages = int(statm.read_text(encoding="ascii").split()[1])
        return pages * int(os.sysconf("SC_PAGE_SIZE"))
    if resource is None:
        return 0
    maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum if sys.platform == "darwin" else maximum * 1_024


def _wait_for_server(url: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("dashboard benchmark server did not start")


def _container_dashboard_render(
    project_root: Path, url: str
) -> subprocess.CompletedProcess[str] | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    return subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "--network",
            "host",
            "--volume",
            f"{project_root}:/work:ro",
            "--workdir",
            "/work",
            "mcr.microsoft.com/playwright:v1.61.1-noble",
            "node",
            "benchmarks/dashboard_render.mjs",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _file_coverage(coverage: dict[str, Any], path: str) -> float | None:
    details = coverage["files"].get(path)
    return details["summary"]["percent_covered"] if details else None
