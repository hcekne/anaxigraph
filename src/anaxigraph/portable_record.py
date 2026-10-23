"""Application entry points for a repository-carried architecture record."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filelock import FileLock

from anaxigraph.config import load_config
from anaxigraph.knowledge_sync import clear_knowledge_cache
from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.persistence.portable_export import export_rows
from anaxigraph.persistence.portable_import import (
    merge_record,
    prepare_record_import,
    write_identity_cache,
)
from anaxigraph.portable_binding import bind_current_record
from anaxigraph.portable_io import publish_record, read_record
from anaxigraph.portable_paths import (
    CURRENT_RECORD_FORMATS,
    managed_record,
    record_directory,
    record_hash,
)
from anaxigraph.portable_rebind import rebind_pattern_cache
from anaxigraph.portable_views import record_views
from anaxigraph.storage_status import storage_status
from anaxigraph.workflow_settings import WorkflowSettings


def record_status(database: Any, repository_id: int) -> dict[str, Any]:
    repository = database.repository(repository_id)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (f"portable-record:{repository_id}",)
        ).fetchone()
    return {
        "status": "loaded" if row else "not_present",
        "repository_id": repository_id,
        "mapped_locally": database.latest_snapshot(repository_id) is not None,
        "record_exported": bool(row)
        and repository is not None
        and (record_directory(Path(repository["path"])) / "manifest.json").is_file(),
        "committed": None,
        "pushed": None,
        "storage": storage_status(
            database,
            Path(repository["path"]),
            _active_policy(database, repository_id, Path(repository["path"])).storage,
        )
        if repository
        else None,
        **(json.loads(row[0]) if row else {}),
    }


def save_record(
    database: Any, repository_id: int, *, maintenance: bool = False, config: Any = None
) -> dict[str, Any]:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository is not indexed")
    root = Path(repository["path"])
    config = config or _active_policy(database, repository_id, root)
    policy = config.storage
    with FileLock(f"{database.path}.record.lock"):
        with database.connect() as connection:
            connection.execute("BEGIN")
            tables, metadata = export_rows(connection, repository_id, config=config)
            views = record_views(connection, repository_id, config=config)
            metadata["contracts"] = {
                "prompt_version": config.semantic.prompt_version,
                "pattern_catalog": bundled_pattern_catalog().fingerprint,
            }
        identities = metadata.pop("_cache_identities")
        metadata["workflow_choices"] = WorkflowSettings(database.path).portable_choices(
            repository_id
        )
        result = _publish_prepared(
            database, repository_id, root, tables, metadata, views, identities, policy
        )
    result.pop("manifest", None)
    result["storage"] = storage_status(database, root, policy)
    return result


def _publish_prepared(database, repository_id, root, tables, metadata, views, identities, policy):
    # Admit the proposed replacement and its receipt before touching the last valid record.
    # The writer lock prevents concurrent index growth during publication.
    with database.transaction(maintenance=True) as connection:

        def before_write(total, manifest):
            receipt = {
                "digest": record_hash(manifest),
                "source": metadata["source"],
                "snapshot_id": identities.get(metadata["source"]["snapshot"]),
            }
            write_identity_cache(connection, repository_id, identities)
            connection.execute(
                "INSERT INTO schema_meta(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"portable-record:{repository_id}", json.dumps(receipt, sort_keys=True)),
            )

        return publish_record(
            root,
            tables,
            metadata,
            views,
            policy=policy,
            before_write=before_write,
            pool=(connection, database.path),
        )


def _active_policy(database: Any, repository_id: int, root: Path) -> Any:
    snapshot = database.latest_snapshot(repository_id)
    metadata = json.loads(snapshot["metadata_json"] or "{}") if snapshot else {}
    path = Path(metadata["config_path"]) if metadata.get("config_path") else None
    return load_config(root, path if path and path.is_file() else None)


def load_record(
    database: Any, repository_id: int, root: Path, *, config: Any, after_scan: bool = False
) -> dict[str, Any]:
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
        pending = connection.execute(
            "SELECT 1 FROM schema_meta WHERE key='index-compaction-pending'"
        ).fetchone()
    if prior and json.loads(prior[0]).get("digest") == digest:
        if pending:
            database.finish_cache_maintenance()
        return {"status": "unchanged", **json.loads(prior[0])}
    manifest, tables = read_record(root)
    if manifest.get("format") in CURRENT_RECORD_FORMATS and not after_scan:
        return {"status": "awaiting_local_scan"}
    if manifest.get("index_schema") != 11:
        raise ValueError("Unsupported portable index schema")
    WorkflowSettings(database.path).restore_choices(
        repository_id, manifest.get("workflow_choices", {})
    )
    receipt = _restore_understanding(
        database, repository_id, root, manifest, tables, config, digest, key
    )
    return {"status": "loaded", **receipt}


def _restore_understanding(
    database: Any,
    repository_id: int,
    root: Path,
    manifest: Any,
    tables: Any,
    config: Any,
    digest: str,
    key: str,
) -> dict[str, Any]:
    with database.transaction() as connection:
        bindings = None
        if manifest.get("format") in CURRENT_RECORD_FORMATS:
            manifest = {
                **manifest,
                "files": [item["value"] for item in tables.pop("source_files", [])],
            }
            bindings, tables = bind_current_record(
                connection, repository_id, manifest, tables, config
            )
        # Imported paid results take priority over a disposable structural projection.
        # Reuse those pages before merging, and rebuild once all annotations are bound.
        clear_knowledge_cache(connection)
        prepare_record_import(connection)
        result = merge_record(
            connection, repository_id, str(root), manifest, tables, bindings=bindings
        )
        rebind_pattern_cache(connection, repository_id, manifest, config.semantic)
        connection.execute(
            "UPDATE repositories SET current_snapshot_id = ? WHERE id = ? AND current_snapshot_id IS NULL",
            (result["snapshot_id"], repository_id),
        )
        receipt = _import_receipt(connection, repository_id, manifest, result, digest, key)
    database.finish_cache_maintenance()
    return receipt


def _import_receipt(connection, repository_id, manifest, result, digest, key):
    snapshot = connection.execute(
        "SELECT current_snapshot_id FROM repositories WHERE id=?", (repository_id,)
    ).fetchone()[0]
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta VALUES ('graph-import-pending',?)", (str(snapshot),)
    )
    receipt = {"digest": digest, "source": manifest["source"], **result}
    connection.execute(
        "INSERT INTO schema_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(receipt, sort_keys=True)),
    )
    return receipt
