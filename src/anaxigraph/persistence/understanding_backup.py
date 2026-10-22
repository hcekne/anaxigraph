"""A bounded recovery index for saved understanding, without historical structural caches."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from anaxigraph.persistence.index_backup import validate_index_backup
from anaxigraph.storage import AnaxiIndex

FACTS = """SELECT file_fact_id FROM semantic_documents WHERE file_fact_id IS NOT NULL
UNION SELECT file_fact_id FROM semantic_scope_states WHERE file_fact_id IS NOT NULL
UNION SELECT file_fact_id FROM semantic_claims
UNION SELECT file_fact_id FROM semantic_jobs WHERE file_fact_id IS NOT NULL AND status='completed'"""
ARTIFACTS = f"""SELECT artifact_id FROM file_facts WHERE id IN ({FACTS})
UNION SELECT artifact_id FROM semantic_documents WHERE artifact_id IS NOT NULL
UNION SELECT artifact_id FROM semantic_scope_states WHERE artifact_id IS NOT NULL
UNION SELECT artifact_id FROM semantic_taxonomy_memberships
UNION SELECT artifact_id FROM semantic_jobs WHERE artifact_id IS NOT NULL AND status='completed'"""
SELECTIONS = {
    "repositories": "1",
    "snapshots": "1",
    "artifacts": f"id IN ({ARTIFACTS})",
    "file_facts": f"id IN ({FACTS})",
    "architecture_rules": "1",
    "semantic_documents": "1",
    "semantic_claims": "1",
    "semantic_jobs": "status='completed'",
    "semantic_scope_states": "1",
    "semantic_taxonomies": "1",
    "semantic_taxonomy_nodes": "1",
    "semantic_taxonomy_memberships": "1",
    "semantic_taxonomy_reviews": "1",
}


def create_understanding_backup(
    database: Any, destination: Path, *, limit: int = 64_000_000
) -> None:
    if destination.exists():
        raise ValueError("Understanding recovery output already exists")
    temporary = destination.with_name("." + destination.name + ".tmp")
    if limit < 1_000_000:
        raise ValueError("Storage budgets leave no room for a bounded understanding backup")
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    try:
        with closing(database.connect()) as origin:
            origin.execute("BEGIN")
            _preflight(origin, limit)
            archive = AnaxiIndex(temporary)
            with closing(archive.connect()) as target:
                target.execute("PRAGMA journal_mode=DELETE")
                target.execute(
                    f"PRAGMA max_page_count={limit // target.execute('PRAGMA page_size').fetchone()[0]}"
                )
                target.execute("BEGIN")
                target.execute("PRAGMA defer_foreign_keys=ON")
                _copy_understanding(origin, target)
                if target.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("Understanding backup has an invalid source reference")
                target.commit()
            validate_index_backup(temporary)
            if temporary.stat().st_size > limit:
                raise ValueError("Understanding recovery copy exceeds its budget")
            temporary.chmod(0o600)
            temporary.replace(destination)
    except sqlite3.OperationalError as error:
        if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
            raise ValueError(
                "Saved analyses exceed the bounded recovery budget; original index was not changed"
            ) from error
        raise
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)


def _rows(connection: Any):
    for table, where in SELECTIONS.items():
        for row in connection.execute(f"SELECT * FROM {table} WHERE {where}"):
            value = dict(row)
            if table == "repositories":
                value["current_snapshot_id"] = None
            elif table == "snapshots":
                metadata = json.loads(value["metadata_json"] or "{}")
                metadata.update(
                    structural_available=False,
                    recovery_source_fingerprint=value["content_fingerprint"],
                )
                value.update(
                    base_snapshot_id=None,
                    snapshot_kind="portable_analysis",
                    content_fingerprint="recovery:" + value["content_fingerprint"],
                    metadata_json=json.dumps(metadata),
                )
            elif table == "file_facts":
                value.update(fact_key="recovery:" + value["fact_key"], metadata_json="{}")
            elif table == "semantic_jobs":
                value.update(worker_id=None, lease_token_hash=None, lease_expires_at=None)
            yield table, value


def _preflight(connection: Any, limit: int) -> None:
    total = 600_000
    for _table, row in _rows(connection):
        total += len(json.dumps(row, ensure_ascii=True).encode())
        if total > limit:
            raise ValueError(
                "Saved understanding exceeds the recovery budget; original index retained"
            )


def _copy_understanding(origin: Any, target: Any) -> None:
    for table, value in _rows(origin):
        columns = list(value)
        target.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [value[column] for column in columns],
        )
    target.execute(
        "INSERT OR REPLACE INTO schema_meta(key,value) VALUES ('understanding_recovery','current-storage-v2')"
    )
