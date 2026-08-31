"""Connection-local current responsibility placement for bounded graph queries."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from anaxigraph.architecture_vocabulary import (
    CURRENT_MAP,
    architecture_placement,
    inferred_group,
)
from anaxigraph.languages import artifact_type
from anaxigraph.persistence.graph_read import group_parents
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
    *,
    layer: str = CURRENT_MAP,
) -> tuple[dict[int, dict[str, Any]], dict[str, str | None], dict[str, Any]]:
    """Project a snapshot through today's map while retaining its original placement."""

    parents = group_parents(connection, repository_id)
    rows = connection.execute(
        """SELECT artifact_id, path, language, declared_group, inferred_group
           FROM projected_file_versions ORDER BY artifact_id"""
    ).fetchall()
    reference = connection.execute(
        "SELECT current_snapshot_id FROM repositories WHERE id = ?", (repository_id,)
    ).fetchone()
    reference_id = int(reference[0]) if reference and reference[0] is not None else snapshot_id
    current_files = [dict(row) for row in rows]
    if reference_id != snapshot_id:
        current_files = snapshot_files(connection, reference_id, expand_metadata=False)
    current_assignments = taxonomy_assignments(connection, reference_id)
    values, assignments = _architecture_rows(
        rows, current_files, current_assignments, parents, layer
    )
    connection.executescript(_GRAPH_ARCHITECTURE_SCHEMA)
    connection.executemany("INSERT INTO graph_architecture VALUES (?, ?, ?, ?, ?, ?)", values)
    frame = {
        "mode": "present_day",
        "reference_snapshot_id": reference_id,
        "historical_snapshot_id": snapshot_id,
        "reclassified": reference_id != snapshot_id,
        "map_layer": layer,
    }
    return assignments, parents, frame


def _architecture_rows(
    rows: list[sqlite3.Row],
    current_files: list[dict[str, Any]],
    current_assignments: dict[int, dict[str, Any]],
    parents: dict[str, str | None],
    layer: str,
) -> tuple[list[tuple[Any, ...]], dict[int, dict[str, Any]]]:
    by_id = {int(file["artifact_id"]): file for file in current_files}
    by_path = {str(file["path"]): file for file in current_files}
    path_moves = _directory_moves(rows, current_files)
    values = []
    assignments = {}
    for row in rows:
        artifact_id = int(row["artifact_id"])
        current = by_id.get(artifact_id) or by_path.get(str(row["path"]))
        if current is None:
            current = by_path.get(_moved_path(str(row["path"]), path_moves))
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
        placement = architecture_placement(
            layer, declared, inferred, parents, assignment, show_missing=True
        )
        assert placement is not None
        values.append(
            (
                artifact_id,
                *(placement[key] for key in ("area", "subsystem", "source")),
                declared,
                inferred,
            )
        )
    return values, assignments


def _directory_moves(
    historical_files: list[sqlite3.Row], current_files: list[dict[str, Any]]
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Infer directory renames from repeated, unique filenames rather than guessing."""
    current_parents: dict[tuple[str, str], list[tuple[str, ...]]] = defaultdict(list)
    for file in current_files:
        path = PurePosixPath(str(file["path"]))
        current_parents[(str(file["language"]), path.name)].append(path.parent.parts)
    support: Counter[tuple[tuple[str, ...], tuple[str, ...]]] = Counter()
    for file in historical_files:
        path = PurePosixPath(str(file["path"]))
        matches = current_parents.get((str(file["language"]), path.name), [])
        if len(matches) == 1 and path.parent.parts != matches[0]:
            old_parent, new_parent = path.parent.parts, matches[0]
            shared = 0
            for old_part, new_part in zip(reversed(old_parent), reversed(new_parent)):
                if old_part != new_part:
                    break
                shared += 1
            old_prefix = old_parent[:-shared] if shared else old_parent
            new_prefix = new_parent[:-shared] if shared else new_parent
            support[(old_prefix, new_prefix)] += 1
    candidates: dict[tuple[str, ...], list[tuple[int, tuple[str, ...]]]] = defaultdict(list)
    for (old_prefix, new_prefix), count in support.items():
        if count >= 2:
            candidates[old_prefix].append((count, new_prefix))
    ranked = ((old, sorted(choices, reverse=True)) for old, choices in candidates.items())
    moves = [
        (old, choices[0][1])
        for old, choices in ranked
        if len(choices) == 1 or choices[0][0] > choices[1][0]
    ]
    return tuple(sorted(moves, key=lambda item: len(item[0]), reverse=True))


def _moved_path(path: str, moves: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]) -> str:
    parts = PurePosixPath(path).parts
    for old_prefix, new_prefix in moves:
        if parts[: len(old_prefix)] == old_prefix:
            return PurePosixPath(*new_prefix, *parts[len(old_prefix) :]).as_posix()
    return path
