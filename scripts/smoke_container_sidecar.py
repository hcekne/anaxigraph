#!/usr/bin/env python3
"""Build and exercise the generated hardened Docker sidecar end to end."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_REPOSITORY_TIMEOUT_SECONDS = 120.0
MCP_REPOSITORY_POLL_SECONDS = 0.25


def smoke_container_sidecar(root: Path, *, image: str, build: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    if build:
        _run(["docker", "build", "--tag", image, "."], cwd=root)
    build_seconds = time.monotonic() - started
    with tempfile.TemporaryDirectory(prefix="anaxigraph-container-gate-") as temporary:
        work = Path(temporary)
        repository = _create_repository(work / "repository")
        port = _available_port()
        project_name = f"Container gate {os.getpid()} {port}"
        _run(
            [
                sys.executable,
                "-m",
                "anaxigraph",
                "init",
                str(repository),
                "--project-name",
                project_name,
                "--image",
                image,
                "--port",
                str(port),
                "--history-snapshots",
                "0",
                "--semantic",
                "agent",
                "--json",
            ],
            cwd=root,
        )
        compose = repository / "compose.anaxigraph.yml"
        command = ["docker", "compose", "-f", str(compose)]
        service_started = time.monotonic()
        try:
            _run([*command, "up", "-d"], cwd=repository)
            health = _wait_for_health(port, command, repository)
            mcp = asyncio.run(_mcp_evidence(f"http://127.0.0.1:{port}/mcp"))
            container_id = _run([*command, "ps", "-q", "anaxigraph"], cwd=repository).stdout.strip()
            hardening = _inspect_hardening(container_id)
        finally:
            _run([*command, "down", "--volumes", "--remove-orphans"], cwd=repository)
        return {
            "status": "complete",
            "image": image,
            "build_seconds": round(build_seconds, 3),
            "healthy_seconds": round(time.monotonic() - service_started, 3),
            "health": health,
            "mcp_repositories": len(mcp["repositories"]),
            "repository_files": mcp["overview"]["files"],
            "parser_files": mcp["overview"]["graph_quality"]["parser_files"],
            "hardening": hardening,
        }


def _create_repository(repository: Path) -> Path:
    repository.mkdir(parents=True)
    (repository / "app.py").write_text(
        '"""Container smoke fixture."""\n\ndef ready() -> bool:\n    return True\n',
        encoding="utf-8",
    )
    (repository / "view.tsx").write_text(
        "export const View = () => <main>AnaxiGraph</main>;\n",
        encoding="utf-8",
    )
    for command in (
        ("init", "--initial-branch=main"),
        ("config", "user.name", "AnaxiGraph container gate"),
        ("config", "user.email", "container@anaxigraph.invalid"),
        ("add", "."),
        ("commit", "-qm", "Initial fixture"),
    ):
        _run(["git", "-C", str(repository), *command], cwd=repository)
    return repository


def _wait_for_health(port: int, compose: list[str], cwd: Path) -> dict[str, Any]:
    deadline = time.monotonic() + 120
    url = f"http://127.0.0.1:{port}/healthz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return json.loads(response.read())
        except OSError:
            time.sleep(0.25)
    logs = _run([*compose, "logs", "--no-color"], cwd=cwd, check=False).stdout
    raise RuntimeError(f"container did not become healthy:\n{logs}")


async def _mcp_evidence(url: str) -> dict[str, Any]:
    async with streamable_http_client(url, terminate_on_close=False) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            repositories = await _wait_for_mcp_repository(session)
            overview = await session.call_tool(
                "ANAXIGRAPH_OVERVIEW",
                arguments={"repository": str(repositories[0]["id"])},
            )
            if overview.isError:
                raise RuntimeError("container MCP overview query failed")
            content = overview.structuredContent or {}
            if content.get("graph_quality", {}).get("parser_files") != 1:
                raise RuntimeError("container did not load the parser-backed TypeScript analyzer")
            return {"repositories": repositories, "overview": content}


async def _wait_for_mcp_repository(
    session: Any,
    *,
    timeout_seconds: float = MCP_REPOSITORY_TIMEOUT_SECONDS,
    poll_seconds: float = MCP_REPOSITORY_POLL_SECONDS,
) -> list[dict[str, Any]]:
    """Wait until startup scanning makes the configured repository queryable."""
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while True:
        result = await session.call_tool("ANAXIGRAPH_REPOSITORIES", arguments={})
        if result.isError:
            last_error = " ".join(
                str(getattr(item, "text", ""))
                for item in (getattr(result, "content", None) or [])
                if getattr(item, "text", "")
            )[:1_000]
        else:
            content = result.structuredContent or {}
            repositories = content.get("repositories") or []
            if repositories:
                return repositories
        if time.monotonic() >= deadline:
            detail = f" Last repository-list error: {last_error}" if last_error else ""
            raise RuntimeError(
                "container became healthy, but its startup scan did not expose a repository "
                f"within {timeout_seconds:g} seconds.{detail}"
            )
        await asyncio.sleep(poll_seconds)


def _inspect_hardening(container_id: str) -> dict[str, Any]:
    if not container_id:
        raise RuntimeError("Compose did not return an AnaxiGraph container id")
    inspected = json.loads(_run(["docker", "inspect", container_id]).stdout)[0]
    host = inspected["HostConfig"]
    repository_mount = next(item for item in inspected["Mounts"] if item["Destination"] == "/repo")
    bindings = inspected["NetworkSettings"]["Ports"]["8765/tcp"]
    result = {
        "read_only_root": bool(host["ReadonlyRootfs"]),
        "cap_drop_all": "ALL" in (host.get("CapDrop") or []),
        "no_new_privileges": "no-new-privileges:true" in (host.get("SecurityOpt") or []),
        "repository_read_only": not repository_mount["RW"],
        "loopback_bind": all(item["HostIp"] == "127.0.0.1" for item in bindings),
    }
    if not all(result.values()):
        raise RuntimeError(f"container hardening contract failed: {result}")
    return result


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}{result.stderr}"
        )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="anaxigraph:phase3-gate")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    report = smoke_container_sidecar(root, image=args.image, build=not args.no_build)
    content = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
