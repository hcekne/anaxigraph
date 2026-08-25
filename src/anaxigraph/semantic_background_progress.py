"""Progress heartbeat written by a detached semantic command for its wrapper."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROGRESS_PATH_ENV = "ANAXIGRAPH_SEMANTIC_PROGRESS_PATH"


def report_background_progress(
    *,
    stage: str | None = None,
    completed: int | None = None,
    last_error: str | None = None,
) -> None:
    """Refresh detached-run progress when this process belongs to a wrapper."""

    configured = os.environ.get(PROGRESS_PATH_ENV)
    if not configured:
        return
    payload: dict[str, Any] = {"heartbeat_at": datetime.now(UTC).isoformat()}
    if stage:
        payload["stage"] = stage
    if completed is not None:
        payload["completed"] = max(0, int(completed))
    if last_error:
        payload["last_error"] = str(last_error)[:1_000]
    _atomic_write(Path(configured), payload)


def read_background_progress(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        if os.name == "posix":
            temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError:
        return
