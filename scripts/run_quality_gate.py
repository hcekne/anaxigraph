#!/usr/bin/env python3
"""Run the complete local AnaxiGraph quality gate in CI-equivalent order."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import TextIO

PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.61.1-noble"


def run(command: list[str], *, root: Path, env: dict[str, str] | None = None) -> None:
    print(f"\n→ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=root, env=env, check=True)


def quality_commands(root: Path, *, base: str, skip_benchmark: bool) -> list[list[str]]:
    commands = [
        ["uv", "run", "pre-commit", "run", "--all-files"],
        [
            "uv",
            "run",
            "pytest",
            "--cov=anaxigraph",
            "--cov-report=term-missing",
            "--cov-report=xml",
            "--cov-fail-under=80",
        ],
        [
            "uv",
            "run",
            "python",
            "scripts/check_changed_coverage.py",
            "--report",
            "coverage.xml",
            "--base",
            base,
        ],
        ["docker", "compose", "-f", "compose.yml", "config", "--quiet"],
        [
            "docker",
            "compose",
            "-f",
            "compose.yml",
            "-f",
            "compose.maxos.yml",
            "config",
            "--quiet",
        ],
    ]
    if not skip_benchmark:
        commands.append(
            [
                "uv",
                "run",
                "python",
                "-m",
                "benchmarks.baseline",
                "--repository",
                str(root),
                "--synthetic-files",
                "120",
                "--history-frames",
                "8",
                "--skip-tests",
                "--skip-dashboard",
            ]
        )
    return commands


def run_browser_contracts(root: Path, *, runner: str) -> None:
    env = dict(os.environ)
    env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
    run(["npm", "ci"], root=root, env=env)
    with tempfile.TemporaryDirectory(prefix="anaxigraph-quality-") as temporary:
        work = Path(temporary)
        repository = work / "repository"
        database = work / "anaxi-index.db"
        log_path = work / "server.log"
        port = _available_port()
        run(
            ["uv", "run", "python", "-m", "benchmarks.dashboard_fixture", str(repository)],
            root=root,
        )
        with log_path.open("w", encoding="utf-8") as log:
            server = _start_server(root, repository, database, port, log)
            try:
                _wait_until_ready(port, server, log_path)
                if runner == "host":
                    browser_env = dict(os.environ)
                    browser_env["ANAXIGRAPH_VISUAL_URL"] = f"http://127.0.0.1:{port}"
                    run(["npm", "run", "test:visual"], root=root, env=browser_env)
                else:
                    run(_container_browser_command(root, port), root=root)
            finally:
                _stop_server(server)


def _start_server(
    root: Path,
    repository: Path,
    database: Path,
    port: int,
    log: TextIO,
) -> subprocess.Popen[str]:
    command = [
        "uv",
        "run",
        "anaxigraph",
        "serve",
        "--repository",
        str(repository),
        "--db",
        str(database),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--scan-on-start",
    ]
    print(f"\n→ {' '.join(command)}", flush=True)
    return subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, text=True)


def _wait_until_ready(port: int, server: subprocess.Popen[str], log_path: Path) -> None:
    url = f"http://127.0.0.1:{port}/healthz"
    for _attempt in range(120):
        if server.poll() is not None:
            raise RuntimeError(
                f"fixture server exited early:\n{log_path.read_text(encoding='utf-8')}"
            )
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(
        f"fixture server did not become ready:\n{log_path.read_text(encoding='utf-8')}"
    )


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _container_browser_command(root: Path, port: int) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--add-host",
        "host.docker.internal:host-gateway",
        "-e",
        f"ANAXIGRAPH_VISUAL_URL=http://host.docker.internal:{port}",
        "-e",
        "PLAYWRIGHT_OUTPUT_DIR=/tmp/test-results",
        "-e",
        "PLAYWRIGHT_HTML_OUTPUT_DIR=/tmp/playwright-report",
        "-v",
        f"{root}:/work:ro",
        "-w",
        "/work",
        PLAYWRIGHT_IMAGE,
        "npm",
        "run",
        "test:visual",
    ]


def _stop_server(server: subprocess.Popen[str]) -> None:
    if server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD^", help="Git base for changed-code coverage")
    parser.add_argument("--browser-runner", choices=("container", "host"), default="container")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--skip-benchmark", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    for command in quality_commands(root, base=args.base, skip_benchmark=args.skip_benchmark):
        run(command, root=root)
    if not args.skip_browser:
        run_browser_contracts(root, runner=args.browser_runner)
    print("\nComplete AnaxiGraph quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
