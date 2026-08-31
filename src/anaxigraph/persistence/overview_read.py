"""Canonical repository overview read model."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from anaxigraph.architecture_vocabulary import CURRENT_MAP, MAP_LAYERS
from anaxigraph.persistence.graph_read import projected_graph_quality
from anaxigraph.persistence.group_read import read_group_hierarchy
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection


def read_overview(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot_id = int(snapshot["id"])
    projection = install_snapshot_projection(connection, snapshot_id)
    totals = _totals(connection)
    relationship_count = int(
        connection.execute("SELECT COUNT(*) FROM projected_relationships").fetchone()[0]
    )
    findings = connection.execute(
        """
        SELECT severity, COUNT(*) AS count FROM findings
        WHERE repository_id = ? AND status NOT IN ('resolved', 'dismissed')
        GROUP BY severity
        """,
        (repository_id,),
    ).fetchall()
    coverage = _coverage(connection, snapshot_id)
    hierarchies = {
        layer: read_group_hierarchy(connection, repository_id, snapshot_id, layer=layer)
        for layer in MAP_LAYERS
    }
    return {
        "repository_id": repository_id,
        "snapshot": dict(snapshot),
        **dict(totals),
        "relationships": relationship_count,
        "graph_quality": projected_graph_quality(connection),
        "symbols": projection.symbol_count,
        "findings": {row["severity"]: row["count"] for row in findings},
        "languages": [dict(row) for row in _languages(connection)],
        "group_hierarchies": hierarchies,
        "map": {
            "default_layer": CURRENT_MAP,
            "available_layers": [layer for layer in MAP_LAYERS if hierarchies[layer]],
            "source": "declared rules first, then inferred responsibilities, then path fallback",
        },
        "coverage": coverage,
        "reconstruction": projection.as_dict(),
    }


def _totals(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT COUNT(*) AS files,
               COALESCE(SUM(lines_of_code), 0) AS lines_of_code,
               COALESCE(SUM(comment_lines), 0) AS comment_lines,
               COALESCE(AVG(complexity), 0) AS average_complexity,
               COALESCE(MAX(complexity), 0) AS maximum_complexity,
               COUNT(DISTINCT language) AS language_count
        FROM projected_file_versions
        """
    ).fetchone()
    assert row is not None
    return row


def _languages(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT language, COUNT(*) AS files, SUM(lines_of_code) AS lines_of_code
        FROM projected_file_versions
        GROUP BY language ORDER BY lines_of_code DESC, language
        """
    ).fetchall()


def _coverage(connection: sqlite3.Connection, snapshot_id: int) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COALESCE(
                   CAST(SUM(covered_lines) AS REAL) / NULLIF(SUM(total_lines), 0),
                   AVG(line_coverage)
               ) AS line_coverage,
               AVG(branch_coverage) AS branch_coverage,
               COUNT(DISTINCT artifact_id) AS measured_files,
               SUM(covered_lines) AS covered_lines,
               SUM(total_lines) AS measured_lines
        FROM coverage_measurements
        WHERE snapshot_id = ? AND artifact_id IS NOT NULL
        """,
        (snapshot_id,),
    ).fetchone()
    relationship = connection.execute(
        """
        SELECT CAST(COUNT(DISTINCT cm.relationship_edge_id) AS REAL) /
               NULLIF((SELECT COUNT(*) FROM projected_relationships
                       WHERE target_artifact_id IS NOT NULL), 0) AS value
        FROM coverage_measurements cm
        WHERE cm.snapshot_id = ? AND cm.relationship_edge_id IS NOT NULL
        """,
        (snapshot_id,),
    ).fetchone()
    return {
        **dict(row or {}),
        "relationship_coverage": relationship["value"] if relationship else None,
    }
