"""Connection-local effective architecture placement for bounded graph queries."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.graph_read import group_parents, root_group
from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments


def install_graph_architecture(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, str | None]]:
    """Materialize only filter columns; detailed assignments remain the canonical source."""

    connection.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS graph_architecture (
            artifact_id INTEGER PRIMARY KEY,
            area TEXT NOT NULL,
            subsystem TEXT NOT NULL,
            source TEXT NOT NULL
        )
        """
    )
    connection.execute("DELETE FROM graph_architecture")
    assignments = taxonomy_assignments(connection, snapshot_id)
    parents = group_parents(connection, repository_id)
    rows = connection.execute(
        """
        SELECT artifact_id, declared_group, inferred_group
        FROM projected_file_versions ORDER BY artifact_id
        """
    ).fetchall()
    values = _architecture_rows(rows, assignments, parents)
    connection.executemany(
        "INSERT INTO graph_architecture(artifact_id, area, subsystem, source) VALUES (?, ?, ?, ?)",
        values,
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS temp.idx_graph_architecture_area ON graph_architecture(area)"
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS temp.idx_graph_architecture_subsystem
        ON graph_architecture(subsystem)
        """
    )
    return assignments, parents


def _architecture_rows(
    rows: list[sqlite3.Row],
    assignments: dict[int, dict[str, Any]],
    parents: dict[str, str | None],
) -> list[tuple[int, str, str, str]]:
    values = []
    for row in rows:
        artifact_id = int(row["artifact_id"])
        assignment = assignments.get(artifact_id)
        fallback = str(row["declared_group"] or row["inferred_group"] or "ungrouped")
        if assignment:
            area = str(assignment["area"])
            subsystem = str(assignment["subsystem"])
            source = str(assignment["source"])
        else:
            area = root_group(fallback, parents)
            subsystem = fallback
            source = (
                "project path rule" if row["declared_group"] else "standard fallback vocabulary"
            )
        values.append((artifact_id, area, subsystem, source))
    return values
