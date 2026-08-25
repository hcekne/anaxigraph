"""Per-repository admission control for expensive HTTP-triggered work."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Admission:
    allowed: bool
    reason: str
    retry_after_seconds: float


class RepositoryOperationGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[tuple[int, str], str] = {}
        self._last_started: dict[tuple[int, str], float] = {}

    def acquire(
        self,
        repository_id: int,
        operation: str,
        *,
        cooldown_seconds: float,
        hold: bool,
    ) -> Admission:
        key = (repository_id, operation)
        now = time.monotonic()
        with self._lock:
            if key in self._active:
                return Admission(False, "already_running", cooldown_seconds)
            remaining = cooldown_seconds - (now - self._last_started.get(key, 0.0))
            if remaining > 0:
                return Admission(False, "rate_limited", round(remaining, 3))
            self._last_started[key] = now
            if hold:
                self._active[key] = datetime.now(UTC).isoformat()
        return Admission(True, "admitted", 0.0)

    def release(self, repository_id: int, operation: str) -> None:
        with self._lock:
            self._active.pop((repository_id, operation), None)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = [
                {
                    "repository_id": repository_id,
                    "operation": operation,
                    "started_at": started_at,
                }
                for (repository_id, operation), started_at in sorted(self._active.items())
            ]
        return {"active": active, "active_count": len(active)}
