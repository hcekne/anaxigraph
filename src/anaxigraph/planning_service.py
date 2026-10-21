"""Prepare optional planning through the shared semantic application facade."""

from __future__ import annotations

from typing import Any

from anaxigraph.architecture_plan import request_plan
from anaxigraph.understanding import SemanticEngine


def prepare_architecture_plan(
    database: Any, repository_id: int, root: Any, config: Any, direction: str = ""
) -> None:
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        raise ValueError("Scan the repository before architecture planning")
    with database.transaction() as connection:
        request_plan(connection, repository_id, snapshot["id"], direction)
    SemanticEngine(database).plan(repository_id, root, config)
