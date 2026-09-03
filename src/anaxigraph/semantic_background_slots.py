"""Per-executor run slots: where a detached worker's record lives and whether it is still live.

One repository has one background run slot per executor, so a Codex worker and a Claude worker can
own the same repository at the same time without sharing a run record or a lock. Records written
before per-executor slots existed live in the repository-only slot and are still read for the
executor they name.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anaxigraph.local_runtime import local_state_root

LATEST_RECORD = "latest.json"
_STOPPED_PROCESS_STATES = frozenset({"T", "t", "Z", "X"})


def slot_directory(repository: Path, executor: str = "") -> Path:
    """Name one repository-and-executor run directory; no executor names the legacy slot."""

    digest = _repository_digest(repository)
    slot = _slot_name(executor)
    return local_state_root() / "semantic-runs" / (f"{digest}-{slot}" if slot else digest)


def semantic_background_status(repository: Path, executor: str = "") -> dict[str, Any] | None:
    """Read one executor's detached-run state, or the most relevant run of any executor."""

    if not executor:
        runs = semantic_background_runs(repository)
        return runs[0] if runs else None
    record = slot_record(slot_directory(repository, executor))
    if record is not None:
        return record
    legacy = slot_record(slot_directory(repository))
    return legacy if legacy and str(legacy.get("executor") or "") == executor else None


def semantic_background_runs(repository: Path) -> list[dict[str, Any]]:
    """Report one run record per executor slot, running workers first, newest first after that."""

    found: dict[str, dict[str, Any]] = {}
    for directory in _slot_directories(repository):
        record = slot_record(directory)
        if record is not None:
            found.setdefault(str(record.get("executor") or ""), record)
    return sorted(
        found.values(),
        key=lambda item: (bool(item.get("active")), str(item.get("started_at") or "")),
        reverse=True,
    )


def slot_record(directory: Path) -> dict[str, Any] | None:
    """Read one slot's latest record and detect an orphaned or stalled process."""

    latest_path = directory / LATEST_RECORD
    if not latest_path.exists():
        return None
    try:
        record = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": "unreadable", "active": False, "state_path": str(latest_path)}
    status = str(record.get("status") or "unknown")
    pid = int(record.get("pid") or 0)
    active = status == "starting" and recent(record)
    if status == "running":
        process_alive = pid_exists(pid)
        stalled = process_alive and (heartbeat_expired(record) or worker_is_stopped(record))
        active = process_alive and not stalled
        if stalled:
            record["status"] = "stalled"
        elif not process_alive:
            record["status"] = "interrupted"
    elif status == "starting" and not active:
        record["status"] = "interrupted"
    record["active"] = active
    return public_record(record)


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Report a run without its spawn command, and with how long it has been running."""

    result = {key: value for key, value in record.items() if key != "command"}
    try:
        started = datetime.fromisoformat(str(record["started_at"]))
        finished = (
            datetime.fromisoformat(str(record["finished_at"]))
            if record.get("finished_at")
            else datetime.now(UTC)
        )
        result["elapsed_ms"] = round(max(0.0, (finished - started).total_seconds() * 1_000), 3)
    except (KeyError, TypeError, ValueError):
        result["elapsed_ms"] = None
    return result


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def worker_is_stopped(record: dict[str, Any]) -> bool:
    worker_pid = int(record.get("worker_pid") or record.get("pid") or 0)
    return _process_state(worker_pid) in _STOPPED_PROCESS_STATES


def heartbeat_expired(record: dict[str, Any]) -> bool:
    try:
        heartbeat = datetime.fromisoformat(str(record["heartbeat_at"]))
        timeout = max(1, int(record.get("heartbeat_timeout_seconds") or 360))
    except (KeyError, TypeError, ValueError):
        return True
    return (datetime.now(UTC) - heartbeat).total_seconds() > timeout


def recent(record: dict[str, Any], seconds: int = 60) -> bool:
    try:
        started = datetime.fromisoformat(str(record["started_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    return (datetime.now(UTC) - started).total_seconds() < seconds


def now() -> str:
    return datetime.now(UTC).isoformat()


def _slot_directories(repository: Path) -> list[Path]:
    digest = _repository_digest(repository)
    root = local_state_root() / "semantic-runs"
    executors = sorted(root.glob(f"{digest}-*")) if root.exists() else []
    return [*executors, root / digest]


def _repository_digest(repository: Path) -> str:
    resolved = str(repository.expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def _slot_name(executor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(executor).lower()).strip("-")[:16]


def _process_state(pid: int) -> str:
    if os.name != "posix" or pid <= 0:
        return ""
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except (OSError, IndexError):
        return ""
