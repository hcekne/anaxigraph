"""Bounded structural graph deltas between two immutable snapshots."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any, Mapping

from anaxigraph.graph_contract import (
    GRAPH_CURRENT,
    GRAPH_DELTA_VERSION,
    GRAPH_UNSCANNED,
    MAX_GRAPH_DELTA_LIMIT,
    with_graph_telemetry,
)
from anaxigraph.persistence.graph_projection import install_graph_projection
from anaxigraph.persistence.graph_query_architecture import install_graph_architecture


def read_graph_delta(
    connection: sqlite3.Connection,
    repository_id: int,
    baseline: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    node_limit: int,
    edge_limit: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    _validate_limits(node_limit, edge_limit)
    baseline_projection = _install_baseline(connection, repository_id, int(baseline["id"]))
    target_projection = install_graph_projection(connection, int(target["id"]))
    install_graph_architecture(connection, repository_id, int(target["id"]))
    node_counts, node_rows = _node_changes(connection, node_limit)
    edge_counts, edge_rows = _edge_changes(connection, edge_limit)
    response = {
        "contract_version": GRAPH_DELTA_VERSION,
        "repository_id": repository_id,
        "availability": GRAPH_CURRENT,
        "baseline_snapshot": dict(baseline),
        "target_snapshot": dict(target),
        "counts": {
            "nodes": node_counts,
            "edges": edge_counts,
            "returned_node_changes": len(node_rows),
            "returned_edge_changes": len(edge_rows),
            "omitted_node_changes": sum(node_counts.values()) - len(node_rows),
            "omitted_edge_changes": sum(edge_counts.values()) - len(edge_rows),
        },
        "node_changes": [_node_change(row) for row in node_rows],
        "edge_changes": [_edge_change(row) for row in edge_rows],
        "reconstruction": {
            "baseline": baseline_projection.as_dict(),
            "target": target_projection.as_dict(),
        },
    }
    return with_graph_telemetry(response, started)


def empty_graph_delta(repository_id: int) -> dict[str, Any]:
    started = time.perf_counter()
    response = {
        "contract_version": GRAPH_DELTA_VERSION,
        "repository_id": repository_id,
        "availability": GRAPH_UNSCANNED,
        "baseline_snapshot": None,
        "target_snapshot": None,
        "counts": {"nodes": {}, "edges": {}},
        "node_changes": [],
        "edge_changes": [],
        "reconstruction": {},
    }
    return with_graph_telemetry(response, started)


def _validate_limits(node_limit: int, edge_limit: int) -> None:
    if not 1 <= node_limit <= MAX_GRAPH_DELTA_LIMIT:
        raise ValueError(f"delta node_limit must be between 1 and {MAX_GRAPH_DELTA_LIMIT}")
    if not 1 <= edge_limit <= MAX_GRAPH_DELTA_LIMIT:
        raise ValueError(f"delta edge_limit must be between 1 and {MAX_GRAPH_DELTA_LIMIT}")


def _install_baseline(connection: sqlite3.Connection, repository_id: int, snapshot_id: int):
    projection = install_graph_projection(connection, snapshot_id)
    install_graph_architecture(connection, repository_id, snapshot_id)
    connection.execute("DROP TABLE IF EXISTS temp.baseline_graph_files")
    connection.execute("DROP TABLE IF EXISTS temp.baseline_graph_edges")
    connection.execute(
        """
        CREATE TEMP TABLE baseline_graph_files AS
        SELECT fv.artifact_id, fv.path, fv.raw_hash, fv.structural_hash,
               ga.area, ga.subsystem
        FROM projected_file_versions fv
        JOIN graph_architecture ga ON ga.artifact_id = fv.artifact_id
        """
    )
    connection.execute(
        "CREATE INDEX temp.idx_baseline_graph_files_id ON baseline_graph_files(artifact_id)"
    )
    connection.execute(
        f"CREATE TEMP TABLE baseline_graph_edges AS SELECT {_EDGE_COLUMNS} FROM projected_relationships"
    )
    return projection


def _node_changes(
    connection: sqlite3.Connection,
    limit: int,
) -> tuple[dict[str, int], list[sqlite3.Row]]:
    counts = connection.execute(_NODE_COUNTS_SQL).fetchone()
    rows = connection.execute(f"{_NODE_CHANGES_SQL} LIMIT ?", (limit,)).fetchall()
    return {
        "added": int(counts["added"]),
        "removed": int(counts["removed"]),
        "changed": int(counts["changed"]),
    }, rows


def _edge_changes(
    connection: sqlite3.Connection,
    limit: int,
) -> tuple[dict[str, int], list[sqlite3.Row]]:
    counts = connection.execute(f"{_EDGE_CTE} {_EDGE_COUNTS_SQL}").fetchone()
    rows = connection.execute(f"{_EDGE_CTE} {_EDGE_CHANGES_SQL} LIMIT ?", (limit,)).fetchall()
    return {"added": int(counts["added"]), "removed": int(counts["removed"])}, rows


def _node_change(row: sqlite3.Row) -> dict[str, Any]:
    before = _node_side(row, "before")
    after = _node_side(row, "after")
    fields = ("path", "raw_hash", "structural_hash", "area", "subsystem")
    return {
        "change": row["change_type"],
        "artifact_id": int(row["artifact_id"]),
        "before": before,
        "after": after,
        "changed_fields": [name for name in fields if before.get(name) != after.get(name)],
    }


def _node_side(row: sqlite3.Row, prefix: str) -> dict[str, Any]:
    if row[f"{prefix}_path"] is None:
        return {}
    return {
        "path": row[f"{prefix}_path"],
        "raw_hash": row[f"{prefix}_raw_hash"],
        "structural_hash": row[f"{prefix}_structural_hash"],
        "area": row[f"{prefix}_area"],
        "subsystem": row[f"{prefix}_subsystem"],
    }


def _edge_change(row: sqlite3.Row) -> dict[str, Any]:
    target = row["target_path"] or row["target_external"]
    identity = "|".join(
        str(row[key] or "")
        for key in (
            "change_type",
            "source_artifact_id",
            "target_artifact_id",
            "target_external",
            "relationship_type",
            "source_line",
            "confidence",
            "weight",
            "evidence",
        )
    )
    return {
        "id": hashlib.sha256(identity.encode()).hexdigest(),
        "change": row["change_type"],
        "source": row["source_path"],
        "target": target,
        "target_external": row["target_external"],
        "type": row["relationship_type"],
        "evidence_source": row["source"],
        "confidence": float(row["confidence"]),
        "source_line": int(row["source_line"]),
        "weight": float(row["weight"]),
    }


_NODE_DIFFERENT = """
    before.path IS NOT current.path OR before.raw_hash IS NOT current.raw_hash OR
    before.structural_hash IS NOT current.structural_hash OR
    before.area IS NOT current_architecture.area OR
    before.subsystem IS NOT current_architecture.subsystem
"""

_NODE_COUNTS_SQL = f"""
SELECT
  (SELECT COUNT(*) FROM projected_file_versions current
   LEFT JOIN baseline_graph_files before ON before.artifact_id = current.artifact_id
   WHERE before.artifact_id IS NULL) AS added,
  (SELECT COUNT(*) FROM baseline_graph_files before
   LEFT JOIN projected_file_versions current ON current.artifact_id = before.artifact_id
   WHERE current.artifact_id IS NULL) AS removed,
  (SELECT COUNT(*) FROM baseline_graph_files before
   JOIN projected_file_versions current ON current.artifact_id = before.artifact_id
   JOIN graph_architecture current_architecture
     ON current_architecture.artifact_id = current.artifact_id
   WHERE {_NODE_DIFFERENT}) AS changed
"""

_NODE_CHANGES_SQL = f"""
SELECT * FROM (
  SELECT 'added' AS change_type, current.artifact_id,
         NULL AS before_path, NULL AS before_raw_hash, NULL AS before_structural_hash,
         NULL AS before_area, NULL AS before_subsystem,
         current.path AS after_path, current.raw_hash AS after_raw_hash,
         current.structural_hash AS after_structural_hash,
         architecture.area AS after_area, architecture.subsystem AS after_subsystem
  FROM projected_file_versions current
  JOIN graph_architecture architecture ON architecture.artifact_id = current.artifact_id
  LEFT JOIN baseline_graph_files before ON before.artifact_id = current.artifact_id
  WHERE before.artifact_id IS NULL
  UNION ALL
  SELECT 'removed', before.artifact_id, before.path, before.raw_hash, before.structural_hash,
         before.area, before.subsystem, NULL, NULL, NULL, NULL, NULL
  FROM baseline_graph_files before
  LEFT JOIN projected_file_versions current ON current.artifact_id = before.artifact_id
  WHERE current.artifact_id IS NULL
  UNION ALL
  SELECT 'changed', current.artifact_id, before.path, before.raw_hash, before.structural_hash,
         before.area, before.subsystem, current.path, current.raw_hash, current.structural_hash,
         architecture.area, architecture.subsystem
  FROM baseline_graph_files before
  JOIN projected_file_versions current ON current.artifact_id = before.artifact_id
  JOIN graph_architecture architecture ON architecture.artifact_id = current.artifact_id
  WHERE {_NODE_DIFFERENT.replace("current_architecture.", "architecture.")}
) ORDER BY COALESCE(after_path, before_path), artifact_id
"""

_EDGE_COLUMNS = """
source_artifact_id, target_artifact_id, target_external, relationship_type,
source, confidence, evidence, source_line, weight, metadata_json
"""

_EDGE_CTE = f"""
WITH current_edges AS (SELECT {_EDGE_COLUMNS} FROM projected_relationships),
added AS (SELECT * FROM current_edges EXCEPT SELECT * FROM baseline_graph_edges),
removed AS (SELECT * FROM baseline_graph_edges EXCEPT SELECT * FROM current_edges),
changes AS (
  SELECT 'added' AS change_type, * FROM added
  UNION ALL SELECT 'removed' AS change_type, * FROM removed
)
"""

_EDGE_COUNTS_SQL = """
SELECT (SELECT COUNT(*) FROM added) AS added,
       (SELECT COUNT(*) FROM removed) AS removed
"""

_EDGE_CHANGES_SQL = """
SELECT changes.*,
       COALESCE(current_source.path, baseline_source.path) AS source_path,
       COALESCE(current_target.path, baseline_target.path) AS target_path
FROM changes
LEFT JOIN projected_file_versions current_source
  ON current_source.artifact_id = changes.source_artifact_id
LEFT JOIN baseline_graph_files baseline_source
  ON baseline_source.artifact_id = changes.source_artifact_id
LEFT JOIN projected_file_versions current_target
  ON current_target.artifact_id = changes.target_artifact_id
LEFT JOIN baseline_graph_files baseline_target
  ON baseline_target.artifact_id = changes.target_artifact_id
ORDER BY source_path, relationship_type, COALESCE(target_path, target_external), source_line
"""
