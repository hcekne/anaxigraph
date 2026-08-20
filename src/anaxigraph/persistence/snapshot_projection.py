"""Connection-local SQL projection of one canonical temporal snapshot."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

from anaxigraph.persistence.temporal_reads import (
    snapshot_files_with_diagnostics,
    snapshot_relationship_edges_with_diagnostics,
    symbols_for_files,
)
from anaxigraph.persistence.temporal_reconstruction import ReconstructionDiagnostics


@dataclass(frozen=True, slots=True)
class SnapshotProjection:
    snapshot_id: int
    files: ReconstructionDiagnostics
    relationships: ReconstructionDiagnostics
    symbol_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "files": asdict(self.files),
            "relationships": asdict(self.relationships),
            "symbol_count": self.symbol_count,
        }


def install_snapshot_projection(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    include_symbols: bool = True,
) -> SnapshotProjection:
    """Populate stable TEMP read models from immutable facts and bounded deltas."""

    _install_tables(connection)
    files, file_diagnostics = snapshot_files_with_diagnostics(connection, snapshot_id)
    relationships, relationship_diagnostics = snapshot_relationship_edges_with_diagnostics(
        connection, snapshot_id
    )
    symbols = symbols_for_files(connection, files) if include_symbols else []
    _replace_files(connection, snapshot_id, files)
    _replace_symbols(connection, symbols)
    _replace_relationships(connection, snapshot_id, relationships)
    return SnapshotProjection(
        snapshot_id=snapshot_id,
        files=file_diagnostics,
        relationships=relationship_diagnostics,
        symbol_count=len(symbols),
    )


def _install_tables(connection: sqlite3.Connection) -> None:
    for statement in _PROJECTION_SCHEMA:
        connection.execute(statement)


def _replace_files(
    connection: sqlite3.Connection,
    snapshot_id: int,
    files: list[dict[str, Any]],
) -> None:
    connection.execute("DELETE FROM projected_file_versions")
    connection.executemany(
        """
        INSERT INTO projected_file_versions(
            id, artifact_id, snapshot_id, path, language, runtime, declared_group,
            inferred_group, raw_hash, structural_hash, lines_of_code, comment_lines,
            complexity, summary, responsibilities_json, inputs_json, outputs_json,
            side_effects_json, public_interfaces_json, analyzer, analysis_status,
            parse_error, metadata_json, first_seen_at, last_changed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                file["file_fact_id"],
                file["artifact_id"],
                snapshot_id,
                file["path"],
                file["language"],
                file["runtime"],
                file["declared_group"],
                file["inferred_group"],
                file["raw_hash"],
                file["structural_hash"],
                file["lines_of_code"],
                file["comment_lines"],
                file["complexity"],
                file["summary"],
                file["responsibilities_json"],
                file["inputs_json"],
                file["outputs_json"],
                file["side_effects_json"],
                file["public_interfaces_json"],
                file["analyzer"],
                file["analysis_status"],
                file["parse_error"],
                file["metadata_json"],
                file["first_seen_at"],
                file["last_changed_at"],
            )
            for file in files
        ],
    )


def _replace_symbols(connection: sqlite3.Connection, symbols: list[dict[str, Any]]) -> None:
    connection.execute("DELETE FROM projected_symbols")
    connection.executemany(
        """
        INSERT INTO projected_symbols(
            id, artifact_version_id, symbol_type, name, qualified_name, start_line,
            end_line, signature, summary, complexity, logical_lines
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                symbol["id"],
                symbol["file_fact_id"],
                symbol["symbol_type"],
                symbol["name"],
                symbol["qualified_name"],
                symbol["start_line"],
                symbol["end_line"],
                symbol["signature"],
                symbol["summary"],
                symbol["complexity"],
                symbol["logical_lines"],
            )
            for symbol in symbols
        ],
    )


def _replace_relationships(
    connection: sqlite3.Connection,
    snapshot_id: int,
    relationships: list[dict[str, Any]],
) -> None:
    connection.execute("DELETE FROM projected_relationships")
    connection.executemany(
        """
        INSERT INTO projected_relationships(
            id, snapshot_id, source_artifact_id, target_artifact_id, target_external,
            relationship_type, source, confidence, evidence, source_line, weight, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                edge["id"],
                snapshot_id,
                edge["source_artifact_id"],
                edge["target_artifact_id"],
                edge["target_external"],
                edge["relationship_type"],
                edge["source"],
                edge["confidence"],
                edge["evidence"],
                edge["source_line"],
                edge["weight"],
                edge["metadata_json"],
            )
            for edge in relationships
        ],
    )


_PROJECTION_SCHEMA = (
    """
    CREATE TEMP TABLE IF NOT EXISTS projected_file_versions (
        id INTEGER PRIMARY KEY, artifact_id INTEGER NOT NULL, snapshot_id INTEGER NOT NULL,
        path TEXT NOT NULL, language TEXT NOT NULL, runtime TEXT, declared_group TEXT,
        inferred_group TEXT, raw_hash TEXT NOT NULL, structural_hash TEXT NOT NULL,
        lines_of_code INTEGER NOT NULL, comment_lines INTEGER NOT NULL, complexity REAL NOT NULL,
        summary TEXT NOT NULL, responsibilities_json TEXT NOT NULL, inputs_json TEXT NOT NULL,
        outputs_json TEXT NOT NULL, side_effects_json TEXT NOT NULL,
        public_interfaces_json TEXT NOT NULL, analyzer TEXT NOT NULL,
        analysis_status TEXT NOT NULL, parse_error TEXT, metadata_json TEXT NOT NULL,
        first_seen_at TEXT, last_changed_at TEXT
    )
    """,
    """
    CREATE TEMP TABLE IF NOT EXISTS projected_symbols (
        id INTEGER PRIMARY KEY, artifact_version_id INTEGER NOT NULL, symbol_type TEXT NOT NULL,
        name TEXT NOT NULL, qualified_name TEXT NOT NULL, start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL, signature TEXT NOT NULL, summary TEXT NOT NULL,
        complexity REAL NOT NULL, logical_lines INTEGER NOT NULL
    )
    """,
    """
    CREATE TEMP TABLE IF NOT EXISTS projected_relationships (
        id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL, source_artifact_id INTEGER NOT NULL,
        target_artifact_id INTEGER, target_external TEXT, relationship_type TEXT NOT NULL,
        source TEXT NOT NULL, confidence REAL NOT NULL, evidence TEXT NOT NULL,
        source_line INTEGER NOT NULL, weight REAL NOT NULL, metadata_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS temp.idx_projected_files_path ON projected_file_versions(path)",
    """
    CREATE INDEX IF NOT EXISTS temp.idx_projected_relationship_source
    ON projected_relationships(source_artifact_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS temp.idx_projected_relationship_target
    ON projected_relationships(target_artifact_id)
    """,
)
