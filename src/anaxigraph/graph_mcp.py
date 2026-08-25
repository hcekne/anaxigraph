"""One bounded graph query tool for architecture-first agent exploration."""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from anaxigraph.graph_contract import GraphNeighborhoodRequest, GraphPageRequest


def register_graph_tool(server: Any, database: Any, context: Any) -> None:
    GraphTool(server, database, context).register()


class GraphTool:
    def __init__(self, server: Any, database: Any, context: Any) -> None:
        self.server = server
        self.database = database
        self.context = context

    def register(self) -> None:
        self.server.tool(
            name="ANAXIGRAPH_GRAPH",
            title="Query a bounded architecture graph",
            description=(
                "Read architecture aggregates, a cursor page, a depth-capped neighborhood, or "
                "a snapshot delta. "
                "Overview is the default and smallest response; follow page cursors only when "
                "the task needs broader module-level evidence."
            ),
            annotations=ToolAnnotations(
                readOnlyHint=True,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )(self.query)

    def query(
        self,
        mode: str = "overview",
        repository: str = "",
        snapshot_id: int = 0,
        baseline_snapshot_id: int = 0,
        node: str = "",
        depth: int = 1,
        direction: str = "both",
        cursor: str = "",
        node_limit: int = 100,
        edge_limit: int = 250,
        include_external: bool = False,
        level: str = "area",
        path: str = "",
        language: list[str] | None = None,
        area: list[str] | None = None,
        subsystem: list[str] | None = None,
        finding: list[str] | None = None,
        relationship: list[str] | None = None,
    ) -> dict[str, Any]:
        row, _root = self.context(repository)
        return self._dispatch(
            row,
            snapshot_id or None,
            baseline_snapshot_id,
            mode,
            node,
            depth,
            direction,
            cursor,
            node_limit,
            edge_limit,
            include_external,
            level,
            path,
            language,
            area,
            subsystem,
            finding,
            relationship,
        )

    def _dispatch(
        self,
        row: dict[str, Any],
        snapshot_id: int | None,
        baseline_snapshot_id: int,
        mode: str,
        node: str,
        depth: int,
        direction: str,
        cursor: str,
        node_limit: int,
        edge_limit: int,
        include_external: bool,
        level: str,
        path: str,
        language: list[str] | None,
        area: list[str] | None,
        subsystem: list[str] | None,
        finding: list[str] | None,
        relationship: list[str] | None,
    ) -> dict[str, Any]:
        if mode == "overview":
            return self._overview(row, snapshot_id, level, node_limit, edge_limit, include_external)
        if mode == "delta":
            return self._delta(row, baseline_snapshot_id, snapshot_id, node_limit, edge_limit)
        return self._explore(
            row,
            snapshot_id,
            mode,
            node,
            depth,
            direction,
            cursor,
            node_limit,
            edge_limit,
            include_external,
            path,
            language,
            area,
            subsystem,
            finding,
            relationship,
        )

    def _explore(
        self,
        row: dict[str, Any],
        snapshot_id: int | None,
        mode: str,
        node: str,
        depth: int,
        direction: str,
        cursor: str,
        node_limit: int,
        edge_limit: int,
        include_external: bool,
        path: str,
        language: list[str] | None,
        area: list[str] | None,
        subsystem: list[str] | None,
        finding: list[str] | None,
        relationship: list[str] | None,
    ) -> dict[str, Any]:
        if mode == "neighbors":
            return self._neighbors(
                row,
                snapshot_id,
                node,
                depth,
                direction,
                node_limit,
                edge_limit,
                include_external,
                relationship,
            )
        if mode != "page":
            raise ValueError("graph mode must be overview, page, neighbors, or delta")
        return self._page(
            row,
            snapshot_id,
            cursor,
            node_limit,
            edge_limit,
            include_external,
            path,
            language,
            area,
            subsystem,
            finding,
            relationship,
        )

    def _overview(
        self,
        row: dict[str, Any],
        snapshot_id: int | None,
        level: str,
        node_limit: int,
        edge_limit: int,
        include_external: bool,
    ) -> dict[str, Any]:
        return self.database.graph_overview(
            int(row["id"]),
            snapshot_id,
            level=level,
            group_limit=node_limit,
            edge_limit=edge_limit,
            include_external=include_external,
        )

    def _delta(
        self,
        row: dict[str, Any],
        baseline_snapshot_id: int,
        target_snapshot_id: int | None,
        node_limit: int,
        edge_limit: int,
    ) -> dict[str, Any]:
        if baseline_snapshot_id < 1:
            raise ValueError("delta mode requires baseline_snapshot_id")
        return self.database.graph_delta(
            int(row["id"]),
            baseline_snapshot_id,
            target_snapshot_id,
            node_limit=node_limit,
            edge_limit=edge_limit,
        )

    def _neighbors(
        self,
        row: dict[str, Any],
        snapshot_id: int | None,
        node: str,
        depth: int,
        direction: str,
        node_limit: int,
        edge_limit: int,
        include_external: bool,
        relationship: list[str] | None,
    ) -> dict[str, Any]:
        request = GraphNeighborhoodRequest(
            node=node,
            depth=depth,
            direction=direction,
            node_limit=node_limit,
            edge_limit=edge_limit,
            include_external=include_external,
            relationship_types=tuple(relationship or ()),
        )
        return self.database.graph_neighborhood(int(row["id"]), snapshot_id, query=request)

    def _page(
        self,
        row: dict[str, Any],
        snapshot_id: int | None,
        cursor: str,
        node_limit: int,
        edge_limit: int,
        include_external: bool,
        path: str,
        language: list[str] | None,
        area: list[str] | None,
        subsystem: list[str] | None,
        finding: list[str] | None,
        relationship: list[str] | None,
    ) -> dict[str, Any]:
        request = GraphPageRequest(
            cursor=cursor,
            node_limit=node_limit,
            edge_limit=edge_limit,
            include_external=include_external,
            path=path,
            languages=tuple(language or ()),
            areas=tuple(area or ()),
            subsystems=tuple(subsystem or ()),
            finding_types=tuple(finding or ()),
            relationship_types=tuple(relationship or ()),
        )
        return self.database.graph(int(row["id"]), snapshot_id, query=request)
