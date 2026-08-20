"""Loopback-first runtime for evaluating AnaxiGraph without Docker."""

from __future__ import annotations

import hashlib
import os
import platform
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import uvicorn

from anaxigraph.registry import HistorySnapshots


@dataclass(frozen=True, slots=True)
class LocalRuntime:
    repository: Path
    config_path: Path
    database_path: Path
    port: int = 8765
    history_snapshots: HistorySnapshots = "auto"
    open_browser: bool = False

    @property
    def dashboard_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def mcp_url(self) -> str:
        return f"{self.dashboard_url}/mcp"


def local_database_path(
    repository: Path,
    *,
    explicit: Path | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    system: str | None = None,
) -> Path:
    """Return a stable per-checkout index path outside the target repository."""

    if explicit is not None:
        return explicit.expanduser().resolve()
    environment = os.environ if environment is None else environment
    configured = environment.get("ANAXIGRAPH_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    root = local_state_root(environment=environment, home=home, system=system)
    resolved = repository.expanduser().resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    readable = "".join(character if character.isalnum() else "-" for character in resolved.name)
    slug = "-".join(part for part in readable.lower().split("-") if part) or "repository"
    return root / "repositories" / f"{slug[:40]}-{digest}" / "anaxi-index.db"


def local_state_root(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    system: str | None = None,
) -> Path:
    environment = os.environ if environment is None else environment
    configured = environment.get("ANAXIGRAPH_STATE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    home = Path.home() if home is None else home.expanduser().resolve()
    system = platform.system() if system is None else system
    if system == "Darwin":
        return home / "Library" / "Application Support" / "AnaxiGraph"
    if system == "Windows":
        base = Path(environment.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return base.expanduser().resolve() / "AnaxiGraph"
    xdg_state = environment.get("XDG_STATE_HOME")
    return (
        Path(xdg_state).expanduser().resolve() / "anaxigraph"
        if xdg_state
        else (home / ".local" / "state" / "anaxigraph")
    )


def assert_port_available(port: int) -> None:
    if not 1 <= port <= 65_535:
        raise ValueError("Port must be between 1 and 65535")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                f"Loopback port {port} is already in use. Stop the existing service or choose "
                "--port with another value."
            ) from exc


def build_local_app(runtime: LocalRuntime, *, index_factory: Any, app_factory: Any) -> Any:
    database = index_factory(runtime.database_path)
    return app_factory(
        database=database,
        repository=runtime.repository,
        config_path=runtime.config_path,
        scan_on_start=True,
        enable_mcp=True,
        allow_scan_tool=True,
        repository_history_snapshots=runtime.history_snapshots,
    )


def run_local_service(runtime: LocalRuntime, *, index_factory: Any, app_factory: Any) -> None:
    _prepare_state_directory(runtime.database_path.parent)
    app = build_local_app(runtime, index_factory=index_factory, app_factory=app_factory)
    if runtime.open_browser:
        threading.Thread(
            target=_open_when_ready,
            args=(runtime.dashboard_url,),
            name="anaxigraph-browser",
            daemon=True,
        ).start()
    uvicorn.run(app, host="127.0.0.1", port=runtime.port, log_level="info")


def print_runtime_banner(runtime: LocalRuntime, *, restart_command: str) -> None:
    print("AnaxiGraph local runtime", file=sys.stderr)
    print(f"  Repository: {runtime.repository}", file=sys.stderr)
    print(f"  AnaxiIndex: {runtime.database_path}", file=sys.stderr)
    print(f"  Dashboard:  {runtime.dashboard_url}", file=sys.stderr)
    print(f"  MCP:        {runtime.mcp_url}", file=sys.stderr)
    print("  Startup:    current scan, then adaptive history in the background", file=sys.stderr)
    print("  Agent scan: enabled for this loopback-only service", file=sys.stderr)
    print("  Stop:       Ctrl-C (history progress is durable and resumes)", file=sys.stderr)
    print(f"  Restart:    {restart_command}", file=sys.stderr)


def _prepare_state_directory(directory: Path) -> None:
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name == "posix":
        directory.chmod(0o700)


def _open_when_ready(url: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    health_url = f"{url}/healthz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(0.1)
