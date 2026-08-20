"""Immutable file facts and sparse per-snapshot placement changes."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.ir_serialization import compact_stored_metadata
from anaxigraph.persistence.temporal_hashing import digest


def legacy_file_facts(
    connection: sqlite3.Connection,
    snapshot_id: int,
    analysis_signature: str,
) -> dict[int, dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM file_versions WHERE snapshot_id = ? ORDER BY artifact_id",
        (snapshot_id,),
    ).fetchall()
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        value = dict(row)
        fact_id = _upsert_file_fact(connection, value, analysis_signature)
        _upsert_symbols(connection, int(value["id"]), fact_id)
        value["file_fact_id"] = fact_id
        result[int(value["artifact_id"])] = value
    return result


def persist_file_changes(
    connection: sqlite3.Connection,
    snapshot_id: int,
    previous: dict[int, dict[str, Any]],
    current: dict[int, dict[str, Any]],
) -> None:
    connection.execute(
        "DELETE FROM snapshot_file_changes WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    for artifact_id in sorted(set(previous) | set(current)):
        prior = previous.get(artifact_id)
        value = current.get(artifact_id)
        if value is None:
            connection.execute(
                """
                INSERT INTO snapshot_file_changes(snapshot_id, artifact_id, change_kind)
                VALUES (?, ?, 'delete')
                """,
                (snapshot_id, artifact_id),
            )
            continue
        if prior is not None and _file_state(prior) == _file_state(value):
            continue
        connection.execute(
            """
            INSERT INTO snapshot_file_changes(
                snapshot_id, artifact_id, change_kind, file_fact_id, path,
                declared_group, inferred_group, analysis_status, metadata_json,
                first_seen_at, last_changed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                artifact_id,
                "add" if prior is None else "change",
                value["file_fact_id"],
                value["path"],
                value["declared_group"],
                value["inferred_group"],
                value["analysis_status"],
                _placement_metadata(value["metadata_json"]),
                value["first_seen_at"],
                value["last_changed_at"],
            ),
        )


def compact_file_placement_metadata(connection: sqlite3.Connection) -> int:
    """Remove immutable analyzer IR duplicated in delta and checkpoint placements."""

    updated = 0
    for table in ("snapshot_file_changes", "checkpoint_files"):
        rows = connection.execute(f"SELECT rowid, metadata_json FROM {table}").fetchall()
        values = []
        for row in rows:
            encoded = _placement_metadata(row["metadata_json"])
            if encoded != row["metadata_json"]:
                values.append((encoded, int(row["rowid"])))
        connection.executemany(
            f"UPDATE {table} SET metadata_json = ? WHERE rowid = ?",
            values,
        )
        updated += len(values)
    return updated


def compact_file_fact_metadata(connection: sqlite3.Connection) -> int:
    """Compact derivable analyzer IR already stored in immutable file facts."""

    updates = []
    for row in connection.execute(
        """SELECT ff.id, ff.language, ff.metadata_json, ff.public_interfaces_json,
                  a.canonical_path
           FROM file_facts ff JOIN artifacts a ON a.id = ff.artifact_id
           ORDER BY ff.id"""
    ).fetchall():
        metadata = compact_stored_metadata(
            json.loads(row["metadata_json"] or "{}"),
            path=str(row["canonical_path"]),
            language=str(row["language"]),
            public_interfaces=json.loads(row["public_interfaces_json"] or "[]"),
        )
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        if encoded != row["metadata_json"]:
            updates.append((encoded, int(row["id"])))
    connection.executemany("UPDATE file_facts SET metadata_json = ? WHERE id = ?", updates)
    return len(updates)


def _upsert_file_fact(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    analysis_signature: str,
) -> int:
    metadata = json.loads(row["metadata_json"] or "{}")
    fact_key = digest(
        [
            row["artifact_id"],
            row["raw_hash"],
            row["structural_hash"],
            row["analyzer"],
            metadata.get("analysis_version"),
            analysis_signature,
        ]
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO file_facts(
            artifact_id, fact_key, analysis_signature, language, runtime, raw_hash,
            structural_hash, lines_of_code, comment_lines, complexity, summary,
            responsibilities_json, inputs_json, outputs_json, side_effects_json,
            public_interfaces_json, analyzer, parse_error, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _fact_values(row, fact_key, analysis_signature, metadata),
    )
    found = connection.execute(
        "SELECT id FROM file_facts WHERE fact_key = ?",
        (fact_key,),
    ).fetchone()
    assert found is not None
    return int(found["id"])


def _fact_values(
    row: dict[str, Any],
    fact_key: str,
    analysis_signature: str,
    metadata: dict[str, Any],
) -> tuple[Any, ...]:
    transient = {"invalidation_reason", "history_change_kind", "source_read"}
    stable_metadata = {key: value for key, value in metadata.items() if key not in transient}
    fact_metadata = compact_stored_metadata(
        stable_metadata,
        path=str(row["path"]),
        language=str(row["language"]),
        public_interfaces=json.loads(row["public_interfaces_json"] or "[]"),
    )
    return (
        row["artifact_id"],
        fact_key,
        analysis_signature,
        row["language"],
        row["runtime"],
        row["raw_hash"],
        row["structural_hash"],
        row["lines_of_code"],
        row["comment_lines"],
        row["complexity"],
        row["summary"],
        row["responsibilities_json"],
        row["inputs_json"],
        row["outputs_json"],
        row["side_effects_json"],
        row["public_interfaces_json"],
        row["analyzer"],
        row["parse_error"],
        json.dumps(fact_metadata, sort_keys=True, separators=(",", ":")),
        row["first_seen_at"],
    )


def _upsert_symbols(
    connection: sqlite3.Connection,
    legacy_version_id: int,
    fact_id: int,
) -> None:
    version = connection.execute(
        "SELECT metadata_json FROM file_versions WHERE id = ?",
        (legacy_version_id,),
    ).fetchone()
    details = _symbol_details(version["metadata_json"] if version else "{}")
    rows = connection.execute(
        "SELECT * FROM symbols WHERE artifact_version_id = ? ORDER BY start_line, id",
        (legacy_version_id,),
    ).fetchall()
    connection.executemany(
        """
        INSERT OR IGNORE INTO fact_symbols(
            file_fact_id, symbol_type, name, qualified_name, start_line, end_line,
            signature, summary, complexity, logical_lines, visibility,
            start_column, end_column
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                fact_id,
                row["symbol_type"],
                row["name"],
                row["qualified_name"],
                row["start_line"],
                row["end_line"],
                row["signature"],
                row["summary"],
                row["complexity"],
                row["logical_lines"],
                details.get((row["qualified_name"], int(row["start_line"])), {}).get(
                    "visibility", "unknown"
                ),
                details.get((row["qualified_name"], int(row["start_line"])), {}).get(
                    "start_column", 0
                ),
                details.get((row["qualified_name"], int(row["start_line"])), {}).get(
                    "end_column", 0
                ),
            )
            for row in rows
        ],
    )


def backfill_fact_symbol_details(connection: sqlite3.Connection) -> int:
    """Populate symbol IR columns before compacting older fact metadata."""

    updated = 0
    for fact in connection.execute("SELECT id, metadata_json FROM file_facts").fetchall():
        details = _symbol_details(fact["metadata_json"])
        for key, value in details.items():
            cursor = connection.execute(
                """UPDATE fact_symbols
                   SET visibility = ?, start_column = ?, end_column = ?
                   WHERE file_fact_id = ? AND qualified_name = ? AND start_line = ?""",
                (
                    value.get("visibility", "unknown"),
                    value.get("start_column", 0),
                    value.get("end_column", 0),
                    fact["id"],
                    key[0],
                    key[1],
                ),
            )
            updated += max(0, cursor.rowcount)
    return updated


def _symbol_details(metadata_json: Any) -> dict[tuple[str, int], dict[str, Any]]:
    metadata = json.loads(metadata_json or "{}")
    return {
        (item["qualified_name"], int(item["start_line"])): item
        for item in (metadata.get("ir") or {}).get("symbols") or []
    }


def _file_state(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("file_fact_id"),
        row.get("path"),
        row.get("declared_group"),
        row.get("inferred_group"),
        row.get("first_seen_at"),
        row.get("last_changed_at"),
    )


def _placement_metadata(metadata_json: Any) -> str:
    metadata = json.loads(metadata_json or "{}")
    transient = {
        key: metadata[key]
        for key in ("invalidation_reason", "history_change_kind", "source_read")
        if key in metadata
    }
    return json.dumps(transient, sort_keys=True, separators=(",", ":"))
