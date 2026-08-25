"""Public-index orchestration for module inventory reads."""

from __future__ import annotations

from typing import Any

from anaxigraph.persistence.module_read import read_modules


def index_modules(
    index: Any,
    repository_id: int,
    snapshot_id: int | None,
    *,
    limit: int | None,
    offset: int,
) -> list[dict[str, Any]]:
    snapshot = index._resolve_snapshot(repository_id, snapshot_id)
    if snapshot is None:
        return []
    with index.connect() as connection:
        return read_modules(
            connection,
            repository_id,
            int(snapshot["id"]),
            limit=limit,
            offset=offset,
        )
