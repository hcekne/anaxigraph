"""Bound local comparison history while keeping current and explicitly saved understanding."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from anaxigraph.config import load_config
from anaxigraph.persistence.index_backup import validate_index_backup
from anaxigraph.persistence.temporal_reconstruction import (
    _insert_checkpoint,
    reconstruct_files,
    reconstruct_relationships,
)
from anaxigraph.persistence.understanding_backup import create_understanding_backup
from anaxigraph.portable_text import concise_module

POLICY_KEY = "current-storage-v2"


def retain_current_index(
    database: Any, repository_id: int, policy: Any, *, migrate: bool = False
) -> dict[str, Any]:
    state = _retention_inputs(database, repository_id)
    if state is None:
        return {"status": "not_mapped"}
    repository, current, snapshots, count, opted_in = state
    detailed = policy.detailed_history or (opted_in and not migrate)
    structural_count = sum(row["snapshot_kind"] != "portable_analysis" for row in snapshots)
    needed = structural_count > policy.comparison_checkpoints + 1 and not detailed
    if not (migrate or needed or count > 16):
        return {"status": "bounded", "mapped_locally": True}
    backup = _migration_backup(database, policy)
    removed = _prune_cache(
        database,
        repository_id,
        policy,
        migrate,
        detailed,
        repository,
        current,
        snapshots,
        backup,
        needed,
    )
    if removed or migrate:
        # Reclaim actual disk space; deleting SQL rows alone leaves a gigabyte-sized file.
        with closing(database.connect()) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")
    size = database.path.stat().st_size
    return {
        "status": "compacted",
        "mapped_locally": True,
        "removed_snapshots": removed,
        "index_bytes": size,
        "budget_bytes": policy.index_bytes,
        "within_budget": size <= policy.index_bytes,
        "recovery_backup": backup,
    }


def _retention_inputs(database: Any, repository_id: int) -> Any:
    with database.connect() as connection:
        repository = connection.execute(
            "SELECT * FROM repositories WHERE id=?", (repository_id,)
        ).fetchone()
        if repository is None or repository["current_snapshot_id"] is None:
            return None
        current = repository["current_snapshot_id"]
        snapshots = connection.execute(
            "SELECT id,snapshot_kind FROM snapshots WHERE repository_id=? ORDER BY id DESC",
            (repository_id,),
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM analysis_runs WHERE repository_id=?", (repository_id,)
        ).fetchone()[0]
        opted_in = (
            connection.execute(
                "SELECT 1 FROM schema_meta WHERE key=?", (f"history-opt-in:{repository_id}",)
            ).fetchone()
            is not None
        )
    return repository, current, snapshots, count, opted_in


def _prune_cache(
    database: Any,
    repository_id: int,
    policy: Any,
    migrate: bool,
    detailed: bool,
    repository: Any,
    current: int,
    snapshots: Any,
    backup: str,
    prune: bool,
) -> int:
    with database.transaction(maintenance=True) as connection:
        if migrate and not load_config(Path(repository["path"])).semantic.detailed_reviews:
            _compact_descriptions(connection, repository_id)
        removed = 0
        if not detailed and (prune or migrate):
            connection.execute(
                "DELETE FROM schema_meta WHERE key=?", (f"history-opt-in:{repository_id}",)
            )
            graph_frames = [row for row in snapshots if row["snapshot_kind"] != "portable_analysis"]
            keep = {
                current,
                *(row["id"] for row in graph_frames[: policy.comparison_checkpoints + 1]),
            }
            structural = set(keep)
            active = connection.execute(
                "SELECT DISTINCT snapshot_id FROM semantic_jobs WHERE repository_id=? AND status='running'",
                (repository_id,),
            ).fetchall()
            structural.update(row["snapshot_id"] for row in active)
            keep.update(_saved_snapshots(connection, repository_id))
            removed = _prune_snapshots(
                connection, repository_id, keep, load_config(Path(repository["path"])), structural
            )
        connection.execute(
            "DELETE FROM analysis_runs WHERE repository_id=? AND status!='running' AND id NOT IN (SELECT id FROM analysis_runs WHERE repository_id=? ORDER BY id DESC LIMIT 16)",
            (repository_id, repository_id),
        )
        if prune or migrate:
            _collect_unused(connection, repository_id)
        connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES (?,?)",
            (
                f"{POLICY_KEY}:{repository_id}",
                json.dumps({"backup": backup, "retained": policy.comparison_checkpoints}),
            ),
        )
    return removed


def _migration_backup(database: Any, policy: Any) -> str:
    path = database.path.with_name(database.path.name + ".before-current-storage.backup")
    limit = min(64_000_000, 200_000_000 - policy.record_bytes - policy.index_bytes - 12_000_000)
    if path.exists() and path.stat().st_size > limit:
        raise ValueError(
            "Existing recovery backup exceeds the available storage budget; move that legacy backup to external recovery storage before compacting"
        )
    with database.connect() as connection:
        verified = connection.execute(
            "SELECT 1 FROM schema_meta WHERE key LIKE ? LIMIT 1", (POLICY_KEY + ":%",)
        ).fetchone()
    if verified and path.exists():
        return str(path)
    if not path.exists():
        create_understanding_backup(database, path, limit=limit)
    else:
        validate_index_backup(path)
    return str(path)


def _compact_descriptions(connection: Any, repository_id: int) -> None:
    for table, where in (
        ("semantic_documents", "repository_id=? AND scope_type='module'"),
        (
            "semantic_claims",
            "file_fact_id IN (SELECT id FROM file_facts WHERE artifact_id IN (SELECT id FROM artifacts WHERE repository_id=?))",
        ),
    ):
        rows = connection.execute(
            f"SELECT id,value_json FROM {table} WHERE {where}", (repository_id,)
        ).fetchall()
        for row in rows:
            value = concise_module(json.loads(row["value_json"]))
            connection.execute(
                f"UPDATE {table} SET value_json=?,supporting_evidence_json=? WHERE id=?",
                (
                    json.dumps(value, sort_keys=True, separators=(",", ":")),
                    json.dumps(value["evidence"]),
                    row["id"],
                ),
            )


def _saved_snapshots(connection: Any, repository_id: int) -> set[int]:
    # Keep selected latest interpretations; Git and the migration backup preserve earlier results.
    latest = connection.execute(
        "SELECT snapshot_id FROM semantic_documents WHERE id IN (SELECT MAX(id) FROM semantic_documents WHERE repository_id=? AND document_kind IN ('architecture_plan','fresh_review','pattern_review') GROUP BY document_kind)",
        (repository_id,),
    ).fetchall()
    reusable = connection.execute(
        "SELECT DISTINCT snapshot_id FROM semantic_documents WHERE id IN (SELECT MAX(id) FROM semantic_documents WHERE repository_id=? AND (scope_type IN ('module','repository','group') OR (scope_type='taxonomy' AND scope_key=CAST(repository_id AS TEXT))) GROUP BY scope_type,scope_key,document_kind)",
        (repository_id,),
    ).fetchall()
    active = connection.execute(
        "SELECT DISTINCT snapshot_id FROM semantic_jobs WHERE repository_id=? AND status='running'",
        (repository_id,),
    ).fetchall()
    return {row["snapshot_id"] for row in (*latest, *active, *reusable)}


def _prune_snapshots(
    connection: Any, repository_id: int, keep: set[int], config: Any, structural: set[int]
) -> int:
    # Materialize retained frames BEFORE severing the delta chains they depend on.
    frames = _retained_frames(connection, keep, structural, config)
    for snapshot, files, relationships, parent in frames:
        identifier = snapshot["id"]
        connection.execute("DELETE FROM snapshot_checkpoints WHERE snapshot_id=?", (identifier,))
        connection.execute("DELETE FROM snapshot_file_changes WHERE snapshot_id=?", (identifier,))
        connection.execute(
            "DELETE FROM snapshot_relationship_changes WHERE snapshot_id=?", (identifier,)
        )
        _insert_checkpoint(
            connection, identifier, repository_id, snapshot["sequence"], 0, files, relationships
        )
        connection.execute(
            "UPDATE snapshots SET base_snapshot_id=? WHERE id=?", (parent, identifier)
        )
        # State can reuse an older document: retain its result and provenance, not its old frame.
        connection.execute(
            "UPDATE semantic_documents SET snapshot_id=? WHERE id IN (SELECT intrinsic_document_id FROM semantic_scope_states WHERE snapshot_id=? UNION SELECT context_document_id FROM semantic_scope_states WHERE snapshot_id=?)",
            (identifier, identifier, identifier),
        )
    parameters = (repository_id, *sorted(keep))
    clause = f"repository_id=? AND id NOT IN ({','.join('?' for _ in keep)})"
    oldest = min(keep)
    connection.execute(
        f"UPDATE findings SET first_snapshot_id=? WHERE repository_id=? AND first_snapshot_id IN (SELECT id FROM snapshots WHERE {clause})",
        (oldest, repository_id, *parameters),
    )
    connection.execute(
        f"UPDATE findings SET last_snapshot_id=? WHERE repository_id=? AND last_snapshot_id IN (SELECT id FROM snapshots WHERE {clause})",
        (oldest, repository_id, *parameters),
    )
    removed = connection.execute(f"DELETE FROM snapshots WHERE {clause}", parameters).rowcount
    return removed


def _retained_frames(
    connection: Any, keep: set[int], structural: set[int], config: Any
) -> list[Any]:
    frames = []
    for identifier in sorted(keep):
        snapshot = connection.execute(
            "SELECT * FROM snapshots WHERE id=?", (identifier,)
        ).fetchone()
        retain_graph = identifier in structural
        files = (
            {
                key: row
                for key, row in reconstruct_files(connection, identifier).items()
                if not config.is_ignored(row["path"])
            }
            if retain_graph
            else {}
        )
        relationships = (
            {
                key: value
                for key, value in reconstruct_relationships(connection, identifier).items()
                if key in files
            }
            if retain_graph
            else {}
        )
        if not retain_graph:
            _analysis_only_snapshot(connection, snapshot)
        parent = _retained_parent(connection, snapshot, structural) if retain_graph else None
        frames.append((snapshot, files, relationships, parent))
    return frames


def _retained_parent(connection: Any, snapshot: Any, structural: set[int]) -> int | None:
    parent = snapshot["base_snapshot_id"]
    seen = {snapshot["id"]}
    while parent is not None and parent not in structural:
        if parent in seen:
            raise ValueError("Snapshot lineage cycle prevents safe compaction")
        seen.add(parent)
        row = connection.execute(
            "SELECT base_snapshot_id FROM snapshots WHERE id=?", (parent,)
        ).fetchone()
        parent = row[0] if row else None
    return parent


def _analysis_only_snapshot(connection: Any, snapshot: Any) -> None:
    metadata = json.loads(snapshot["metadata_json"] or "{}")
    original = metadata.get(
        "analysis_source_fingerprint",
        metadata.get(
            "recovery_source_fingerprint", snapshot["content_fingerprint"].removeprefix("analysis:")
        ),
    )
    metadata.update(structural_available=False, analysis_source_fingerprint=original)
    connection.execute(
        "UPDATE snapshots SET snapshot_kind='portable_analysis',content_fingerprint=?,metadata_json=? WHERE id=?",
        ("analysis:" + original, json.dumps(metadata), snapshot["id"]),
    )


def _collect_unused(connection: Any, repository_id: int) -> None:
    connection.execute(
        "DELETE FROM relationship_sets WHERE repository_id=? AND id NOT IN (SELECT relationship_set_id FROM snapshot_relationship_changes WHERE relationship_set_id IS NOT NULL UNION SELECT relationship_set_id FROM checkpoint_relationships)",
        (repository_id,),
    )
    connection.execute(
        "UPDATE file_facts SET metadata_json='{}',fact_key='archived:'||fact_key WHERE artifact_id IN (SELECT id FROM artifacts WHERE repository_id=?) AND fact_key NOT LIKE 'archived:%' AND id NOT IN (SELECT file_fact_id FROM checkpoint_files UNION SELECT file_fact_id FROM snapshot_file_changes WHERE file_fact_id IS NOT NULL UNION SELECT source_file_fact_id FROM relationship_sets)",
        (repository_id,),
    )
    connection.execute(
        "DELETE FROM file_facts WHERE artifact_id IN (SELECT id FROM artifacts WHERE repository_id=?) AND id NOT IN (SELECT file_fact_id FROM snapshot_file_changes WHERE file_fact_id IS NOT NULL UNION SELECT file_fact_id FROM checkpoint_files UNION SELECT source_file_fact_id FROM relationship_sets UNION SELECT file_fact_id FROM semantic_documents WHERE file_fact_id IS NOT NULL UNION SELECT file_fact_id FROM semantic_jobs WHERE file_fact_id IS NOT NULL UNION SELECT file_fact_id FROM semantic_scope_states WHERE file_fact_id IS NOT NULL)",
        (repository_id,),
    )
