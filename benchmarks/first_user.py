"""Measure the supported local path from an empty checkout to the first compact graph annotation."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anaxigraph.semantic_agent_protocol import rehydrate_agent_request
from anaxigraph.semantic_contract import SEMANTIC_SCHEMA_VERSION


def measure_first_user_path(root: Path, *, runs: int = 3) -> dict[str, Any]:
    results = []
    with tempfile.TemporaryDirectory(prefix="anaxigraph-first-user-") as temporary:
        work = Path(temporary)
        for index in range(1, runs + 1):
            results.append(_run_trial(root, work, index))
    dashboard = [float(item["dashboard_seconds"]) for item in results]
    annotations = [float(item["first_annotation_seconds"]) for item in results]
    return {
        "status": "complete",
        "measurement_kind": "synthetic_first_user_runtime_no_model",
        "runs": results,
        "median_dashboard_seconds": statistics.median(dashboard),
        "median_first_annotation_seconds": statistics.median(annotations),
        "budgets": {"dashboard_seconds": 300, "first_annotation_seconds": 600},
    }


def _run_trial(root: Path, work: Path, index: int) -> dict[str, Any]:
    repository = _create_repository(work / f"repository-{index}")
    database = work / f"state-{index}/anaxi-index.db"
    port = _available_port()
    log_path = work / f"runtime-{index}.log"
    command = _runtime_command(repository, database, port)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=root, stdout=log, stderr=subprocess.STDOUT, text=True
        )
        try:
            _wait_for_health(process, port, log_path)
            dashboard_seconds = time.monotonic() - started
            submission = asyncio.run(
                _submit_first_annotation(f"http://127.0.0.1:{port}/executor/mcp")
            )
            first_annotation_seconds = time.monotonic() - started
        finally:
            _stop_runtime(process)
    if process.returncode != 0:
        raise RuntimeError(f"local runtime did not stop cleanly:\n{log_path.read_text()}")
    return {
        "run": index,
        "dashboard_seconds": round(dashboard_seconds, 3),
        "first_annotation_seconds": round(first_annotation_seconds, 3),
        "submission_status": submission["status"],
        "artifact": submission["artifact"],
        "function_count": submission["functions"],
        "evidence_pages": submission["evidence_pages"],
        "command": command[3:],
        "project_connection_created": (repository / ".codex/config.toml").is_file(),
        "index_created": database.is_file(),
    }


def _runtime_command(repository: Path, database: Path, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "anaxigraph",
        "up",
        str(repository),
        "--db",
        str(database),
        "--port",
        str(port),
        "--history-snapshots",
        "0",
        "--semantic",
        "agent",
        "--connect",
        "codex",
        "--connect-scope",
        "project",
    ]


def _create_repository(repository: Path) -> Path:
    (repository / "src").mkdir(parents=True)
    (repository / "src/app.py").write_text(
        '"""First-user architecture fixture."""\n\n'
        "def greet(name: str) -> str:\n"
        "    return f'Hello {name}'\n",
        encoding="utf-8",
    )
    (repository / ".anaxigraph.yml").write_text(
        "semantic:\n  enabled: true\n  provider: agent\n  detailed_reviews: false\n  include: [src/**]\n",
        encoding="utf-8",
    )
    commands = (
        ("init", "--initial-branch=main"),
        ("config", "user.name", "AnaxiGraph first-user gate"),
        ("config", "user.email", "first-user@anaxigraph.invalid"),
        ("add", "."),
        ("commit", "-qm", "Initial fixture"),
    )
    for command in commands:
        subprocess.run(["git", "-C", str(repository), *command], check=True, capture_output=True)
    return repository


def _wait_for_health(process: subprocess.Popen[str], port: int, log_path: Path) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz", timeout=0.5
            ) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"dashboard did not become healthy:\n{log_path.read_text()}")


async def _submit_first_annotation(mcp_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as http_client:
        async with streamable_http_client(
            mcp_url,
            http_client=http_client,
            terminate_on_close=False,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                work = await session.call_tool(
                    "ANAXIGRAPH_SEMANTIC_WORK",
                    arguments={"agent_id": "first-user-gate", "agent_model": "fixture"},
                )
                packet = work.structuredContent
                if packet["status"] != "work":
                    raise RuntimeError(f"semantic work was not available: {packet['status']}")
                schema = await session.call_tool(
                    "ANAXIGRAPH_SEMANTIC_SCHEMA",
                    arguments=packet["response_contract"]["schema_arguments"],
                )
                if (
                    schema.isError
                    or schema.structuredContent["schema_version"] != SEMANTIC_SCHEMA_VERSION
                ):
                    raise RuntimeError("unexpected semantic graph annotation schema")
                if (
                    packet["job"]["kind"] != "annotation"
                    or schema.structuredContent["artifact"] != "graph_annotation"
                ):
                    raise RuntimeError(
                        "first semantic work did not use the graph annotation contract"
                    )
                pages = await _fetch_evidence_pages(session, packet)
                request = rehydrate_agent_request(packet["analysis_request"], pages)
                submitted = await session.call_tool(
                    "ANAXIGRAPH_SEMANTIC_SUBMIT",
                    arguments={
                        "job_id": packet["job"]["id"],
                        "lease_token": packet["lease"]["token"],
                        "dossier": _annotation(request),
                    },
                )
                if submitted.isError:
                    raise RuntimeError(f"annotation submission failed: {submitted.content}")
                status = submitted.structuredContent["status"]
                if status not in {"completed", "already_completed"}:
                    raise RuntimeError(f"semantic submission failed: {status}")
                return {
                    "status": status,
                    "evidence_pages": len(pages),
                    "artifact": "graph_annotation",
                    "functions": len(request["functions"]),
                }


async def _fetch_evidence_pages(
    session: ClientSession, packet: dict[str, Any]
) -> list[dict[str, Any]]:
    manifest = packet.get("evidence_manifest") or {}
    page_count = int(manifest.get("page_count") or 0)
    pages = []
    for page in range(1, page_count + 1):
        result = await session.call_tool(
            "ANAXIGRAPH_SEMANTIC_EVIDENCE",
            arguments={
                "job_id": packet["job"]["id"],
                "lease_token": packet["lease"]["token"],
                "page": page,
            },
        )
        if result.structuredContent["status"] != "evidence":
            raise RuntimeError(f"semantic evidence page {page} was unavailable")
        pages.append(result.structuredContent)
    return pages


def _annotation(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "overview": "Returns a greeting for the supplied name.",
        "detail": "The fixture exposes one greeting function with no external side effects.",
        "functions": [
            {
                "qualified_name": item["qualified_name"],
                "overview": "Returns a greeting for the supplied name.",
            }
            for item in request["functions"]
        ],
        "contracts": [],
        "capabilities": [],
        "evidence": [request["path"]],
        "confidence": 0.9,
    }


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _stop_runtime(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.runs < 1:
        raise ValueError("runs must be at least one")
    root = Path(__file__).resolve().parents[1]
    report = measure_first_user_path(root, runs=args.runs)
    content = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)
    budgets = report["budgets"]
    return int(
        report["median_dashboard_seconds"] >= budgets["dashboard_seconds"]
        or report["median_first_annotation_seconds"] >= budgets["first_annotation_seconds"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
