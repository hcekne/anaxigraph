"""Transaction-bound writes for a prepared repository snapshot."""

from __future__ import annotations

import json
import sqlite3
from pathlib import PurePosixPath
from typing import Any

from anaxigraph import __version__
from anaxigraph.clock import utc_now
from anaxigraph.ir import analysis_metadata, artifact_type
from anaxigraph.persistence.temporal_facts import record_canonical_file_facts
from anaxigraph.scan_preparation import PreparedFile


def insert_snapshot(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    git_metadata: Any,
    fingerprint: str,
    revision: str | None,
    config: Any,
    analysis_version: int,
    signature: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO snapshots(
            repository_id, commit_sha, parent_commit_sha, branch, commit_timestamp,
            analysis_timestamp, content_fingerprint, snapshot_kind, dirty, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repository_id,
            git_metadata.commit_sha,
            git_metadata.parent_commit_sha,
            git_metadata.branch,
            git_metadata.commit_timestamp,
            utc_now(),
            fingerprint,
            "commit" if revision else "working_tree",
            int(git_metadata.dirty),
            json.dumps(
                {
                    "anaxigraph_version": __version__,
                    "analysis_version": analysis_version,
                    "analysis_signature": signature,
                    "config_path": str(config.config_path) if config.config_path else None,
                    "working_tree_fingerprint": git_metadata.working_tree_fingerprint,
                },
                sort_keys=True,
            ),
        ),
    )
    return int(cursor.lastrowid)


def upsert_artifacts(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    prepared: list[PreparedFile],
    commit_sha: str,
) -> tuple[dict[str, int], int]:
    rows = connection.execute(
        "SELECT id, canonical_path FROM artifacts WHERE repository_id = ?",
        (repository_id,),
    ).fetchall()
    existing = {row["canonical_path"]: int(row["id"]) for row in rows}
    active_paths = {
        row["canonical_path"]
        for row in connection.execute(
            "SELECT canonical_path FROM artifacts WHERE repository_id = ? AND deleted_commit IS NULL",
            (repository_id,),
        )
    }
    current_paths = {item.discovered.path for item in prepared}
    now = utc_now()
    for item in prepared:
        path = item.discovered.path
        kind = artifact_type(path, item.discovered.language)
        if path not in existing:
            cursor = connection.execute(
                """
                INSERT INTO artifacts(
                    repository_id, canonical_path, artifact_type, first_seen_commit, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (repository_id, path, kind, commit_sha, now),
            )
            existing[path] = int(cursor.lastrowid)
        else:
            connection.execute(
                "UPDATE artifacts SET deleted_commit = NULL, artifact_type = ? WHERE id = ?",
                (kind, existing[path]),
            )
    deleted_paths = active_paths - current_paths
    connection.executemany(
        "UPDATE artifacts SET deleted_commit = ? WHERE id = ?",
        [(commit_sha, existing[path]) for path in deleted_paths],
    )
    return {path: existing[path] for path in current_paths}, len(deleted_paths)


def insert_file_facts(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    base_snapshot_id: int | None,
    prepared: list[PreparedFile],
    artifacts: dict[str, int],
    config: Any,
    analysis_version: int,
    signature: str,
) -> None:
    versions = [
        (_version_record(item, artifacts, config, analysis_version), item.analysis.symbols)
        for item in prepared
    ]
    record_canonical_file_facts(
        connection,
        snapshot_id=snapshot_id,
        base_snapshot_id=base_snapshot_id,
        versions=versions,
        signature=signature,
    )


def upsert_groups(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    config: Any,
) -> None:
    for group in config.groups:
        connection.execute(
            """
            INSERT INTO groups(repository_id, name, level, parent_name, source, description)
            VALUES (?, ?, ?, ?, 'declared', ?)
            ON CONFLICT(repository_id, name, source) DO UPDATE SET
                level = excluded.level, parent_name = excluded.parent_name,
                description = excluded.description
            """,
            (repository_id, group.name, group.level, group.parent, group.description),
        )


def ingest_git_history(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    changes: list[Any],
) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO git_changes(
            repository_id, commit_sha, committed_at, author_name, subject, path,
            change_type, additions, deletions
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                repository_id,
                item.commit_sha,
                item.committed_at,
                item.author_name,
                item.subject,
                item.path,
                item.change_type,
                item.additions,
                item.deletions,
            )
            for item in changes
        ],
    )


def _version_record(
    item: PreparedFile,
    artifacts: dict[str, int],
    config: Any,
    analysis_version: int,
) -> dict[str, Any]:
    path = item.discovered.path
    analysis = item.analysis
    return {
        "artifact_id": artifacts[path],
        "path": path,
        "language": item.discovered.language,
        "runtime": _runtime(path, item.discovered.language),
        "declared_group": config.declared_group(path),
        "inferred_group": _inferred_group(path, item.discovered.language),
        "raw_hash": item.discovered.raw_hash,
        "structural_hash": analysis.structural_hash,
        "lines_of_code": analysis.lines_of_code,
        "comment_lines": analysis.comment_lines,
        "complexity": analysis.complexity,
        "summary": analysis.summary,
        "responsibilities_json": json.dumps(analysis.responsibilities),
        "inputs_json": json.dumps(analysis.inputs),
        "outputs_json": json.dumps(analysis.outputs),
        "side_effects_json": json.dumps(analysis.side_effects),
        "public_interfaces_json": json.dumps(analysis.public_interfaces),
        "analyzer": analysis.analyzer,
        "analysis_status": item.analysis_status,
        "parse_error": analysis.parse_error,
        "metadata_json": json.dumps(
            _version_metadata(item, config, analysis_version), sort_keys=True
        ),
        "first_seen_at": item.first_seen_at,
        "last_changed_at": item.last_changed_at,
    }


def _version_metadata(
    item: PreparedFile,
    config: Any,
    analysis_version: int,
) -> dict[str, Any]:
    metadata = analysis_metadata(
        item.analysis,
        analysis_version=analysis_version,
        configured_aliases=config.aliases,
    )
    metadata.update(
        {
            "invalidation_reason": item.discovered.invalidation_reason,
            "history_change_kind": item.discovered.change_kind,
            "source_read": item.discovered.source_read,
        }
    )
    return metadata


def _inferred_group(path: str, language: str) -> str:
    lowered = [part.lower() for part in PurePosixPath(path).parts]
    if artifact_type(path, language) == "test":
        return "testing"
    for name in (
        "frontend",
        "backend",
        "agent-runner",
        "runner-launcher",
        "native-worker",
        "git-worker",
        "infra",
        "docs",
        "scripts",
    ):
        if name in lowered:
            return name
    if lowered and lowered[0] == "src" and len(lowered) > 1:
        return lowered[1]
    return lowered[0] if lowered else "root"


def _runtime(path: str, language: str) -> str:
    lowered = path.lower()
    if lowered.startswith("frontend/") or language in {"javascriptreact", "typescriptreact"}:
        return "browser"
    if "worker" in lowered:
        return "worker"
    if language == "python":
        return "python"
    if language in {"javascript", "typescript"}:
        return "node"
    if language in {"dockerfile", "terraform", "hcl", "yaml"}:
        return "deployment"
    return "static"
