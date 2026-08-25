"""Bounded REST graph query routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query

from anaxigraph.graph_contract import (
    DEFAULT_EDGE_LIMIT,
    DEFAULT_GRAPH_AGGREGATE_EDGE_LIMIT,
    DEFAULT_GRAPH_DELTA_LIMIT,
    DEFAULT_GRAPH_GROUP_LIMIT,
    DEFAULT_NEIGHBOR_EDGE_LIMIT,
    DEFAULT_NEIGHBOR_NODE_LIMIT,
    DEFAULT_NODE_LIMIT,
    MAX_EDGE_LIMIT,
    MAX_GRAPH_AGGREGATE_EDGE_LIMIT,
    MAX_GRAPH_CURSOR_LENGTH,
    MAX_GRAPH_DELTA_LIMIT,
    MAX_GRAPH_GROUP_LIMIT,
    MAX_NEIGHBOR_EDGE_LIMIT,
    MAX_NEIGHBOR_NODE_LIMIT,
    MAX_NODE_LIMIT,
    GraphNeighborhoodRequest,
    GraphPageRequest,
)

RepositorySelector = Callable[[int | None], dict[str, Any]]


def register_graph_routes(
    app: FastAPI,
    database: Any,
    selected_repository: RepositorySelector,
) -> None:
    app.include_router(GraphRoutes(database, selected_repository).router)


class GraphRoutes:
    def __init__(self, database: Any, selected_repository: RepositorySelector) -> None:
        self.database = database
        self.selected_repository = selected_repository
        self.router = APIRouter()
        self.router.add_api_route("/api/graph", self.page, methods=["GET"])
        self.router.add_api_route("/api/graph/overview", self.overview, methods=["GET"])
        self.router.add_api_route("/api/graph/neighbors", self.neighbors, methods=["GET"])
        self.router.add_api_route("/api/graph/delta", self.delta, methods=["GET"])

    def page(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        cursor: str = Query(default="", max_length=MAX_GRAPH_CURSOR_LENGTH),
        node_limit: int = Query(default=DEFAULT_NODE_LIMIT, ge=1, le=MAX_NODE_LIMIT),
        edge_limit: int = Query(default=DEFAULT_EDGE_LIMIT, ge=1, le=MAX_EDGE_LIMIT),
        include_external: bool = False,
        path: str = Query(default="", max_length=2_000),
        language: list[str] = Query(default=[]),
        area: list[str] = Query(default=[]),
        subsystem: list[str] = Query(default=[]),
        finding: list[str] = Query(default=[]),
        relationship: list[str] = Query(default=[]),
    ) -> dict[str, Any]:
        row = self.selected_repository(repository_id)
        try:
            request = GraphPageRequest(
                cursor=cursor,
                node_limit=node_limit,
                edge_limit=edge_limit,
                include_external=include_external,
                path=path,
                languages=tuple(language),
                areas=tuple(area),
                subsystems=tuple(subsystem),
                finding_types=tuple(finding),
                relationship_types=tuple(relationship),
            )
            return self.database.graph(int(row["id"]), snapshot_id, query=request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def overview(
        self,
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        level: str = Query(default="area", pattern="^(area|subsystem)$"),
        group_limit: int = Query(default=DEFAULT_GRAPH_GROUP_LIMIT, ge=1, le=MAX_GRAPH_GROUP_LIMIT),
        edge_limit: int = Query(
            default=DEFAULT_GRAPH_AGGREGATE_EDGE_LIMIT,
            ge=1,
            le=MAX_GRAPH_AGGREGATE_EDGE_LIMIT,
        ),
        include_external: bool = False,
    ) -> dict[str, Any]:
        row = self.selected_repository(repository_id)
        try:
            return self.database.graph_overview(
                int(row["id"]),
                snapshot_id,
                level=level,
                group_limit=group_limit,
                edge_limit=edge_limit,
                include_external=include_external,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def neighbors(
        self,
        node: str = Query(min_length=1, max_length=2_000),
        repository_id: int | None = None,
        snapshot_id: int | None = None,
        depth: int = Query(default=1, ge=1, le=3),
        direction: str = Query(default="both", pattern="^(incoming|outgoing|both)$"),
        node_limit: int = Query(
            default=DEFAULT_NEIGHBOR_NODE_LIMIT, ge=1, le=MAX_NEIGHBOR_NODE_LIMIT
        ),
        edge_limit: int = Query(
            default=DEFAULT_NEIGHBOR_EDGE_LIMIT, ge=1, le=MAX_NEIGHBOR_EDGE_LIMIT
        ),
        include_external: bool = False,
        relationship: list[str] = Query(default=[]),
    ) -> dict[str, Any]:
        row = self.selected_repository(repository_id)
        try:
            request = GraphNeighborhoodRequest(
                node=node,
                depth=depth,
                direction=direction,
                node_limit=node_limit,
                edge_limit=edge_limit,
                include_external=include_external,
                relationship_types=tuple(relationship),
            )
            return self.database.graph_neighborhood(int(row["id"]), snapshot_id, query=request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def delta(
        self,
        from_snapshot_id: int = Query(ge=1),
        repository_id: int | None = None,
        to_snapshot_id: int | None = Query(default=None, ge=1),
        node_limit: int = Query(default=DEFAULT_GRAPH_DELTA_LIMIT, ge=1, le=MAX_GRAPH_DELTA_LIMIT),
        edge_limit: int = Query(default=DEFAULT_GRAPH_DELTA_LIMIT, ge=1, le=MAX_GRAPH_DELTA_LIMIT),
    ) -> dict[str, Any]:
        row = self.selected_repository(repository_id)
        try:
            return self.database.graph_delta(
                int(row["id"]),
                from_snapshot_id,
                to_snapshot_id,
                node_limit=node_limit,
                edge_limit=edge_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
