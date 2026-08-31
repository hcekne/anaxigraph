"""Connection-local effective architecture placement for bounded graph queries."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.architecture_vocabulary import inferred_group
from anaxigraph.languages import artifact_type
from anaxigraph.persistence.graph_read import group_parents, root_group
from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.temporal_reads import snapshot_files

_GRAPH_ARCHITECTURE_SCHEMA = """
DROP TABLE IF EXISTS temp.graph_architecture;
CREATE TEMP TABLE graph_architecture (
    artifact_id INTEGER PRIMARY KEY, area TEXT NOT NULL, subsystem TEXT NOT NULL,
    source TEXT NOT NULL, declared_group TEXT, inferred_group TEXT NOT NULL
);
CREATE INDEX temp.idx_graph_architecture_area ON graph_architecture(area);
CREATE INDEX temp.idx_graph_architecture_subsystem ON graph_architecture(subsystem);
"""


def install_graph_architecture(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, str | None], dict[str, Any]]:
    """Project a snapshot through today's map while retaining its original placement."""

    parents = group_parents(connection, repository_id)
    rows = connection.execute(
        """SELECT artifact_id, path, language, declared_group, inferred_group
           FROM projected_file_versions ORDER BY artifact_id"""
    ).fetchall()
    reference_id = _reference_snapshot_id(connection, repository_id, snapshot_id)
    current_files, current_assignments = _current_view(connection, rows, snapshot_id, reference_id)
    values, assignments = _architecture_rows(rows, current_files, current_assignments, parents)
    connection.executescript(_GRAPH_ARCHITECTURE_SCHEMA)
    connection.executemany(
        """INSERT INTO graph_architecture(
               artifact_id, area, subsystem, source, declared_group, inferred_group
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        values,
    )
    frame = {
        "mode": "present_day",
        "reference_snapshot_id": reference_id,
        "historical_snapshot_id": snapshot_id,
        "reclassified": reference_id != snapshot_id,
    }
    return assignments, parents, frame


def _current_view(
    connection: sqlite3.Connection,
    rows: list[sqlite3.Row],
    snapshot_id: int,
    reference_id: int,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    if reference_id == snapshot_id:
        return [dict(row) for row in rows], taxonomy_assignments(connection, snapshot_id)
    return (
        snapshot_files(connection, reference_id, expand_metadata=False),
        taxonomy_assignments(connection, reference_id),
    )


def _reference_snapshot_id(
    connection: sqlite3.Connection, repository_id: int, fallback: int
) -> int:
    row = connection.execute(
        "SELECT current_snapshot_id FROM repositories WHERE id = ?", (repository_id,)
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else fallback


def _architecture_rows(
    rows: list[sqlite3.Row],
    current_files: list[dict[str, Any]],
    current_assignments: dict[int, dict[str, Any]],
    parents: dict[str, str | None],
) -> tuple[list[tuple[Any, ...]], dict[int, dict[str, Any]]]:
    by_id = {int(file["artifact_id"]): file for file in current_files}
    by_path = {str(file["path"]): file for file in current_files}
    values = []
    assignments = {}
    for row in rows:
        artifact_id = int(row["artifact_id"])
        current = by_id.get(artifact_id) or by_path.get(str(row["path"]))
        if current:
            declared = current["declared_group"]
            inferred = str(current["inferred_group"] or "ungrouped")
            assignment = current_assignments.get(int(current["artifact_id"]))
        else:
            declared = None
            inferred = inferred_group(
                str(row["path"]),
                str(row["language"]),
                artifact_type(str(row["path"]), str(row["language"])),
            )
            assignment = None
        if assignment:
            assignments[artifact_id] = assignment
        area, subsystem, source = _placement(declared, inferred, assignment, parents)
        values.append((artifact_id, area, subsystem, source, declared, inferred))
    return values, assignments


def _placement(
    declared: Any,
    inferred: str,
    assignment: dict[str, Any] | None,
    parents: dict[str, str | None],
) -> tuple[str, str, str]:
    if assignment:
        return str(assignment["area"]), str(assignment["subsystem"]), str(assignment["source"])
    fallback = str(declared or inferred)
    return (
        root_group(fallback, parents),
        fallback,
        "project path rule" if declared else "standard fallback vocabulary",
    )
