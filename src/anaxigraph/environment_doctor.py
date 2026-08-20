"""End-to-end diagnostics for repository, index, service, MCP, and client setup."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from anaxigraph import __version__, git
from anaxigraph.onboarding_clients import client_connection_status, validate_mcp_url
from anaxigraph.onboarding_detection import repository_policy_details
from anaxigraph.persistence import inspect_index


def inspect_environment(
    database_path: Path,
    connect: Callable[..., Any],
    *,
    repository: Path,
    config_path: Path | None = None,
    service_url: str | None = None,
    client: str | None = None,
    connection_scope: str = "user",
    expected_mcp_url: str | None = None,
    home: Path | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    repository = repository.expanduser().resolve()
    index_report = inspect_index(database_path, connect)
    repository_report = _inspect_repository(repository, config_path)
    database_report = _inspect_database_path(database_path)
    service_report, mcp_report = _inspect_service(service_url, expected_mcp_url, timeout)
    client_report = _inspect_client(
        client,
        connection_scope,
        repository,
        expected_mcp_url or _mcp_url(service_url),
        home,
    )
    checks = {
        "repository": repository_report,
        "database": database_report,
        "service": service_report,
        "mcp": mcp_report,
        "client": client_report,
    }
    failures = [name for name, check in checks.items() if check["status"] == "failed"]
    warnings = [name for name, check in checks.items() if check["status"] == "warning"]
    index_blockers = list(index_report.get("blockers", []))
    if index_report.get("status") == "blocked":
        failures.append("index")
    status = "blocked" if failures else "degraded" if warnings else "healthy"
    return {
        **index_report,
        "status": status,
        "environment": {
            "status": status,
            "checks": checks,
            "failures": failures,
            "warnings": warnings,
        },
        "blockers": [*index_blockers, *(f"environment:{name}" for name in failures)],
    }


def _inspect_repository(repository: Path, config_path: Path | None) -> dict[str, Any]:
    selected_config = (
        config_path.expanduser().resolve() if config_path else repository / ".anaxigraph.yml"
    )
    if not repository.is_dir():
        return {
            "status": "failed",
            "path": str(repository),
            "message": "Repository directory does not exist",
        }
    readable = os.access(repository, os.R_OK | os.X_OK)
    report = {
        "status": "ok" if readable else "failed",
        "path": str(repository),
        "readable": readable,
        "writable": os.access(repository, os.W_OK),
        "git_repository": git.is_repository(repository),
        "config_path": str(selected_config),
        "config_present": selected_config.is_file(),
    }
    if not readable:
        report["message"] = "Repository mount is not readable"
        return report
    try:
        details = repository_policy_details(
            repository, selected_config if selected_config.exists() else None
        )
        report.update(details)
    except (OSError, ValueError) as exc:
        report.update(status="failed", message=f"Repository policy is invalid: {exc}")
    if not report["git_repository"] and report["status"] == "ok":
        report.update(status="warning", message="Directory is readable but is not a Git worktree")
    return report


def _inspect_database_path(database_path: Path) -> dict[str, Any]:
    database_path = database_path.expanduser().resolve()
    parent = database_path.parent
    report = {
        "status": "ok",
        "path": str(database_path),
        "exists": database_path.is_file(),
        "parent": str(parent),
        "writable": False,
    }
    try:
        with tempfile.NamedTemporaryFile(prefix=".anaxigraph-doctor-", dir=parent):
            report["writable"] = True
    except OSError as exc:
        report.update(status="failed", message=f"Index directory is not writable: {exc}")
    return report


def _inspect_service(
    service_url: str | None,
    expected_mcp_url: str | None,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if service_url is None:
        return ({"status": "skipped"}, {"status": "skipped"})
    root = validate_mcp_url(service_url)
    health_url = f"{root}/healthz"
    try:
        request = urllib.request.Request(health_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") != "ok":
            raise ValueError(f"unexpected health payload: {payload!r}")
        service = {"status": "ok", "url": root, "health_url": health_url}
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        failed = {"status": "failed", "url": root, "message": str(exc)}
        return failed, {"status": "failed", "url": _mcp_url(root), "message": "not attempted"}
    mcp_url = validate_mcp_url(expected_mcp_url or _mcp_url(root))
    return service, _initialize_mcp(mcp_url, timeout)


def _initialize_mcp(mcp_url: str, timeout: float) -> dict[str, Any]:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "anaxigraph-doctor", "version": __version__},
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        mcp_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        server = result.get("result", {}).get("serverInfo", {})
        if server.get("name") != "AnaxiMCP":
            raise ValueError(f"endpoint initialized an unexpected MCP server: {server!r}")
        return {
            "status": "ok",
            "url": mcp_url,
            "server": server,
            "protocol_version": result["result"].get("protocolVersion"),
        }
    except (OSError, KeyError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        return {"status": "failed", "url": mcp_url, "message": str(exc)}


def _inspect_client(
    client: str | None,
    scope: str,
    repository: Path,
    expected_url: str | None,
    home: Path | None,
) -> dict[str, Any]:
    if client is None:
        return {"status": "skipped"}
    expected_url = validate_mcp_url(expected_url or "http://127.0.0.1:8765/mcp")
    report = client_connection_status(
        client,
        scope=scope,
        repository=repository,
        expected_url=expected_url,
        home=home,
    )
    report["status"] = "ok" if report["status"] == "configured" else "failed"
    return report


def _mcp_url(service_url: str | None) -> str | None:
    return f"{service_url.rstrip('/')}/mcp" if service_url else None
