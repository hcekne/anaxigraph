"""Public index facade combining durable storage and source-aware analysis reads."""

from __future__ import annotations

from contextlib import closing
from typing import Any

from anaxigraph.knowledge_sync import clear_knowledge_cache, sync_knowledge
from anaxigraph.pattern_evidence_source import empty_pattern_evidence, read_pattern_evidence
from anaxigraph.persistence import index_store

SCHEMA_VERSION = index_store.SCHEMA_VERSION
GitMetadata = index_store.GitMetadata
StoragePolicy = index_store.StoragePolicy
admit_index_write = index_store.admit_index_write
persistence = index_store.persistence
time = index_store.time
utc_now = index_store.utc_now
_WRITE_LOCK_WAIT_SECONDS = index_store._WRITE_LOCK_WAIT_SECONDS


def _begin_write(connection) -> None:
    index_store._begin_write(connection, wait_seconds=_WRITE_LOCK_WAIT_SECONDS)


class AnaxiIndex(index_store.AnaxiIndexStore):
    """Persistent repository knowledge and reusable source-aware evidence."""

    def initialize(self) -> None:
        try:
            super().initialize()
            self._resume_import_graph()
        except persistence.CompactionHeadroomError:
            self._recover_compaction_headroom()

    def finish_cache_maintenance(self) -> None:
        try:
            super().finish_cache_maintenance()
            self._resume_import_graph()
        except persistence.CompactionHeadroomError:
            self._recover_compaction_headroom()

    def _resume_import_graph(self) -> None:
        with closing(self.connect()) as connection:
            pending = connection.execute(
                "SELECT value FROM schema_meta WHERE key='graph-import-pending'"
            ).fetchone()
        if pending is not None:
            self._build_import_graph(int(pending[0]))
            super().finish_cache_maintenance()

    def _recover_compaction_headroom(self) -> None:
        with closing(self.connect()) as connection:
            snapshot = connection.execute(
                "SELECT CAST(value AS INTEGER) FROM schema_meta WHERE key='graph-import-pending' "
                "UNION ALL SELECT snapshot_id FROM graph_revisions LIMIT 1"
            ).fetchone()
        if snapshot is None:
            raise persistence.CompactionHeadroomError(
                "Canonical index cannot be compacted safely within 200 MB"
            )
        # Retry once after evicting only the rebuildable graph, preserving paid rows.
        self._defer_import_graph(int(snapshot[0]))
        super().finish_cache_maintenance()
        self._rebuild_compact_graph(int(snapshot[0]))

    def _rebuild_compact_graph(self, snapshot_id: int) -> None:
        def build(connection):
            sync_knowledge(connection, snapshot_id, force=True)
            persistence.refresh_current_search_projections(connection)
            connection.execute(
                "DELETE FROM schema_meta WHERE key IN ('graph-import-pending','index-compaction-pending')"
            )

        def admit(connection, staged):
            admit_index_write(connection, staged, self.storage_policy)

        persistence.rebuild_compact_cache(
            self.path, schema_version=SCHEMA_VERSION, build=build, admit=admit
        )

    def rebuild_graph_cache(self, snapshot_id: int) -> None:
        if self.path.stat().st_size * 2 <= self.storage_policy.index_bytes:
            with self.transaction() as connection:
                sync_knowledge(connection, snapshot_id)
            return
        self._defer_import_graph(snapshot_id)
        self.finish_cache_maintenance()

    def _defer_import_graph(self, snapshot_id: int) -> None:
        with self.transaction(maintenance=True) as connection:
            clear_knowledge_cache(connection)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta VALUES ('graph-import-pending',?)",
                (str(snapshot_id),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
            )

    def _build_import_graph(self, snapshot_id: int) -> None:
        with self.transaction(maintenance=True) as connection:
            with index_store.maintenance_headroom(connection, self.path):
                sync_knowledge(connection, snapshot_id, force=True)
            connection.execute("DELETE FROM schema_meta WHERE key='graph-import-pending'")
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
            )

    def _begin_write(self, connection) -> None:
        _begin_write(connection)

    def _now(self) -> str:
        return utc_now()

    def pattern_evidence(
        self, repository_id: int, snapshot_id: int | None = None
    ) -> dict[str, Any]:
        snapshot = self.resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return empty_pattern_evidence(repository_id)
        with closing(self.connect()) as connection:
            return read_pattern_evidence(connection, repository_id, int(snapshot["id"])).as_dict()
