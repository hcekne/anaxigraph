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
from anaxigraph.persistence import (
    migrate_schema,
    relationship_metadata,
    relationship_quality,
    resolution_status,
)

SCHEMA_VERSION = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    remote_url TEXT,
    default_branch TEXT,
    current_snapshot_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    parent_commit_sha TEXT,
    branch TEXT NOT NULL,
    commit_timestamp TEXT,
    analysis_timestamp TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL DEFAULT 'working_tree',
    dirty INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(repository_id, content_fingerprint)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    canonical_path TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    first_seen_commit TEXT,
    deleted_commit TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(repository_id, canonical_path)
);

CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    runtime TEXT,
    declared_group TEXT,
    inferred_group TEXT,
    raw_hash TEXT NOT NULL,
    structural_hash TEXT NOT NULL,
    lines_of_code INTEGER NOT NULL,
    comment_lines INTEGER NOT NULL,
    complexity REAL NOT NULL,
    summary TEXT NOT NULL,
    responsibilities_json TEXT NOT NULL DEFAULT '[]',
    inputs_json TEXT NOT NULL DEFAULT '[]',
    outputs_json TEXT NOT NULL DEFAULT '[]',
    side_effects_json TEXT NOT NULL DEFAULT '[]',
    public_interfaces_json TEXT NOT NULL DEFAULT '[]',
    analyzer TEXT NOT NULL,
    analysis_status TEXT NOT NULL,
    parse_error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_changed_at TEXT NOT NULL,
    UNIQUE(snapshot_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    artifact_version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
    symbol_type TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    complexity REAL NOT NULL DEFAULT 1,
    logical_lines INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    source_artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    target_artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    target_external TEXT,
    relationship_type TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    source_line INTEGER NOT NULL DEFAULT 0,
    weight REAL NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK(target_artifact_id IS NOT NULL OR target_external IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    level TEXT NOT NULL,
    parent_name TEXT,
    source TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE(repository_id, name, source)
);

CREATE TABLE IF NOT EXISTS group_memberships (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    confidence REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(snapshot_id, artifact_id, group_id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS coverage_measurements (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    relationship_id INTEGER REFERENCES relationships(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    line_coverage REAL,
    branch_coverage REAL,
    function_coverage REAL,
    covered_lines INTEGER,
    total_lines INTEGER,
    evidence TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    stable_key TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    summary TEXT NOT NULL,
    explanation TEXT NOT NULL,
    affected_artifacts_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    recommended_action TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'deterministic',
    status TEXT NOT NULL DEFAULT 'new',
    first_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    last_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    first_detected_at TEXT NOT NULL,
    last_detected_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(repository_id, stable_key)
);

CREATE TABLE IF NOT EXISTS finding_occurrences (
    finding_id INTEGER NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    detected_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY(finding_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    analyzed_count INTEGER NOT NULL DEFAULT 0,
    reused_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE TABLE IF NOT EXISTS architecture_rules (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(repository_id, rule_id)
);

CREATE TABLE IF NOT EXISTS semantic_claims (
    id INTEGER PRIMARY KEY,
    artifact_version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
    claim_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    executor_id TEXT,
    executor_model TEXT,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confidence REAL NOT NULL,
    supporting_evidence_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS semantic_documents (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    artifact_version_id INTEGER REFERENCES file_versions(id) ON DELETE CASCADE,
    previous_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    document_kind TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    intent_fingerprint TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    confidence REAL NOT NULL,
    supporting_evidence_json TEXT NOT NULL DEFAULT '[]',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantic_jobs (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    artifact_version_id INTEGER REFERENCES file_versions(id) ON DELETE CASCADE,
    job_kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    input_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    available_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    worker_id TEXT,
    lease_expires_at TEXT,
    lease_token_hash TEXT,
    executor_id TEXT,
    executor_model TEXT,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS semantic_scope_states (
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    artifact_version_id INTEGER REFERENCES file_versions(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    intrinsic_input_hash TEXT,
    context_input_hash TEXT,
    interface_hash TEXT,
    relationship_hash TEXT,
    context_fingerprint TEXT,
    intrinsic_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    context_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    last_checked_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, scope_type, scope_key)
);

CREATE TABLE IF NOT EXISTS git_changes (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    committed_at TEXT,
    author_name TEXT,
    subject TEXT,
    path TEXT NOT NULL,
    change_type TEXT NOT NULL,
    additions INTEGER,
    deletions INTEGER,
    UNIQUE(repository_id, commit_sha, path)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_repository ON snapshots(repository_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_repository ON artifacts(repository_id, canonical_path);
CREATE INDEX IF NOT EXISTS idx_versions_snapshot ON file_versions(snapshot_id, path);
CREATE INDEX IF NOT EXISTS idx_versions_artifact ON file_versions(artifact_id, snapshot_id DESC);
CREATE INDEX IF NOT EXISTS idx_symbols_version ON symbols(artifact_version_id);
CREATE INDEX IF NOT EXISTS idx_relationships_snapshot_source ON relationships(snapshot_id, source_artifact_id);
CREATE INDEX IF NOT EXISTS idx_relationships_snapshot_target ON relationships(snapshot_id, target_artifact_id);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshot ON metrics(snapshot_id, name);
CREATE INDEX IF NOT EXISTS idx_findings_repository_status ON findings(repository_id, status);
CREATE INDEX IF NOT EXISTS idx_git_changes_repository_path ON git_changes(repository_id, path);
CREATE INDEX IF NOT EXISTS idx_semantic_documents_scope
    ON semantic_documents(repository_id, scope_type, scope_key, document_kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_jobs_queue
    ON semantic_jobs(repository_id, status, available_at, priority DESC, id);
CREATE INDEX IF NOT EXISTS idx_semantic_states_snapshot
    ON semantic_scope_states(snapshot_id, scope_type, status);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AnaxiIndex:
    """Persistent repository knowledge store used by AnaxiGraph and AnaxiMCP."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            migrate_schema(
                connection,
                current_version=int(row["value"]) if row is not None else None,
                target_version=SCHEMA_VERSION,
            )

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
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
            rows = connection.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*)
                          FROM file_versions fv
                         WHERE fv.snapshot_id = s.id) AS file_count,
                       (SELECT COALESCE(SUM(fv.lines_of_code), 0)
                          FROM file_versions fv
                         WHERE fv.snapshot_id = s.id) AS lines_of_code,
                       (SELECT COUNT(*)
                          FROM relationships rel
                         WHERE rel.snapshot_id = s.id) AS relationship_count
                FROM snapshots s
                WHERE s.repository_id = ?
                ORDER BY COALESCE(datetime(s.commit_timestamp), s.analysis_timestamp) DESC,
                         s.id DESC
                LIMIT ?
                """,
                (repository_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def timeline_snapshots(self, repository_id: int, *, limit: int = 250) -> list[dict[str, Any]]:
        """Return Git commit frames plus the current working tree, without scan-run duplicates."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*) FROM file_versions fv
                         WHERE fv.snapshot_id = s.id) AS file_count,
                       (SELECT COALESCE(SUM(fv.lines_of_code), 0) FROM file_versions fv
                         WHERE fv.snapshot_id = s.id) AS lines_of_code,
                       (SELECT COUNT(*) FROM relationships rel
                         WHERE rel.snapshot_id = s.id) AS relationship_count
                FROM snapshots s
                JOIN repositories r ON r.id = s.repository_id
                WHERE s.repository_id = ?
                  AND (s.snapshot_kind = 'commit' OR s.id = r.current_snapshot_id)
                ORDER BY COALESCE(datetime(s.commit_timestamp), s.analysis_timestamp), s.id
                """,
                (repository_id,),
            ).fetchall()

        commit_frames: list[dict[str, Any]] = []
        commit_indexes: dict[str, int] = {}
        current: dict[str, Any] | None = None
        repository = self.repository(repository_id)
        current_id = (
            int(repository["current_snapshot_id"])
            if repository and repository.get("current_snapshot_id")
            else None
        )
        for row in rows:
            item = dict(row)
            if current_id is not None and int(item["id"]) == current_id:
                current = item
            if item["snapshot_kind"] != "commit":
                continue
            commit_sha = str(item["commit_sha"])
            if commit_sha in commit_indexes:
                commit_frames[commit_indexes[commit_sha]] = item
            else:
                commit_indexes[commit_sha] = len(commit_frames)
                commit_frames.append(item)

        if current is not None:
            same_fingerprint = next(
                (
                    index
                    for index, frame in enumerate(commit_frames)
                    if frame["content_fingerprint"] == current["content_fingerprint"]
                ),
                None,
            )
            same_commit = commit_indexes.get(str(current["commit_sha"]))
            if same_fingerprint is not None:
                commit_frames[same_fingerprint] = current
            elif current.get("dirty") or same_commit is None:
                commit_frames.append(current)
            else:
                commit_frames[same_commit] = current

        bounded = max(1, limit)
        if len(commit_frames) <= bounded:
            return commit_frames
        if bounded == 1:
            return [commit_frames[-1]]
        indexes = {
            round(index * (len(commit_frames) - 1) / (bounded - 1)) for index in range(bounded)
        }
        return [commit_frames[index] for index in sorted(indexes)]

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
        snapshot_id = int(snapshot["id"])
        with self.connect() as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) AS files,
                       COALESCE(SUM(lines_of_code), 0) AS lines_of_code,
                       COALESCE(SUM(comment_lines), 0) AS comment_lines,
                       COALESCE(AVG(complexity), 0) AS average_complexity,
                       COALESCE(MAX(complexity), 0) AS maximum_complexity,
                       COUNT(DISTINCT language) AS language_count
                FROM file_versions WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()
            relationship_rows = connection.execute(
                """
                SELECT target_artifact_id, metadata_json
                FROM relationships WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchall()
            symbols = connection.execute(
                """
                SELECT COUNT(*) AS count FROM symbols s
                JOIN file_versions fv ON fv.id = s.artifact_version_id
                WHERE fv.snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()
            findings = connection.execute(
                """
                SELECT severity, COUNT(*) AS count FROM findings
                WHERE repository_id = ? AND status NOT IN ('resolved', 'dismissed')
                GROUP BY severity
                """,
                (repository_id,),
            ).fetchall()
            languages = connection.execute(
                """
                SELECT language, COUNT(*) AS files, SUM(lines_of_code) AS lines_of_code
                FROM file_versions WHERE snapshot_id = ?
                GROUP BY language ORDER BY lines_of_code DESC, language
                """,
                (snapshot_id,),
            ).fetchall()
            groups = connection.execute(
                """
                SELECT COALESCE(declared_group, inferred_group, 'ungrouped') AS name,
                       COUNT(*) AS files, SUM(lines_of_code) AS lines_of_code
                FROM file_versions WHERE snapshot_id = ?
                GROUP BY name ORDER BY lines_of_code DESC
                """,
                (snapshot_id,),
            ).fetchall()
            coverage = connection.execute(
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
            relationship_coverage = connection.execute(
                """
                SELECT CAST(COUNT(DISTINCT cm.relationship_id) AS REAL) /
                       NULLIF((SELECT COUNT(*) FROM relationships r
                               WHERE r.snapshot_id = ? AND r.target_artifact_id IS NOT NULL), 0)
                       AS value
                FROM coverage_measurements cm
                WHERE cm.snapshot_id = ? AND cm.relationship_id IS NOT NULL
                """,
                (snapshot_id, snapshot_id),
            ).fetchone()
            graph_quality = _graph_quality(
                connection,
                snapshot_id,
                [dict(row) for row in relationship_rows],
            )
        return {
            "repository_id": repository_id,
            "snapshot": dict(snapshot),
            **dict(totals or {}),
            "relationships": len(relationship_rows),
            "graph_quality": graph_quality,
            "symbols": int(symbols["count"] if symbols else 0),
            "findings": {row["severity"]: row["count"] for row in findings},
            "languages": [dict(row) for row in languages],
            "groups": [dict(row) for row in groups],
            "group_hierarchy": self.group_hierarchy(repository_id, snapshot_id),
            "coverage": {
                **dict(coverage or {}),
                "relationship_coverage": (
                    relationship_coverage["value"] if relationship_coverage else None
                ),
            },
        }

    def group_hierarchy(
        self, repository_id: int, snapshot_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Return effective groups rolled up through their configured parent hierarchy."""

        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return []
        sid = int(snapshot["id"])
        with self.connect() as connection:
            stat_rows = connection.execute(
                """
                SELECT COALESCE(declared_group, inferred_group, 'ungrouped') AS name,
                       COUNT(*) AS files,
                       COALESCE(SUM(lines_of_code), 0) AS lines_of_code,
                       SUM(CASE WHEN declared_group IS NOT NULL THEN 1 ELSE 0 END)
                           AS declared_files
                FROM file_versions WHERE snapshot_id = ?
                GROUP BY name
                """,
                (sid,),
            ).fetchall()
            metadata_rows = connection.execute(
                """
                SELECT name, level, parent_name, source, description
                FROM groups WHERE repository_id = ?
                ORDER BY CASE source WHEN 'declared' THEN 0 ELSE 1 END, name
                """,
                (repository_id,),
            ).fetchall()

        metadata: dict[str, dict[str, Any]] = {}
        for row in metadata_rows:
            # Declared policy is authoritative when a same-named inferred group also exists.
            metadata.setdefault(row["name"], dict(row))

        nodes: dict[str, dict[str, Any]] = {}
        for row in stat_rows:
            name = str(row["name"])
            files = int(row["files"] or 0)
            declared_files = int(row["declared_files"] or 0)
            source = (
                "declared"
                if declared_files == files
                else "inferred"
                if declared_files == 0
                else "mixed"
            )
            nodes[name] = {
                "name": name,
                "level": "subsystem",
                "parent": None,
                "source": source,
                "description": "",
                "direct_files": files,
                "direct_lines_of_code": int(row["lines_of_code"] or 0),
            }

        for name, item in metadata.items():
            if name not in nodes and item["source"] != "declared":
                # Inferred membership rows are historical implementation details. Only an
                # inferred group that is effective in this snapshot belongs in the overview.
                continue
            node = nodes.setdefault(
                name,
                {
                    "name": name,
                    "level": item["level"],
                    "parent": None,
                    "source": item["source"],
                    "description": "",
                    "direct_files": 0,
                    "direct_lines_of_code": 0,
                },
            )
            node.update(
                level=item["level"],
                parent=item["parent_name"],
                description=item["description"] or "",
            )
            if node["direct_files"] == 0:
                node["source"] = item["source"]

        # A parent may be intentionally virtual: MaxOS declares backend-api as a child of
        # backend while unmatched backend files use the inferred backend group.
        for node in list(nodes.values()):
            parent = node["parent"]
            if parent and parent not in nodes:
                nodes[parent] = {
                    "name": parent,
                    "level": "area",
                    "parent": None,
                    "source": "derived",
                    "description": f"Top-level {parent.replace('-', ' ')} architecture area.",
                    "direct_files": 0,
                    "direct_lines_of_code": 0,
                }

        children: dict[str, list[str]] = {name: [] for name in nodes}
        for name, node in nodes.items():
            parent = node["parent"]
            if parent and parent in nodes and parent != name:
                children[parent].append(name)

        for name, child_names in children.items():
            node = nodes[name]
            if child_names and not node["parent"]:
                node["level"] = "area"
                node["source"] = "mixed" if node["direct_files"] else "derived"
                if not node["description"]:
                    node["description"] = (
                        f"Top-level {name.replace('-', ' ')} area; child subsystems remain "
                        "separate so their responsibilities and dependency rules stay visible."
                    )

        def materialize(name: str, ancestors: frozenset[str] = frozenset()) -> dict[str, Any]:
            node = nodes[name]
            if name in ancestors:
                child_items: list[dict[str, Any]] = []
            else:
                child_items = [
                    materialize(child, ancestors | {name}) for child in sorted(children[name])
                ]
            files = int(node["direct_files"]) + sum(int(item["files"]) for item in child_items)
            lines = int(node["direct_lines_of_code"]) + sum(
                int(item["lines_of_code"]) for item in child_items
            )
            return {
                **node,
                "files": files,
                "lines_of_code": lines,
                "children": sorted(
                    child_items,
                    key=lambda item: (-int(item["lines_of_code"]), item["name"]),
                ),
            }

        roots = [
            name
            for name, node in nodes.items()
            if not node["parent"] or node["parent"] not in nodes or node["parent"] == name
        ]
        materialized = [materialize(name) for name in roots]
        return sorted(
            (item for item in materialized if int(item["files"]) > 0),
            key=lambda item: (-int(item["lines_of_code"]), item["name"]),
        )

    def modules(self, repository_id: int, snapshot_id: int | None = None) -> list[dict[str, Any]]:
        """Return the file-level intelligence ledger for inventory views and agents."""

        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return []
        sid = int(snapshot["id"])
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.id AS artifact_id, a.artifact_type, a.canonical_path,
                       a.first_seen_commit, fv.id AS artifact_version_id, fv.path,
                       fv.language, fv.runtime, fv.declared_group, fv.inferred_group,
                       fv.raw_hash, fv.structural_hash, fv.lines_of_code, fv.comment_lines,
                       fv.complexity, fv.summary, fv.responsibilities_json,
                       fv.public_interfaces_json, fv.analyzer, fv.analysis_status,
                       fv.parse_error, fv.first_seen_at, fv.last_changed_at,
                       COALESCE(incoming.count, 0) AS fan_in,
                       COALESCE(outgoing.count, 0) AS fan_out,
                       coverage.line_coverage,
                       COALESCE(history.change_count, 0) AS change_count,
                       history.first_changed_at, history.last_changed_at AS last_commit_at,
                       history.additions, history.deletions,
                       (SELECT gc.commit_sha FROM git_changes gc
                        WHERE gc.repository_id = ? AND gc.path = fv.path
                        ORDER BY gc.committed_at ASC LIMIT 1) AS first_change_commit,
                       (SELECT gc.commit_sha FROM git_changes gc
                        WHERE gc.repository_id = ? AND gc.path = fv.path
                        ORDER BY gc.committed_at DESC LIMIT 1) AS last_change_commit,
                       (SELECT gc.subject FROM git_changes gc
                        WHERE gc.repository_id = ? AND gc.path = fv.path
                        ORDER BY gc.committed_at DESC LIMIT 1) AS last_change_subject
                FROM file_versions fv
                JOIN artifacts a ON a.id = fv.artifact_id
                LEFT JOIN (
                    SELECT target_artifact_id, COUNT(*) AS count FROM relationships
                    WHERE snapshot_id = ? AND target_artifact_id IS NOT NULL
                    GROUP BY target_artifact_id
                ) incoming ON incoming.target_artifact_id = a.id
                LEFT JOIN (
                    SELECT source_artifact_id, COUNT(*) AS count FROM relationships
                    WHERE snapshot_id = ? GROUP BY source_artifact_id
                ) outgoing ON outgoing.source_artifact_id = a.id
                LEFT JOIN (
                    SELECT snapshot_id, artifact_id, MAX(line_coverage) AS line_coverage
                    FROM coverage_measurements WHERE artifact_id IS NOT NULL
                    GROUP BY snapshot_id, artifact_id
                ) coverage ON coverage.snapshot_id = fv.snapshot_id
                          AND coverage.artifact_id = a.id
                LEFT JOIN (
                    SELECT repository_id, path, COUNT(*) AS change_count,
                           MIN(committed_at) AS first_changed_at,
                           MAX(committed_at) AS last_changed_at,
                           SUM(COALESCE(additions, 0)) AS additions,
                           SUM(COALESCE(deletions, 0)) AS deletions
                    FROM git_changes WHERE repository_id = ?
                    GROUP BY repository_id, path
                ) history ON history.repository_id = a.repository_id AND history.path = fv.path
                WHERE fv.snapshot_id = ? ORDER BY fv.path
                """,
                (repository_id, repository_id, repository_id, sid, sid, repository_id, sid),
            ).fetchall()
            group_rows = connection.execute(
                """
                SELECT name, parent_name, source FROM groups
                WHERE repository_id = ?
                ORDER BY CASE source WHEN 'declared' THEN 0 ELSE 1 END
                """,
                (repository_id,),
            ).fetchall()
            claim_rows = connection.execute(
                """
                SELECT sc.* FROM semantic_claims sc
                JOIN file_versions fv ON fv.id = sc.artifact_version_id
                WHERE fv.snapshot_id = ?
                  AND sc.claim_type IN ('module_analysis', 'module_context')
                ORDER BY CASE sc.claim_type WHEN 'module_analysis' THEN 0 ELSE 1 END
                """,
                (sid,),
            ).fetchall()
            semantic_state_rows = connection.execute(
                """
                SELECT ss.*, intrinsic.intent_fingerprint AS intrinsic_intent_fingerprint,
                       intrinsic.created_at AS intrinsic_created_at,
                       context.intent_fingerprint AS context_intent_fingerprint,
                       context.created_at AS context_created_at,
                       context.value_json AS context_value_json,
                       context.confidence AS context_confidence,
                       context.provider AS context_provider,
                       context.model AS context_model,
                       context.executor_id AS context_executor_id,
                       context.executor_model AS context_executor_model
                FROM semantic_scope_states ss
                LEFT JOIN semantic_documents intrinsic ON intrinsic.id = ss.intrinsic_document_id
                LEFT JOIN semantic_documents context ON context.id = ss.context_document_id
                WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
                """,
                (sid,),
            ).fetchall()
            finding_rows = connection.execute(
                """
                SELECT id, finding_type, severity, summary, status, affected_artifacts_json
                FROM findings WHERE repository_id = ?
                  AND status NOT IN ('resolved', 'dismissed')
                """,
                (repository_id,),
            ).fetchall()

        parents: dict[str, str | None] = {}
        for row in group_rows:
            parents.setdefault(str(row["name"]), row["parent_name"])

        claims: dict[int, dict[str, Any]] = {}
        for row in claim_rows:
            claims[int(row["artifact_version_id"])] = {
                "value": json.loads(row["value_json"] or "{}"),
                "source": row["source"],
                "provider": row["provider"],
                "model": row["model"],
                "claim_type": row["claim_type"],
                "confidence": row["confidence"],
            }
        semantic_states = {str(row["scope_key"]): dict(row) for row in semantic_state_rows}

        findings_by_path: dict[str, list[dict[str, Any]]] = {}
        for row in finding_rows:
            finding = dict(row)
            paths = json.loads(finding.pop("affected_artifacts_json") or "[]")
            for path in paths:
                findings_by_path.setdefault(str(path), []).append(finding)

        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["responsibilities"] = json.loads(item.pop("responsibilities_json") or "[]")
            item["public_interfaces"] = json.loads(item.pop("public_interfaces_json") or "[]")
            group = item["declared_group"] or item["inferred_group"] or "ungrouped"
            area = str(group)
            visited: set[str] = set()
            while parents.get(area) and area not in visited:
                visited.add(area)
                area = str(parents[area])
            item["name"] = Path(item["path"]).name
            item["architecture_area"] = area
            item["architecture_subsystem"] = group if group != area else None
            item["architecture_group"] = group
            item["architecture_source"] = "configured" if item["declared_group"] else "inferred"
            claim = claims.get(int(item["artifact_version_id"]))
            if claim:
                item["deterministic_summary"] = item["summary"]
                item["summary"] = claim["value"].get("summary") or item["summary"]
                phase = "contextual" if claim["claim_type"] == "module_context" else "intrinsic"
                item["summary_source"] = f"{claim['provider']} {phase} interpretation"
                item["summary_confidence"] = claim["confidence"]
            else:
                item["summary_source"] = "deterministic"
                item["summary_confidence"] = 1.0
            semantic_state = semantic_states.get(item["path"])
            context_value = (
                json.loads(semantic_state.get("context_value_json") or "{}")
                if semantic_state
                else {}
            )
            item["semantic"] = (
                {
                    "status": semantic_state["status"],
                    "reason": semantic_state["reason"],
                    "intent_fingerprint": semantic_state["intrinsic_intent_fingerprint"],
                    "context_intent_fingerprint": semantic_state["context_intent_fingerprint"],
                    "context_fingerprint": semantic_state["context_fingerprint"],
                    "intrinsic_created_at": semantic_state["intrinsic_created_at"],
                    "context_created_at": semantic_state["context_created_at"],
                    "provider": semantic_state["context_provider"],
                    "model": semantic_state["context_model"],
                    "executor_id": semantic_state["context_executor_id"],
                    "executor_model": semantic_state["context_executor_model"],
                    "confidence": semantic_state["context_confidence"],
                    "architecture_role": context_value.get("architecture_role") or "",
                    "pattern_opportunities": context_value.get("pattern_opportunities") or [],
                    "consolidation_assessment": context_value.get("consolidation_assessment") or "",
                    "dead_code_candidates": context_value.get("dead_code_candidates") or [],
                    "placement_guidance": context_value.get("placement_guidance") or "",
                    "change_summary": context_value.get("change_summary") or "",
                }
                if semantic_state
                else {"status": "not_started", "reason": "Semantic bootstrap has not run"}
            )
            active_findings = findings_by_path.get(item["path"], [])
            item["active_findings"] = active_findings
            item["evaluation"] = _module_evaluation(item, active_findings)
            result.append(item)
        return result

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
        sid = int(snapshot["id"])
        with self.connect() as connection:
            node_rows = connection.execute(
                """
                SELECT a.id, fv.path, fv.language, fv.lines_of_code, fv.complexity,
                       fv.summary, fv.declared_group, fv.inferred_group, fv.analysis_status,
                       fv.last_changed_at,
                       COALESCE(incoming.count, 0) AS fan_in,
                       COALESCE(outgoing.count, 0) AS fan_out,
                       cm.line_coverage,
                       (SELECT COUNT(*) FROM git_changes gc
                        WHERE gc.repository_id = ? AND gc.path = fv.path) AS change_count
                FROM file_versions fv
                JOIN artifacts a ON a.id = fv.artifact_id
                LEFT JOIN (
                    SELECT target_artifact_id, COUNT(*) AS count FROM relationships
                    WHERE snapshot_id = ? AND target_artifact_id IS NOT NULL
                    GROUP BY target_artifact_id
                ) incoming ON incoming.target_artifact_id = a.id
                LEFT JOIN (
                    SELECT source_artifact_id, COUNT(*) AS count FROM relationships
                    WHERE snapshot_id = ? GROUP BY source_artifact_id
                ) outgoing ON outgoing.source_artifact_id = a.id
                LEFT JOIN (
                    SELECT snapshot_id, artifact_id, MAX(line_coverage) AS line_coverage
                    FROM coverage_measurements WHERE artifact_id IS NOT NULL
                    GROUP BY snapshot_id, artifact_id
                ) cm ON cm.snapshot_id = fv.snapshot_id AND cm.artifact_id = a.id
                WHERE fv.snapshot_id = ? ORDER BY fv.path
                """,
                (repository_id, sid, sid, sid),
            ).fetchall()
            edge_rows = connection.execute(
                """
                SELECT r.id, r.source_artifact_id AS source, r.target_artifact_id AS target,
                       r.target_external, r.relationship_type AS type, r.source AS evidence_source,
                       r.confidence, r.weight, r.evidence, r.source_line, r.metadata_json
                FROM relationships r WHERE r.snapshot_id = ?
                ORDER BY r.source_artifact_id, r.target_artifact_id, r.target_external
                """,
                (sid,),
            ).fetchall()
            quality = _graph_quality(
                connection,
                sid,
                [dict(row) for row in edge_rows],
            )
        nodes = [dict(row) for row in node_rows]
        edges = []
        external_nodes: dict[str, tuple[str, str]] = {}
        for row in edge_rows:
            edge = dict(row)
            metadata = relationship_metadata(edge)
            edge["resolution_status"] = resolution_status(edge)
            edge["candidate_paths"] = metadata.get("candidate_paths", [])
            edge["metadata"] = metadata
            edge.pop("metadata_json", None)
            if edge["target"] is None:
                if not include_external:
                    continue
                label = edge["target_external"]
                external_id = f"{edge['resolution_status']}:{label}"
                external_nodes.setdefault(external_id, (str(label), edge["resolution_status"]))
                edge["target"] = external_id
            edges.append(edge)
        if include_external:
            nodes.extend(
                {
                    "id": external_id,
                    "path": label,
                    "language": "external" if status == "external" else "unresolved",
                    "lines_of_code": 0,
                    "complexity": 0,
                    "summary": (
                        f"External dependency {label}"
                        if status == "external"
                        else f"{status.replace('_', ' ').title()} reference {label}"
                    ),
                    "declared_group": "external" if status == "external" else "unresolved",
                    "inferred_group": "external" if status == "external" else "unresolved",
                    "analysis_status": status,
                    "fan_in": 0,
                    "fan_out": 0,
                    "line_coverage": None,
                }
                for external_id, (label, status) in external_nodes.items()
            )
        return {
            "snapshot": dict(snapshot),
            "nodes": nodes,
            "edges": edges,
            "quality": quality,
        }

    def file_details(
        self, repository_id: int, path: str, snapshot_id: int | None = None
    ) -> dict[str, Any] | None:
        snapshot = self._resolve_snapshot(repository_id, snapshot_id)
        if snapshot is None:
            return None
        sid = int(snapshot["id"])
        with self.connect() as connection:
            version = connection.execute(
                """
                SELECT fv.*, a.canonical_path, a.artifact_type, a.first_seen_commit,
                       a.deleted_commit
                FROM file_versions fv JOIN artifacts a ON a.id = fv.artifact_id
                WHERE fv.snapshot_id = ? AND fv.path = ?
                """,
                (sid, path),
            ).fetchone()
            if version is None:
                return None
            symbols = connection.execute(
                "SELECT * FROM symbols WHERE artifact_version_id = ? ORDER BY start_line",
                (version["id"],),
            ).fetchall()
            relationships = connection.execute(
                """
                SELECT r.*, target.canonical_path AS target_path
                FROM relationships r
                LEFT JOIN artifacts target ON target.id = r.target_artifact_id
                WHERE r.snapshot_id = ? AND r.source_artifact_id = ?
                ORDER BY r.source_line, target_path, r.target_external
                """,
                (sid, version["artifact_id"]),
            ).fetchall()
            dependants = connection.execute(
                """
                SELECT r.*, source.canonical_path AS source_path
                FROM relationships r JOIN artifacts source ON source.id = r.source_artifact_id
                WHERE r.snapshot_id = ? AND r.target_artifact_id = ?
                ORDER BY source_path
                """,
                (sid, version["artifact_id"]),
            ).fetchall()
            history = connection.execute(
                """
                SELECT commit_sha, committed_at, author_name, subject, change_type,
                       additions, deletions FROM git_changes
                WHERE repository_id = ? AND path = ? ORDER BY committed_at DESC LIMIT 50
                """,
                (repository_id, path),
            ).fetchall()
            claims = connection.execute(
                "SELECT * FROM semantic_claims WHERE artifact_version_id = ?",
                (version["id"],),
            ).fetchall()
            semantic_state = connection.execute(
                """
                SELECT * FROM semantic_scope_states
                WHERE snapshot_id = ? AND scope_type = 'module' AND scope_key = ?
                """,
                (sid, path),
            ).fetchone()
            semantic_documents: dict[str, dict[str, Any]] = {}
            if semantic_state is not None:
                for kind, document_id in (
                    ("intrinsic", semantic_state["intrinsic_document_id"]),
                    ("context", semantic_state["context_document_id"]),
                ):
                    if not document_id:
                        continue
                    document = connection.execute(
                        "SELECT * FROM semantic_documents WHERE id = ?", (document_id,)
                    ).fetchone()
                    if document is not None:
                        semantic_documents[kind] = _decode_json_columns(dict(document))
        result = dict(version)
        for key in (
            "responsibilities_json",
            "inputs_json",
            "outputs_json",
            "side_effects_json",
            "public_interfaces_json",
            "metadata_json",
        ):
            result[key.removesuffix("_json")] = json.loads(result.pop(key) or "null")
        return {
            "file": result,
            "symbols": [dict(row) for row in symbols],
            "relationships": [_decode_relationship(dict(row)) for row in relationships],
            "dependants": [_decode_relationship(dict(row)) for row in dependants],
            "history": [dict(row) for row in history],
            "semantic_claims": [_decode_json_columns(dict(row)) for row in claims],
            "semantic_state": dict(semantic_state) if semantic_state else None,
            "semantic_dossiers": semantic_documents,
        }

    def search(self, repository_id: int, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        snapshot = self._resolve_snapshot(repository_id, None)
        if snapshot is None:
            return []
        terms = [term.lower() for term in query.split() if len(term) > 1]
        if not terms:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.id AS artifact_id, fv.path, fv.language, fv.summary,
                       fv.declared_group, fv.inferred_group, fv.lines_of_code,
                       GROUP_CONCAT(s.name, ' ') AS symbol_names
                FROM file_versions fv JOIN artifacts a ON a.id = fv.artifact_id
                LEFT JOIN symbols s ON s.artifact_version_id = fv.id
                WHERE fv.snapshot_id = ? GROUP BY fv.id
                """,
                (snapshot["id"],),
            ).fetchall()
            semantic_rows = connection.execute(
                """
                SELECT ss.artifact_id, ss.status, sd.value_json, sd.provider,
                       sd.model, sd.confidence, sd.document_kind
                FROM semantic_scope_states ss
                LEFT JOIN semantic_documents sd
                  ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
                WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
                """,
                (snapshot["id"],),
            ).fetchall()
        semantic_by_artifact = {
            int(row["artifact_id"]): {
                **dict(row),
                "value": json.loads(row["value_json"] or "{}"),
            }
            for row in semantic_rows
            if row["artifact_id"] is not None
        }
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            item = dict(row)
            semantic = semantic_by_artifact.get(int(item["artifact_id"]))
            semantic_value = semantic["value"] if semantic else {}
            if semantic_value.get("summary"):
                item["deterministic_summary"] = item["summary"]
                item["summary"] = semantic_value["summary"]
            if semantic:
                item["semantic"] = {
                    "status": semantic["status"],
                    "source": semantic["document_kind"],
                    "provider": semantic["provider"],
                    "model": semantic["model"],
                    "confidence": semantic["confidence"],
                }
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("path", "summary", "declared_group", "inferred_group", "symbol_names")
            )
            haystack += " " + " ".join(
                str(value)
                for value in (
                    semantic_value.get("detailed_summary"),
                    semantic_value.get("architecture_role"),
                    semantic_value.get("placement_guidance"),
                    *(semantic_value.get("responsibilities") or []),
                    *(semantic_value.get("domain_concepts") or []),
                )
                if value
            )
            haystack = haystack.lower()
            path = item["path"].lower()
            score = sum(
                8 * path.count(term) + 3 * haystack.count(term) + (10 if path == term else 0)
                for term in terms
            )
            if score:
                item["score"] = score
                scored.append((score, item))
        return [
            item for _, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]["path"]))[:limit]
        ]

    def findings(
        self,
        repository_id: int,
        *,
        statuses: tuple[str, ...] = (),
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        snapshot = self._resolve_snapshot(repository_id, None)
        params: list[Any] = [repository_id]
        condition = "repository_id = ?"
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            condition += f" AND status IN ({placeholders})"
            params.extend(statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM findings WHERE {condition}
                ORDER BY last_detected_at DESC
                """,
                params,
            ).fetchall()
            module_stats: dict[str, dict[str, Any]] = {}
            if snapshot is not None:
                sid = int(snapshot["id"])
                stat_rows = connection.execute(
                    """
                    SELECT fv.path, fv.complexity,
                           COALESCE(incoming.count, 0) AS fan_in,
                           COALESCE(outgoing.count, 0) AS fan_out,
                           COALESCE(history.change_count, 0) AS change_count,
                           coverage.line_coverage
                    FROM file_versions fv
                    LEFT JOIN (
                        SELECT target_artifact_id, COUNT(*) AS count FROM relationships
                        WHERE snapshot_id = ? AND target_artifact_id IS NOT NULL
                        GROUP BY target_artifact_id
                    ) incoming ON incoming.target_artifact_id = fv.artifact_id
                    LEFT JOIN (
                        SELECT source_artifact_id, COUNT(*) AS count FROM relationships
                        WHERE snapshot_id = ? GROUP BY source_artifact_id
                    ) outgoing ON outgoing.source_artifact_id = fv.artifact_id
                    LEFT JOIN (
                        SELECT path, COUNT(*) AS change_count FROM git_changes
                        WHERE repository_id = ? GROUP BY path
                    ) history ON history.path = fv.path
                    LEFT JOIN (
                        SELECT artifact_id, MAX(line_coverage) AS line_coverage
                        FROM coverage_measurements WHERE snapshot_id = ?
                        AND artifact_id IS NOT NULL GROUP BY artifact_id
                    ) coverage ON coverage.artifact_id = fv.artifact_id
                    WHERE fv.snapshot_id = ?
                    """,
                    (sid, sid, repository_id, sid, sid),
                ).fetchall()
                module_stats = {str(row["path"]): dict(row) for row in stat_rows}

        ranked = []
        for row in rows:
            item = _decode_json_columns(dict(row))
            item.update(_finding_priority(item, module_stats))
            ranked.append(item)
        return sorted(
            ranked,
            key=lambda item: (
                -int(item["priority_score"]),
                -int(item["id"]),
            ),
        )[:limit]

    def finding(self, repository_id: int, finding_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT f.*,
                       (SELECT COUNT(*) FROM finding_occurrences occurrence
                         WHERE occurrence.finding_id = f.id) AS occurrence_count
                FROM findings f WHERE f.repository_id = ? AND f.id = ?
                """,
                (repository_id, finding_id),
            ).fetchone()
        return _decode_json_columns(dict(row)) if row else None

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


_PATTERN_REVIEWS = {
    "architecture_drift": "Architecture-role review",
    "architecture_violation": "Layer boundary or adapter review",
    "dependency_cycle": "Dependency inversion or boundary review",
    "high_fan_in": "Stable interface boundary review",
    "high_fan_out": "Facade or orchestration boundary review",
    "long_function": "Focused operation extraction review",
    "module_complexity": "Module cohesion and extraction review",
    "possible_dead_code": "Ownership or removal review",
    "symbol_complexity": "Strategy or decision-table review",
    "weak_test_coverage": "Test seam review",
}


def _module_evaluation(item: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Build reproducible triage signals without pretending they are pattern suitability."""

    artifact_type = str(item.get("artifact_type") or "source")
    monitored = artifact_type in {"source", "test"}
    if not monitored:
        kind = {
            "documentation": "Documentation/reference file",
            "configuration": "Configuration/manifest file",
            "asset": "Presentation asset",
        }.get(artifact_type, f"{artifact_type.capitalize()} artifact")
        return {
            "monitored_by_default": False,
            "monitoring_reason": (
                f"{kind}; retained in AnaxiIndex but excluded from source-code attention triage."
            ),
            "attention_score": None,
            "attention_label": "Reference",
            "attention_reasons": [
                f"{kind}; size and churn are not source-module refactoring signals"
            ],
            "pattern_status": "not_applicable",
            "pattern_candidates": [],
            "suitability_score": None,
            "note": (
                "Reference artifacts remain searchable and visible on demand, but are not "
                "ranked against executable modules."
            ),
        }

    loc = int(item.get("lines_of_code") or 0)
    complexity = float(item.get("complexity") or 0)
    coupling = int(item.get("fan_in") or 0) + int(item.get("fan_out") or 0)
    changes = int(item.get("change_count") or 0)
    severity_points = {"critical": 8, "error": 7, "warning": 5, "info": 2}
    finding_pressure = min(
        20,
        sum(severity_points.get(str(finding.get("severity")), 2) for finding in findings),
    )
    score = round(
        min(loc / 500, 1) * 25
        + min(complexity / 50, 1) * 20
        + min(coupling / 30, 1) * 20
        + min(changes / 20, 1) * 15
        + finding_pressure
    )
    label = "Low"
    if score >= 75:
        label = "Priority"
    elif score >= 50:
        label = "Review"
    elif score >= 25:
        label = "Watch"

    reasons: list[str] = []
    if loc >= 500:
        reasons.append(f"Large module ({loc:,} LOC)")
    if complexity >= 25:
        reasons.append(f"High detected decision complexity ({complexity:g})")
    if coupling >= 20:
        reasons.append(f"Highly connected ({coupling} incoming + outgoing links)")
    if changes >= 10:
        reasons.append(f"Frequently changed ({changes} indexed commits)")
    if findings:
        reasons.append(f"{len(findings)} active architecture finding(s)")
    if not reasons:
        reasons.append("No threshold-level deterministic signal")

    candidates = sorted(
        {
            _PATTERN_REVIEWS[finding["finding_type"]]
            for finding in findings
            if finding.get("finding_type") in _PATTERN_REVIEWS
        }
    )
    return {
        "monitored_by_default": True,
        "monitoring_reason": "Executable source or test module included in attention triage.",
        "attention_score": min(100, score),
        "attention_label": label,
        "attention_reasons": reasons,
        "pattern_status": "candidate_review" if candidates else "not_evaluated",
        "pattern_candidates": candidates,
        "suitability_score": None,
        "note": (
            "Candidates are detector-grounded review prompts, not approved refactors. "
            "Pattern suitability scoring requires the semantic pattern-evaluation pipeline."
        ),
    }


def _finding_priority(
    finding: dict[str, Any], module_stats: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Rank review signals by risk and repository behavior, not threshold type alone."""

    severity = str(finding.get("severity") or "info")
    score = {"critical": 45, "error": 38, "warning": 24, "info": 8}.get(severity, 8)
    confidence = max(0.0, min(1.0, float(finding.get("confidence") or 0)))
    score += round(confidence * 12)
    paths = [str(path) for path in finding.get("affected_artifacts") or ()]
    affected = [module_stats[path] for path in paths if path in module_stats]
    changes = max((int(item.get("change_count") or 0) for item in affected), default=0)
    degree = max(
        (int(item.get("fan_in") or 0) + int(item.get("fan_out") or 0) for item in affected),
        default=0,
    )
    complexity = max((float(item.get("complexity") or 0) for item in affected), default=0)
    score += round(min(changes / 20, 1) * 14)
    score += round(min(degree / 30, 1) * 16)
    score += round(min(len(paths) / 5, 1) * 8)
    if changes and complexity:
        score += round(min(changes / 10, 1) * min(complexity / 50, 1) * 10)
    measured_coverage = [
        float(item["line_coverage"]) for item in affected if item.get("line_coverage") is not None
    ]
    if measured_coverage:
        score += round((1 - min(measured_coverage)) * 5)
    if finding.get("status") == "regressed":
        score += 8

    score = min(100, score)
    label = "Low"
    if score >= 80:
        label = "Urgent"
    elif score >= 60:
        label = "High"
    elif score >= 35:
        label = "Medium"

    reasons = [f"{severity.title()} severity · {confidence:.0%} confidence"]
    if changes:
        reasons.append(f"Hot path: up to {changes} indexed changes")
    if degree:
        reasons.append(f"Blast radius: up to {degree} incoming + outgoing links")
    if changes and complexity >= 10:
        reasons.append(f"Behavioral hotspot: churn × complexity {complexity:g}")
    if len(paths) > 1:
        reasons.append(f"Spans {len(paths)} modules")
    if measured_coverage:
        reasons.append(f"Lowest imported line coverage {min(measured_coverage):.0%}")
    if finding.get("status") == "regressed":
        reasons.append("Previously resolved condition has returned")
    return {
        "priority_score": score,
        "priority_label": label,
        "priority_reasons": reasons,
        "priority_version": "risk-churn-blast-v1",
    }


def _graph_quality(
    connection: sqlite3.Connection,
    snapshot_id: int,
    relationship_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    result = relationship_quality(relationship_rows)
    analyzer_rows = connection.execute(
        """
        SELECT analyzer, COUNT(*) AS files,
               SUM(CASE WHEN parse_error IS NOT NULL THEN 1 ELSE 0 END) AS parse_errors
        FROM file_versions WHERE snapshot_id = ? GROUP BY analyzer ORDER BY analyzer
        """,
        (snapshot_id,),
    ).fetchall()
    analyzers = {str(row["analyzer"]): int(row["files"] or 0) for row in analyzer_rows}
    result.update(
        {
            "analyzers": analyzers,
            "ast_files": analyzers.get("builtin-python-ast", 0),
            "lexical_files": analyzers.get("builtin-js-lexer", 0),
            "fallback_files": analyzers.get("builtin-text", 0),
            "parse_error_files": sum(int(row["parse_errors"] or 0) for row in analyzer_rows),
            "extraction_caveat": (
                "Python uses an AST parser; JavaScript and TypeScript use lexical extraction; "
                "other supported text formats use fallback analysis."
            ),
        }
    )
    return result


def _decode_relationship(value: dict[str, Any]) -> dict[str, Any]:
    metadata = relationship_metadata(value)
    value["resolution_status"] = resolution_status(value)
    value["candidate_paths"] = metadata.get("candidate_paths", [])
    value["metadata"] = metadata
    value.pop("metadata_json", None)
    return value


def _decode_json_columns(value: dict[str, Any]) -> dict[str, Any]:
    for key in list(value):
        if key.endswith("_json"):
            decoded_key = key.removesuffix("_json")
            try:
                value[decoded_key] = json.loads(value.pop(key) or "null")
            except json.JSONDecodeError:
                value[decoded_key] = None
    return value
