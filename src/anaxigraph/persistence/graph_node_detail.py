"""Shared bounded node-detail SQL for graph pages and neighborhoods."""

from __future__ import annotations

import sqlite3
from typing import Any


def read_graph_node_rows(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    *,
    selection_sql: str,
    selection_parameters: list[Any],
    limit: int,
    offset: int = 0,
    order_by: str = "fv.path, fv.artifact_id",
) -> list[sqlite3.Row]:
    """Read details for an internal, trusted CTE named ``selected``."""

    return connection.execute(
        f"""
        WITH {selection_sql}
        SELECT fv.*, ga.area, ga.subsystem, ga.source AS architecture_source,
               ga.declared_group AS architecture_declared_group,
               ga.inferred_group AS architecture_inferred_group,
               COALESCE(incoming.count, 0) AS fan_in,
               COALESCE(outgoing.count, 0) AS fan_out,
               coverage.line_coverage,
               COALESCE(history.change_count, 0) AS change_count,
               selected.depth AS graph_depth
        FROM projected_file_versions fv
        JOIN selected ON selected.artifact_id = fv.artifact_id
        JOIN graph_architecture ga ON ga.artifact_id = fv.artifact_id
        LEFT JOIN (
            SELECT target_artifact_id, COUNT(*) AS count FROM projected_relationships
            WHERE target_artifact_id IS NOT NULL GROUP BY target_artifact_id
        ) incoming ON incoming.target_artifact_id = fv.artifact_id
        LEFT JOIN (
            SELECT source_artifact_id, COUNT(*) AS count FROM projected_relationships
            GROUP BY source_artifact_id
        ) outgoing ON outgoing.source_artifact_id = fv.artifact_id
        LEFT JOIN (
            SELECT artifact_id, MAX(line_coverage) AS line_coverage
            FROM coverage_measurements WHERE snapshot_id = ? GROUP BY artifact_id
        ) coverage ON coverage.artifact_id = fv.artifact_id
        LEFT JOIN (
            SELECT path, COUNT(*) AS change_count FROM git_changes
            WHERE repository_id = ? GROUP BY path
        ) history ON history.path = fv.path
        ORDER BY {order_by} LIMIT ? OFFSET ?
        """,
        [*selection_parameters, snapshot_id, repository_id, limit, offset],
    ).fetchall()
