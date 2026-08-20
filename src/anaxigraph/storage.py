"""AnaxiIndex: SQLite persistence for temporal repository intelligence."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anaxigraph.models import GitMetadata
from anaxigraph.persistence.index_facade import (
    SCHEMA,
    SCHEMA_VERSION,
    GraphReadCache,
    initialize_index,
    install_snapshot_projection,
    read_file_details,
    read_finding,
    read_findings,
    read_graph,
    read_group_hierarchy,
    read_modules,
    read_overview,
    read_snapshots,
    read_timeline,
    search_modules,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AnaxiIndex:
    """Persistent repository knowledge store used by AnaxiGraph and AnaxiMCP."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._graph_cache = GraphReadCache()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        initialize_index(
            self.path,
            self.connect,
            schema=SCHEMA,
            target_version=SCHEMA_VERSION,
        )

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
            self._graph_cache.clear()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ensure_repository(
        self,
        *,
        path: Path,
        name: str,
        git: GitMetadata,
    ) -> int:
        resolved = str(path.resolve())
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO repositories(name, path, remote_url, default_branch, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    remote_url = excluded.remote_url,
                    default_branch = excluded.default_branch,
                    updated_at = excluded.updated_at
                """,
                (name, resolved, git.remote_url, git.default_branch, now, now),
            )
            row = connection.execute(
                "SELECT id FROM repositories WHERE path = ?", (resolved,)
            ).fetchone()
            assert row is not None
            return int(row["id"])

    def repository(self, selector: int | str | Path | None = None) -> dict[str, Any] | None:
        with self.connect() as connection:
            if selector is None:
                row = connection.execute(
                    "SELECT * FROM repositories ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
            elif isinstance(selector, int) or str(selector).isdigit():
                row = connection.execute(
                    "SELECT * FROM repositories WHERE id = ?", (int(selector),)
                ).fetchone()
            else:
                value = (
                    str(Path(selector).expanduser().resolve())
                    if isinstance(selector, Path)
                    else str(selector)
                )
                row = connection.execute(
                    "SELECT * FROM repositories WHERE path = ? OR name = ? ORDER BY updated_at DESC LIMIT 1",
                    (value, value),
                ).fetchone()
            return dict(row) if row else None

    def repositories(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*,
                       COALESCE(
                           r.current_snapshot_id,
                           (SELECT id FROM snapshots s WHERE s.repository_id = r.id ORDER BY id DESC LIMIT 1)
                       )
                           AS latest_snapshot_id
                FROM repositories r ORDER BY updated_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def latest_snapshot(self, repository_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT s.* FROM repositories r
                LEFT JOIN snapshots s ON s.id = r.current_snapshot_id
                WHERE r.id = ? AND s.id IS NOT NULL
                """,
                (repository_id,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM snapshots WHERE repository_id = ? ORDER BY id DESC LIMIT 1",
                    (repository_id,),
                ).fetchone()
            return dict(row) if row else None

    def snapshot_by_fingerprint(
        self, repository_id: int, content_fingerprint: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM snapshots
                WHERE repository_id = ? AND content_fingerprint = ? LIMIT 1
                """,
                (repository_id, content_fingerprint),
            ).fetchone()
            return dict(row) if row else None

    def commit_snapshot(
        self,
        repository_id: int,
        commit_sha: str,
        analysis_signature: str,
    ) -> dict[str, Any] | None:
        """Find a compatible commit frame without rereading the full Git tree."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM snapshots
                WHERE repository_id = ? AND commit_sha = ?
                  AND (snapshot_kind = 'commit' OR dirty = 0)
                ORDER BY CASE snapshot_kind WHEN 'commit' THEN 0 ELSE 1 END, id DESC
                """,
                (repository_id, commit_sha),
            ).fetchall()
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            if metadata.get("analysis_signature") == analysis_signature:
                return dict(row)
        return None

    def set_current_snapshot(self, repository_id: int, snapshot_id: int) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE repositories SET current_snapshot_id = ?, updated_at = ? WHERE id = ?",
                (snapshot_id, utc_now(), repository_id),
            )

    def snapshots(self, repository_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return read_snapshots(connection, repository_id, limit=limit)

    def timeline_snapshots(self, repository_id: int, *, limit: int = 250) -> list[dict[str, Any]]:
        """Return Git commit frames plus the current working tree, without scan-run duplicates."""

        with self.connect() as connection:
            return read_timeline(connection, repository_id, limit=limit)

    def start_run(self, repository_id: int, run_type: str) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_runs(repository_id, run_type, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (repository_id, run_type, utc_now()),
            )
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        snapshot_id: int | None,
        status: str,
        discovered: int = 0,
        analyzed: int = 0,
        reused: int = 0,
        error_count: int = 0,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE analysis_runs SET snapshot_id = ?, status = ?, completed_at = ?,
                    discovered_count = ?, analyzed_count = ?, reused_count = ?, error_count = ?,
                    metadata_json = ?, error = ?
                WHERE id = ?
                """,
                (
                    snapshot_id,
                    status,
                    utc_now(),
                    discovered,
                    analyzed,
                    reused,
                    error_count,
                    json.dumps(metadata or {}, sort_keys=True),
                    error,
                    run_id,
                ),
            )

    def overview(self, repository_id: int, snapshot_id: int | None = None) -> dict[str, Any]:
        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return {"repository_id": repository_id, "snapshot": None}
        with self.connect() as connection:
            return read_overview(connection, repository_id, snapshot)

    def group_hierarchy(
        self, repository_id: int, snapshot_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Return effective groups rolled up through their configured parent hierarchy."""

        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return []
        with self.connect() as connection:
            install_snapshot_projection(connection, int(snapshot["id"]), include_symbols=False)
            return read_group_hierarchy(connection, repository_id)

    def modules(self, repository_id: int, snapshot_id: int | None = None) -> list[dict[str, Any]]:
        """Return the file-level intelligence ledger for inventory views and agents."""

        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return []
        with self.connect() as connection:
            return read_modules(connection, repository_id, int(snapshot["id"]))

    def _resolve_snapshot(self, repository_id: int, snapshot_id: int | None) -> sqlite3.Row | None:
        with self.connect() as connection:
            if snapshot_id is None:
                row = connection.execute(
                    """
                    SELECT s.* FROM repositories r
                    JOIN snapshots s ON s.id = r.current_snapshot_id
                    WHERE r.id = ?
                    """,
                    (repository_id,),
                ).fetchone()
                if row is not None:
                    return row
                return connection.execute(
                    "SELECT * FROM snapshots WHERE repository_id = ? ORDER BY id DESC LIMIT 1",
                    (repository_id,),
                ).fetchone()
            return connection.execute(
                "SELECT * FROM snapshots WHERE id = ? AND repository_id = ?",
                (snapshot_id, repository_id),
            ).fetchone()

    def graph(
        self,
        repository_id: int,
        snapshot_id: int | None = None,
        *,
        include_external: bool = False,
    ) -> dict[str, Any]:
        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return {"nodes": [], "edges": [], "snapshot": None}
        key = (repository_id, int(snapshot["id"]), include_external)
        cached = self._graph_cache.get(key)
        if cached is not None:
            return cached
        with self.connect() as connection:
            result = read_graph(
                connection,
                repository_id,
                snapshot,
                include_external=include_external,
            )
        self._graph_cache.put(key, result)
        return result

    def file_details(
        self, repository_id: int, path: str, snapshot_id: int | None = None
    ) -> dict[str, Any] | None:
        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return None
        with self.connect() as connection:
            return read_file_details(
                connection,
                repository_id,
                path,
                int(snapshot["id"]),
            )

    def search(self, repository_id: int, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        snapshot = self._resolve_snapshot(repository_id, None)
        if snapshot is None:
            return []
        with self.connect() as connection:
            return search_modules(connection, int(snapshot["id"]), query, limit=limit)

    def findings(
        self,
        repository_id: int,
        *,
        statuses: tuple[str, ...] = (),
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        snapshot = self._resolve_snapshot(repository_id, None)
        snapshot_id = int(snapshot["id"]) if snapshot is not None else None
        with self.connect() as connection:
            return read_findings(
                connection,
                repository_id,
                snapshot_id,
                statuses=statuses,
                limit=limit,
            )

    def finding(self, repository_id: int, finding_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            return read_finding(connection, repository_id, finding_id)

    def update_finding_status(self, repository_id: int, finding_id: int, status: str) -> bool:
        allowed = {
            "new",
            "acknowledged",
            "accepted",
            "dismissed",
            "planned",
            "resolved",
            "regressed",
        }
        if status not in allowed:
            raise ValueError(f"Unsupported finding status: {status}")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE findings SET status = ?, resolved_at = CASE
                    WHEN ? = 'resolved' THEN ?
                    WHEN status = 'resolved' THEN NULL
                    ELSE resolved_at END
                WHERE id = ? AND repository_id = ?
                """,
                (status, status, utc_now(), finding_id, repository_id),
            )
            return cursor.rowcount > 0
