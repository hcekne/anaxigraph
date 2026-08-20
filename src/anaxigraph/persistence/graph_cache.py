"""Small process-local cache for immutable snapshot graph read models."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any


class GraphReadCache:
    def __init__(self, capacity: int = 4) -> None:
        self._capacity = capacity
        self._values: OrderedDict[tuple[int, int, bool], dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: tuple[int, int, bool]) -> dict[str, Any] | None:
        with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return value

    def put(self, key: tuple[int, int, bool], value: dict[str, Any]) -> None:
        with self._lock:
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self._capacity:
                self._values.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
