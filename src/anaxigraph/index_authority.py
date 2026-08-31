"""Exclusive long-running process authority for one AnaxiIndex."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout


class IndexWriteAuthority:
    """Prevent multiple serving/watching processes from owning one index."""

    def __init__(self, index_path: str | Path) -> None:
        self.index_path = Path(index_path).expanduser().resolve()
        self._file_lock = FileLock(f"{self.index_path}.writer.lock")
        self._state_lock = threading.Lock()
        self._owner: str | None = None

    @contextlib.contextmanager
    def claim(self, owner: str) -> Iterator[None]:
        try:
            self._file_lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError(
                "Another AnaxiGraph server or watcher already owns this AnaxiIndex; "
                "use the running service instead of starting a second writer"
            ) from exc
        with self._state_lock:
            self._owner = owner
        try:
            yield
        finally:
            with self._state_lock:
                self._owner = None
            self._file_lock.release()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            owner = self._owner
        return {
            "contract_version": "index-write-authority-v1",
            "claimed": owner is not None,
            "owner": owner,
            "index_path": str(self.index_path),
        }
