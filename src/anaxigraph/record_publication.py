"""Checkpoint shared results during explicit workflows without coupling them to Git pushes."""

from __future__ import annotations

import time
from threading import Event, Thread
from typing import Any

from anaxigraph.portable_record import save_record


class RecordPublisher:
    def __init__(self, database: Any, repository_id: int, *, interval: float = 30) -> None:
        self.database, self.repository_id = database, repository_id
        self.interval, self.last_saved = interval, time.monotonic()
        self.receipt: dict[str, Any] = {"status": "not_saved"}
        self.stopped = Event()
        self.thread = Thread(target=self._checkpoint, daemon=True, name="anaxigraph-record-save")

    def __enter__(self) -> RecordPublisher:
        self.thread.start()
        return self

    def __exit__(self, *error: Any) -> None:
        self.stopped.set()
        self.thread.join()
        self.save()

    def _checkpoint(self) -> None:
        while not self.stopped.wait(self.interval):
            self.update()

    def update(self, **progress: Any) -> None:
        if time.monotonic() - self.last_saved >= self.interval:
            self.save()

    def save(self) -> dict[str, Any]:
        try:
            self.receipt = save_record(self.database, self.repository_id)
        except (OSError, ValueError) as error:
            self.receipt = {
                "status": "not_saved",
                "message": str(error),
                "action": "Results remain in the local index. Save from a service with write access to the reserved anaxigraph/ directory.",
            }
        self.last_saved = time.monotonic()
        return self.receipt
