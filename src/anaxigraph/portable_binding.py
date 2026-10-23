"""Bind portable understanding to independently scanned and fingerprint-checked source."""

from __future__ import annotations

import json
import re
from typing import Any

from anaxigraph.persistence.portable_current import SEMANTIC_TABLES, current_file_evidence
from anaxigraph.portable_paths import record_hash


def bind_current_record(
    connection: Any, repository_id: int, manifest: Any, tables: Any, config: Any
) -> tuple[dict[str, int], dict[str, Any]]:
    _validate_source(manifest)
    if set(tables) - set(SEMANTIC_TABLES):
        raise ValueError("Current records cannot contain structural or historical SQL tables")
    snapshot = connection.execute(
        "SELECT s.* FROM snapshots s JOIN repositories r ON r.current_snapshot_id=s.id WHERE r.id=?",
        (repository_id,),
    ).fetchone()
    if snapshot is None:
        raise ValueError("Scan local source before importing current understanding")
    files, bindings, compatible = _file_bindings(
        connection, repository_id, manifest, config, snapshot
    )
    # A record-only Git commit and a clone's absolute path do not invalidate understanding.
    prompt_matches = manifest.get("contracts", {}).get("prompt_version") in (
        None,
        config.semantic.prompt_version,
    )
    exact = len(compatible) == len(files) == len(manifest.get("files", [])) and prompt_matches
    if not prompt_matches:
        compatible.clear()
    source_id = snapshot["id"] if exact else _analysis_baseline(connection, repository_id, manifest)
    bindings[manifest["source"]["snapshot"]] = source_id
    for saved in manifest.get("saved_sources", []):
        bindings[saved["snapshot"]] = _analysis_baseline(
            connection, repository_id, {"source": saved}
        )
    current_key = "snapshots:" + record_hash(
        {"content_fingerprint": snapshot["content_fingerprint"]}
    )
    bindings[current_key] = snapshot["id"]
    return bindings, _selected_scopes(tables, bindings, current_key, compatible, exact)


def _file_bindings(
    connection: Any, repository_id: int, manifest: Any, config: Any, snapshot: Any
) -> tuple[Any, Any, Any]:
    files = {row["path"]: row for row in current_file_evidence(connection, snapshot["id"], config)}
    bindings = {manifest["repository"]["key"]: repository_id}
    compatible = set()
    for item in manifest.get("files", []):
        file = files.get(item["path"])
        if file is None or config.is_ignored(item["path"]):
            continue
        bindings[item["artifact"]] = file["artifact_id"]
        # Parser/app versions rebuild deterministic facts locally. Exact source
        # identity remains compatible paid evidence; semantic planners separately
        # validate their supported schema, prompt and analysis input contracts.
        if file["raw_hash"] == item["raw_hash"]:
            bindings[item["fact"]] = file["file_fact_id"]
            compatible.add(item["path"])
    return files, bindings, compatible


def _selected_scopes(
    tables: Any, bindings: Any, current_key: str, compatible: set[str], exact: bool
) -> dict[str, Any]:
    selected = {}
    for table, rows in tables.items():
        selected[table] = [row for row in rows if _compatible_row(row["value"], compatible)]
        if table == "semantic_scope_states" and not exact:
            for row in selected[table]:
                if row["value"].get("scope_type") == "module":
                    row["value"]["snapshot_id"] = {"$ref": current_key}
    keys = set(bindings) | {row["key"] for rows in selected.values() for row in rows}
    selected = {
        table: [_available_references(row, keys) for row in rows]
        for table, rows in selected.items()
    }
    return selected


def _validate_source(manifest: Any) -> None:
    def key(table: str, value: Any) -> None:
        if not isinstance(value, str) or not re.fullmatch(table + r":[a-f0-9]{64}", value):
            raise ValueError("Invalid portable source reference")

    key("repositories", manifest["repository"]["key"])
    key("snapshots", manifest["source"]["snapshot"])
    paths = set()
    for file in manifest.get("files", []):
        path = file["path"]
        if (
            not isinstance(path, str)
            or path.startswith("/")
            or ".." in path.split("/")
            or path in paths
        ):
            raise ValueError("Invalid or duplicate portable source path")
        paths.add(path)
        key("artifacts", file["artifact"])
        key("file_facts", file["fact"])
    if len(manifest.get("saved_sources", [])) > 8:
        raise ValueError("Too many saved analysis sources")
    for source in manifest.get("saved_sources", []):
        key("snapshots", source["snapshot"])


def _compatible_row(value: Any, paths: set[str]) -> bool:
    return value.get("scope_type") != "module" or value.get("scope_key") in paths


def _available_references(value: Any, keys: set[str]) -> Any:
    if isinstance(value, list):
        return [_available_references(item, keys) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return value if value["$ref"] in keys else None
        return {key: _available_references(item, keys) for key, item in value.items()}
    return value


def _analysis_baseline(connection: Any, repository_id: int, manifest: Any) -> int:
    source = manifest["source"]
    existing = connection.execute(
        "SELECT id FROM snapshots WHERE repository_id=? AND content_fingerprint IN (?,?)",
        (
            repository_id,
            source["fingerprint"],
            "analysis:" + source["fingerprint"].removeprefix("analysis:"),
        ),
    ).fetchone()
    if existing:
        return existing[0]
    connection.execute(
        "INSERT INTO snapshots(repository_id,commit_sha,branch,analysis_timestamp,content_fingerprint,snapshot_kind,metadata_json) VALUES (?,?,?,?,?,'portable_analysis',?) ON CONFLICT(repository_id,content_fingerprint) DO NOTHING",
        (
            repository_id,
            source["commit"],
            source["branch"],
            "1970-01-01T00:00:00+00:00",
            source["fingerprint"],
            json.dumps(
                {
                    "structural_available": False,
                    "analysis_signature": source.get("analysis_signature"),
                }
            ),
        ),
    )
    return connection.execute(
        "SELECT id FROM snapshots WHERE repository_id=? AND content_fingerprint=?",
        (repository_id, source["fingerprint"]),
    ).fetchone()[0]
