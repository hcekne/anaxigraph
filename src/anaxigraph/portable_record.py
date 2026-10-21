"""Application entry points for a repository-carried architecture record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filelock import FileLock

from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.persistence.portable_export import export_rows
from anaxigraph.persistence.portable_import import merge_record
from anaxigraph.portable_io import publish_record, read_record
from anaxigraph.portable_paths import managed_record, record_directory, record_hash
from anaxigraph.portable_rebind import rebind_pattern_cache
from anaxigraph.portable_views import record_views
from anaxigraph.semantic_fresh_eyes_grounding import write_review_grounding
from anaxigraph.workflow_settings import WorkflowSettings


def record_status(database: Any, repository_id: int) -> dict[str, Any]:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (f"portable-record:{repository_id}",)
        ).fetchone()
    return {
        "status": "loaded" if row else "not_present",
        "repository_id": repository_id,
        **(json.loads(row[0]) if row else {}),
    }


def save_record(database: Any, repository_id: int) -> dict[str, Any]:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository is not indexed")
    root = Path(repository["path"])
    with FileLock(f"{database.path}.record.lock"):
        with database.connect() as connection:
            connection.execute("BEGIN")
            tables, metadata = export_rows(connection, repository_id)
            views = record_views(connection, repository_id)
            metadata["contracts"] = {
                "prompt_version": _saved_prompt(connection, repository_id),
                "pattern_catalog": bundled_pattern_catalog().fingerprint,
            }
        identities = metadata.pop("_cache_identities")
        metadata["workflow_choices"] = WorkflowSettings(database.path).portable_choices(
            repository_id
        )
        result = publish_record(root, tables, metadata, views)
        receipt = {
            "digest": record_hash(result["manifest"]),
            "source": metadata["source"],
            "snapshot_id": repository["current_snapshot_id"],
        }
        with database.transaction() as connection:
            for key, value in (
                (f"portable-identities:{repository_id}", identities),
                (f"portable-record:{repository_id}", receipt),
            ):
                connection.execute(
                    "INSERT INTO schema_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, sort_keys=True)),
                )
    result.pop("manifest", None)
    return result


def load_record(database: Any, repository_id: int, root: Path, *, config: Any) -> dict[str, Any]:
    if not managed_record(root):
        return {"status": "not_present"}
    path = record_directory(root) / "manifest.json"
    if not path.exists():
        return {
            "status": "publication_incomplete",
            "message": "The shared record has not finished saving. Existing local analysis is retained.",
        }
    digest = record_hash(json.loads(path.read_bytes()))
    key = f"portable-record:{repository_id}"
    with database.connect() as connection:
        prior = connection.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
    if prior and json.loads(prior[0]).get("digest") == digest:
        return {"status": "unchanged", **json.loads(prior[0])}
    manifest, tables = read_record(root)
    if manifest.get("index_schema") != 11:
        raise ValueError("Unsupported portable index schema")
    WorkflowSettings(database.path).restore_choices(
        repository_id, manifest.get("workflow_choices", {})
    )
    with database.transaction() as connection:
        result = merge_record(connection, repository_id, str(root), manifest, tables)
        rebind_pattern_cache(connection, repository_id, manifest, config.semantic)
        reviews = connection.execute(
            "SELECT id,snapshot_id FROM semantic_documents WHERE repository_id = ? AND document_kind = 'fresh_review'",
            (repository_id,),
        ).fetchall()
        for review in reviews:
            write_review_grounding(
                connection,
                repository_id=repository_id,
                snapshot_id=review["snapshot_id"],
                review_id=review["id"],
            )
        connection.execute(
            "UPDATE repositories SET current_snapshot_id = ? WHERE id = ? AND current_snapshot_id IS NULL",
            (result["snapshot_id"], repository_id),
        )
        receipt = {"digest": digest, "source": manifest["source"], **result}
        connection.execute(
            "INSERT INTO schema_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(receipt, sort_keys=True)),
        )
    return {"status": "loaded", **receipt}


def _saved_prompt(connection: Any, repository_id: int) -> str | None:
    row = connection.execute(
        "SELECT prompt_version FROM semantic_documents WHERE repository_id = ? AND scope_type = 'repository' ORDER BY id DESC LIMIT 1",
        (repository_id,),
    ).fetchone()
    return row[0] if row else None
