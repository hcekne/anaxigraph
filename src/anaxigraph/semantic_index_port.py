"""Narrow persistence interface required by semantic application services."""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Any, Protocol


class SemanticIndex(Protocol):
    def connect(self) -> sqlite3.Connection: ...

    def transaction(self) -> AbstractContextManager[sqlite3.Connection]: ...

    def latest_snapshot(self, repository_id: int) -> dict[str, Any] | None: ...

    def resolve_snapshot(
        self, repository_id: int, snapshot_id: int | None
    ) -> dict[str, Any] | None: ...
