"""Semantic coverage, budget, and dossier reporting."""

from __future__ import annotations

from typing import Any

from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_records import _document_by_id
from anaxigraph.semantic_status import semantic_status_payload
from anaxigraph.semantic_status_queries import read_semantic_status


class SemanticReportingService:
    def __init__(self, database: SemanticIndex) -> None:
        self._database = database

    def status(self, repository_id: int, semantic: SemanticConfig | None = None) -> dict[str, Any]:
        snapshot = self._database.latest_snapshot(repository_id)
        configured = bool(semantic and semantic.enabled)
        if snapshot is None:
            return {
                "enabled": configured,
                "state": "not_indexed",
                "semantically_ready": False,
                "baseline_complete": False,
            }
        snapshot_id = int(snapshot["id"])
        with self._database.connect() as connection:
            rows = read_semantic_status(connection, repository_id, snapshot_id)
        return semantic_status_payload(snapshot_id, semantic, rows)

    def dossier(
        self, repository_id: int, path: str, snapshot_id: int | None = None
    ) -> dict[str, Any] | None:
        snapshot = (
            self._database.latest_snapshot(repository_id)
            if snapshot_id is None
            else self._database._resolve_snapshot(repository_id, snapshot_id)
        )
        if snapshot is None:
            return None
        with self._database.connect() as connection:
            state = connection.execute(
                """
                SELECT * FROM semantic_scope_states
                WHERE snapshot_id = ? AND scope_type = 'module' AND scope_key = ?
                """,
                (int(snapshot["id"]), path),
            ).fetchone()
            if state is None:
                return None
            result = dict(state)
            for key, label in (
                ("intrinsic_document_id", "intrinsic"),
                ("context_document_id", "context"),
            ):
                document_id = result.get(key)
                result[label] = (
                    _document_by_id(connection, int(document_id)) if document_id else None
                )
            return result
