"""Merge validated portable facts into a checkout's cache without replacing local work."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.persistence.portable_references import IDENTITY_FIELDS
from anaxigraph.persistence.portable_rows import TABLES, primary_columns, table_references
from anaxigraph.portable_paths import canonical_json

ID_ORDER = (
    "snapshots",
    "artifacts",
    "groups",
    "file_facts",
    "fact_symbols",
    "relationship_sets",
    "relationship_edges",
    "findings",
    "architecture_rules",
    "semantic_documents",
    "semantic_taxonomies",
    "git_changes",
    "semantic_jobs",
    "analysis_runs",
    "metrics",
    "coverage_measurements",
    "semantic_claims",
)
UNIQUE_FIELDS = {
    "snapshots": ("repository_id", "content_fingerprint"),
    "artifacts": ("repository_id", "canonical_path"),
    "groups": ("repository_id", "name", "source"),
    "file_facts": ("fact_key",),
    "relationship_sets": ("set_key",),
    "findings": ("repository_id", "stable_key"),
    "architecture_rules": ("repository_id", "rule_id"),
    "semantic_taxonomies": ("snapshot_id", "input_hash"),
    "git_changes": ("repository_id", "commit_sha", "path"),
    "fact_symbols": ("file_fact_id", "symbol_type", "qualified_name", "start_line", "end_line"),
}


def merge_record(
    connection: Any, repository_id: int, root: str, manifest: Any, tables: Any
) -> dict[str, Any]:
    _validate_tables(connection, tables)
    cache_key = f"portable-identities:{repository_id}"
    prior = connection.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (cache_key,)
    ).fetchone()
    identities = json.loads(prior[0]) if prior else {}
    repository = tables.get("repositories", [])
    if len(repository) != 1:
        raise ValueError("A portable record must contain exactly one repository")
    identities[repository[0]["key"]] = repository_id
    connection.execute("PRAGMA defer_foreign_keys = ON")
    _allocate(connection, tables, identities, repository_id)
    imported = 0
    for table in (*ID_ORDER, *(item for item in tables if item not in (*ID_ORDER, "repositories"))):
        for item in sorted(tables.get(table, []), key=_record_order):
            value = _decode(item["value"], identities, root)
            if table in ID_ORDER:
                value["id"] = identities[item["key"]]
            value = _prepare_row(table, value, repository_id)
            imported += _save_row(connection, table, value)
    connection.execute(
        "INSERT INTO schema_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (cache_key, canonical_json(identities).decode()),
    )
    return {
        "imported_rows": imported,
        "snapshot_id": identities.get(manifest["source"]["snapshot"]),
    }


def _validate_tables(connection: Any, tables: Any) -> None:
    keys = {item["key"] for items in tables.values() for item in items}
    for table, items in tables.items():
        if table not in TABLES:
            raise ValueError(f"Unknown portable table: {table}")
        columns = {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        references = table_references(connection, table)
        for item in items:
            if not isinstance(item["value"], dict) or set(item["value"]) - columns:
                raise ValueError(f"Unsupported columns in {table}")
            if not item["key"].startswith(f"{table}:"):
                raise ValueError("Portable identity has the wrong table")
            _validate_references(item["value"], keys)
            _validate_foreign_keys(item["value"], references)
            if table == "semantic_jobs" and item["value"].get("status") != "completed":
                raise ValueError("Portable records cannot import active workers or pending jobs")


def _validate_foreign_keys(value: Any, references: Any) -> None:
    for field, parent in references.items():
        link = value.get(field)
        if link is not None and (
            not isinstance(link, dict) or not str(link.get("$ref", "")).startswith(parent + ":")
        ):
            raise ValueError("Portable foreign keys must reference the correct table")


def _validate_references(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"} or value["$ref"] not in keys:
                raise ValueError("Portable record has a missing or invalid reference")
        else:
            for item in value.values():
                _validate_references(item, keys)
    elif isinstance(value, list):
        for item in value:
            _validate_references(item, keys)


def _allocate(connection: Any, tables: Any, identities: Any, repository_id: int) -> None:
    for table in ID_ORDER:
        next_id = connection.execute(f'SELECT COALESCE(MAX(id),0)+1 FROM "{table}"').fetchone()[0]
        for item in sorted(tables.get(table, []), key=_record_order):
            key = item["key"]
            value = _decode(item["value"], identities, "${CHECKOUT}", missing=None)
            value = _prepare_row(table, value, repository_id)
            if key in identities and _cached_identity_matches(
                connection, table, identities[key], value
            ):
                continue
            existing = _existing_id(connection, table, value)
            identities[key] = existing or next_id
            next_id += existing is None


def _cached_identity_matches(connection: Any, table: str, identifier: int, value: Any) -> bool:
    row = connection.execute(f'SELECT * FROM "{table}" WHERE id = ?', (identifier,)).fetchone()
    if row is None:
        return False
    fields = {
        "file_facts": ("artifact_id", "raw_hash", "analysis_signature"),
        "relationship_sets": (
            "source_artifact_id",
            "source_file_fact_id",
            "content_hash",
            "resolver_context_hash",
        ),
    }.get(table, IDENTITY_FIELDS.get(table, ()))
    return bool(fields) and all(row[field] == value.get(field) for field in fields)


def _existing_id(connection: Any, table: str, value: Any) -> int | None:
    fields = UNIQUE_FIELDS.get(table)
    if fields is None or any(value.get(field) is None for field in fields):
        return None
    where = " AND ".join(f'"{field}" = ?' for field in fields)
    row = connection.execute(
        f'SELECT id FROM "{table}" WHERE {where}', [value[field] for field in fields]
    ).fetchone()
    return int(row[0]) if row else None


def _record_order(item: Any) -> tuple[Any, ...]:
    row = item["value"]
    return (
        row.get("sequence", 0),
        str(row.get("created_at") or row.get("analysis_timestamp") or ""),
        item["key"],
    )


def _decode(value: Any, identities: Any, root: str, *, missing: Any = ...) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            if missing is ...:
                return identities[value["$ref"]]
            return identities.get(value["$ref"], missing)
        return {
            key: _decode(item, identities, root, missing=missing) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_decode(item, identities, root, missing=missing) for item in value]
    return value.replace("${CHECKOUT}", root) if isinstance(value, str) else value


def _prepare_row(table: str, value: Any, repository_id: int) -> dict[str, Any]:
    value = dict(value)
    if "repository_id" in value:
        value["repository_id"] = repository_id
    if value.get("scope_type") == "repository":
        value["scope_key"] = str(repository_id)
    if table in {"file_facts", "relationship_sets"}:
        field = "fact_key" if table == "file_facts" else "set_key"
        prefix = f"portable:{repository_id}:"
        if not str(value[field]).startswith(prefix):
            value[field] = prefix + str(value[field])
    for field in list(value):
        if field.endswith("_json"):
            value[field] = json.dumps(value[field], sort_keys=True, separators=(",", ":"))
    return value


def _save_row(connection: Any, table: str, value: dict[str, Any]) -> int:
    primary = primary_columns(connection, table)
    where = " AND ".join(f'"{field}" = ?' for field in primary)
    existing = connection.execute(
        f'SELECT * FROM "{table}" WHERE {where}', [value[field] for field in primary]
    ).fetchone()
    if existing:
        if table in {"semantic_scope_states", "semantic_taxonomies"} and _newer_local(
            existing, value
        ):
            return 0
        fields = [field for field in value if field not in primary]
        if fields:
            connection.execute(
                f'UPDATE "{table}" SET {",".join(f"{field} = ?" for field in fields)} WHERE {where}',
                [value[field] for field in (*fields, *primary)],
            )
    else:
        fields = list(value)
        connection.execute(
            f'INSERT INTO "{table}" ({",".join(fields)}) VALUES ({",".join("?" for _ in fields)})',
            [value[field] for field in fields],
        )
    return 1


def _newer_local(existing: Any, incoming: Any) -> bool:
    field = "last_checked_at" if "last_checked_at" in incoming else "updated_at"
    return existing["status"] == "current" and str(existing[field]) > str(incoming.get(field, ""))
