"""Canonical module-detail read model."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.persistence.graph_read import decode_relationship
from anaxigraph.persistence.row_decoding import decode_json_columns
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection


def read_file_details(
    connection: sqlite3.Connection,
    repository_id: int,
    path: str,
    snapshot_id: int,
) -> dict[str, Any] | None:
    projection = install_snapshot_projection(connection, snapshot_id)
    version = _file_version(connection, path)
    if version is None:
        return None
    rows = _module_rows(connection, repository_id, path, version)
    artifact_id = int(version["artifact_id"])
    claims = _legacy_claims(connection, snapshot_id, artifact_id)
    semantic_state, semantic_documents = _semantic_details(connection, snapshot_id, path)
    return {
        "file": _decode_file(dict(version)),
        "symbols": [dict(row) for row in rows["symbols"]],
        "relationships": [decode_relationship(dict(row)) for row in rows["relationships"]],
        "dependants": [decode_relationship(dict(row)) for row in rows["dependants"]],
        "history": [dict(row) for row in rows["history"]],
        "semantic_claims": [decode_json_columns(dict(row)) for row in claims],
        "semantic_state": dict(semantic_state) if semantic_state else None,
        "semantic_dossiers": semantic_documents,
        "reconstruction": projection.as_dict(),
    }


def _file_version(connection: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    version = connection.execute(
        """
        SELECT fv.*, a.canonical_path, a.artifact_type, a.first_seen_commit, a.deleted_commit
        FROM projected_file_versions fv JOIN artifacts a ON a.id = fv.artifact_id
        WHERE fv.path = ?
        """,
        (path,),
    ).fetchone()
    return version


def _module_rows(
    connection: sqlite3.Connection,
    repository_id: int,
    path: str,
    version: sqlite3.Row,
) -> dict[str, list[sqlite3.Row]]:
    artifact_id = int(version["artifact_id"])
    symbols = connection.execute(
        "SELECT * FROM projected_symbols WHERE artifact_version_id = ? ORDER BY start_line",
        (version["id"],),
    ).fetchall()
    relationships = connection.execute(
        """
        SELECT r.*, target.canonical_path AS target_path
        FROM projected_relationships r
        LEFT JOIN artifacts target ON target.id = r.target_artifact_id
        WHERE r.source_artifact_id = ?
        ORDER BY r.source_line, target_path, r.target_external
        """,
        (artifact_id,),
    ).fetchall()
    dependants = connection.execute(
        """
        SELECT r.*, source.canonical_path AS source_path
        FROM projected_relationships r JOIN artifacts source ON source.id = r.source_artifact_id
        WHERE r.target_artifact_id = ? ORDER BY source_path
        """,
        (artifact_id,),
    ).fetchall()
    history = connection.execute(
        """
        SELECT commit_sha, committed_at, author_name, subject, change_type, additions, deletions
        FROM git_changes WHERE repository_id = ? AND path = ?
        ORDER BY committed_at DESC LIMIT 50
        """,
        (repository_id, path),
    ).fetchall()
    return {
        "symbols": symbols,
        "relationships": relationships,
        "dependants": dependants,
        "history": history,
    }


def _legacy_claims(
    connection: sqlite3.Connection,
    snapshot_id: int,
    artifact_id: int,
) -> list[sqlite3.Row]:
    version = connection.execute(
        "SELECT id FROM file_versions WHERE snapshot_id = ? AND artifact_id = ?",
        (snapshot_id, artifact_id),
    ).fetchone()
    if version is None:
        return []
    return connection.execute(
        "SELECT * FROM semantic_claims WHERE artifact_version_id = ?",
        (version["id"],),
    ).fetchall()


def _semantic_details(
    connection: sqlite3.Connection,
    snapshot_id: int,
    path: str,
) -> tuple[sqlite3.Row | None, dict[str, dict[str, Any]]]:
    state = connection.execute(
        """
        SELECT * FROM semantic_scope_states
        WHERE snapshot_id = ? AND scope_type = 'module' AND scope_key = ?
        """,
        (snapshot_id, path),
    ).fetchone()
    documents: dict[str, dict[str, Any]] = {}
    if state is None:
        return None, documents
    for kind, document_id in (
        ("intrinsic", state["intrinsic_document_id"]),
        ("context", state["context_document_id"]),
    ):
        if not document_id:
            continue
        document = connection.execute(
            "SELECT * FROM semantic_documents WHERE id = ?", (document_id,)
        ).fetchone()
        if document is not None:
            documents[kind] = decode_json_columns(dict(document))
    return state, documents


def _decode_file(value: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "responsibilities_json",
        "inputs_json",
        "outputs_json",
        "side_effects_json",
        "public_interfaces_json",
        "metadata_json",
    ):
        value[key.removesuffix("_json")] = json.loads(value.pop(key) or "null")
    return value
