"""Public-index orchestration for bounded graph read models."""

from __future__ import annotations

from typing import Any

from anaxigraph.persistence.graph_delta_read import empty_graph_delta, read_graph_delta
from anaxigraph.persistence.graph_neighborhood_read import (
    empty_graph_neighborhood,
    read_graph_neighborhood,
)
from anaxigraph.persistence.graph_page_read import empty_graph_page, read_graph_page


def resolved_graph_snapshot(
    index: Any,
    repository_id: int,
    snapshot_id: int | None,
    label: str,
) -> Any | None:
    """Resolve one snapshot, refusing an explicit id that is unknown or foreign.

    An explicit id that does not resolve is a caller error and must fail loud; only the
    implicit lookup may come back empty, which means the repository was never scanned.
    """

    snapshot = index._resolve_snapshot(repository_id, snapshot_id)
    if snapshot is None and snapshot_id is not None:
        raise ValueError(f"{label} snapshot does not belong to the repository")
    return snapshot


def index_graph_page(
    index: Any,
    repository_id: int,
    snapshot_id: int | None,
    *,
    include_external: bool,
    query: Any | None,
) -> dict[str, Any]:
    snapshot = resolved_graph_snapshot(index, repository_id, snapshot_id, "graph")
    if snapshot is None:
        return empty_graph_page(repository_id)
    with index.connect() as connection:
        return read_graph_page(
            connection,
            repository_id,
            snapshot,
            query,
            include_external=include_external,
        )


def index_graph_neighborhood(
    index: Any,
    repository_id: int,
    snapshot_id: int | None,
    *,
    query: Any,
) -> dict[str, Any]:
    snapshot = resolved_graph_snapshot(index, repository_id, snapshot_id, "graph")
    if snapshot is None:
        return empty_graph_neighborhood(repository_id)
    with index.connect() as connection:
        return read_graph_neighborhood(connection, repository_id, snapshot, query)


def index_graph_delta(
    index: Any,
    repository_id: int,
    baseline_snapshot_id: int,
    target_snapshot_id: int | None,
    *,
    node_limit: int,
    edge_limit: int,
) -> dict[str, Any]:
    baseline = resolved_graph_snapshot(index, repository_id, baseline_snapshot_id, "baseline graph")
    if baseline is None:
        raise ValueError("baseline graph snapshot does not belong to the repository")
    target = resolved_graph_snapshot(index, repository_id, target_snapshot_id, "target graph")
    if target is None:
        return empty_graph_delta(repository_id)
    with index.connect() as connection:
        return read_graph_delta(
            connection,
            repository_id,
            baseline,
            target,
            node_limit=node_limit,
            edge_limit=edge_limit,
        )
