"""One rebuildable FTS projection for module discovery and task seeding."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any, Iterable

from anaxigraph.agent_lexicon import goal_artifact_type, goal_terms, split_camel
from anaxigraph.knowledge_values import annotation_compatibility
from anaxigraph.persistence.module_read import read_modules
from anaxigraph.persistence.row_decoding import _decode_json_value
from anaxigraph.persistence.search_delta import projection_changes, taxonomy_provenance
from anaxigraph.persistence.search_storage import (
    SEARCH_CONTRACT_VERSION,
    clear_search_cache,
    delete_search_rows,
    ensure_search_schema,
    insert_search_rows,
    move_search_snapshot,
)
from anaxigraph.persistence.search_storage import (
    STATE_PREFIX as _STATE_PREFIX,
)
from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.temporal_reads import (
    artifact_types_for_files,
    snapshot_files,
    symbols_for_files,
)


def refresh_current_search_projections(connection: sqlite3.Connection) -> None:
    """Backfill missing projections before the service begins serving reads."""
    ensure_search_schema(connection)
    query = "SELECT id, current_snapshot_id FROM repositories WHERE current_snapshot_id IS NOT NULL"
    for repository_id, snapshot_id in connection.execute(query):
        refresh_search_projection(connection, int(repository_id), int(snapshot_id))


def defer_search_projection(connection):
    """Free disposable token pages before canonical planning; maintenance resumes the rebuild."""
    clear_search_cache(connection)
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta VALUES ('index-compaction-pending','true')"
    )


def refresh_search_projection(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    *,
    artifact_ids: Iterable[int] | None = None,
    force: bool = False,
) -> int:
    """Refresh all current rows or only explicitly changed module rows."""

    ensure_search_schema(connection)
    selected = tuple(sorted(set(artifact_ids or ()))) if artifact_ids is not None else None
    state = _projection_state(connection, repository_id)
    if selected is None and not force and state.get("snapshot_id") == snapshot_id:
        return int(state.get("rows", 0))
    selected = projection_changes(connection, repository_id, snapshot_id, state, selected)
    _refresh_selected_rows(connection, repository_id, snapshot_id, selected)
    move_search_snapshot(connection, repository_id, snapshot_id)
    count_sql = "SELECT COUNT(*) FROM module_search_rows WHERE repository_id = ?"
    count = int(connection.execute(count_sql, (repository_id,)).fetchone()[0])
    if state.get("snapshot_id") != snapshot_id or count != state.get("rows"):
        _write_projection_state(connection, repository_id, snapshot_id, count)
    return count


def _refresh_selected_rows(connection, repository_id, snapshot_id, selected):
    if selected == ():
        return
    rowids = delete_search_rows(connection, repository_id, selected)
    rows = _search_rows(connection, snapshot_id, selected)
    semantics = _semantic_documents(connection, snapshot_id, selected)
    assignments = taxonomy_assignments(connection, snapshot_id, artifact_ids=selected)
    insert_search_rows(
        connection,
        [
            _projection_row(
                repository_id,
                snapshot_id,
                dict(row),
                semantics.get(int(row["artifact_id"])),
                assignments.get(int(row["artifact_id"])),
            )
            for row in rows
        ],
        rowids=rowids,
    )


def search_modules(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    query: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return bounded, enriched results from the shared repository search projection."""

    ranked = search_module_hits(connection, repository_id, snapshot_id, query, limit=limit)
    if not ranked:
        return []
    artifact_ids = tuple(int(row["artifact_id"]) for row in ranked)
    results = read_modules(
        connection,
        repository_id,
        snapshot_id,
        artifact_ids=artifact_ids,
    )
    by_id = {int(row["artifact_id"]): row for row in results}
    return [{**by_id[int(hit["artifact_id"])], **hit} for hit in ranked]


def search_module_hits(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    query: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the shared ranked identities without hydrating full module records."""

    refresh_search_projection(connection, repository_id, snapshot_id)
    match = _match_expression(query)
    if not match:
        return []
    candidate_limit = min(500, max(50, limit * 5))
    matches = connection.execute(
        """
        SELECT r.artifact_id, r.artifact_type, r.path, r.name, r.symbols, r.provenance,
               bm25(module_search, 0, 0, 0, 0, 12, 14, 8, 4, 3, 2, 2, 0) AS rank
        FROM module_search JOIN module_search_rows r ON r.rowid=module_search.rowid
        WHERE module_search MATCH ? AND r.repository_id = ? AND r.snapshot_id = ?
        ORDER BY rank, r.path LIMIT ?
        """,
        (match, repository_id, snapshot_id, candidate_limit),
    ).fetchall()
    ranked = sorted(
        ((_score_match(dict(row), query), dict(row)) for row in matches),
        key=lambda pair: (-pair[0], str(pair[1]["path"])),
    )[:limit]
    return [
        {
            "artifact_id": int(row["artifact_id"]),
            "path": str(row["path"]),
            "score": round(score, 6),
            "search": {
                "contract_version": SEARCH_CONTRACT_VERSION,
                "snapshot_id": snapshot_id,
                "provenance": {
                    key: value
                    for key, value in json.loads(row["provenance"] or "{}").items()
                    if not key.startswith("_")
                },
            },
        }
        for score, row in ranked
    ]


def _search_rows(
    connection: sqlite3.Connection, snapshot_id: int, artifact_ids: tuple[int, ...] | None
) -> list[dict[str, Any]]:
    # A result updates one module: never rebuild the repository's metadata, symbols
    # and relationship TEMP tables while holding the shared SQLite write lock.
    files = snapshot_files(
        connection, snapshot_id, expand_metadata=False, artifact_ids=artifact_ids
    )
    types = artifact_types_for_files(connection, files)
    names: dict[int, list[str]] = defaultdict(list)
    for symbol in symbols_for_files(connection, files):
        names[int(symbol["artifact_id"])].append(str(symbol["name"]))
    return [
        {
            **file,
            "artifact_type": types[int(file["artifact_id"])],
            "symbol_names": " ".join(names[int(file["artifact_id"])]),
        }
        for file in files
    ]


def _semantic_documents(
    connection: sqlite3.Connection,
    snapshot_id: int,
    artifact_ids: tuple[int, ...] | None,
) -> dict[int, dict[str, Any]]:
    restriction = ""
    parameters: tuple[Any, ...] = (snapshot_id,)
    if artifact_ids is not None:
        if not artifact_ids:
            return {}
        placeholders = ",".join("?" for _ in artifact_ids)
        restriction = f"AND ss.artifact_id IN ({placeholders})"
        parameters = (snapshot_id, *artifact_ids)
    rows = connection.execute(
        f"""
        SELECT ss.artifact_id, sd.id AS document_id, sd.value_json, sd.provider, sd.confidence
        FROM semantic_scope_states ss
        JOIN semantic_document_values sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
          AND ss.status IN ('current', 'intrinsic_current') {restriction}
        """,
        parameters,
    ).fetchall()
    return {
        int(row["artifact_id"]): {
            **dict(row),
            "value": annotation_compatibility(json.loads(row["value_json"] or "{}")),
        }
        for row in rows
    }


def _projection_row(
    repository_id: int,
    snapshot_id: int,
    item: dict[str, Any],
    semantic: dict[str, Any] | None,
    assignment: dict[str, Any] | None,
) -> tuple[Any, ...]:
    value = (semantic or {}).get("value") or {}
    path = str(item["path"])
    name = PurePosixPath(path).name
    responsibilities = _joined(
        item.get("declared_group"),
        item.get("inferred_group"),
        _decode_json_value(item.get("responsibilities_json")),
        value.get("responsibilities"),
        value.get("domain_concepts"),
        value.get("architecture_role"),
        value.get("placement_guidance"),
        [(assignment or {}).get(key) for key in ("area_name", "subsystem_name")],
    )
    contracts = _joined(
        _decode_json_value(item.get("public_interfaces_json")),
        _decode_json_value(item.get("inputs_json")),
        _decode_json_value(item.get("outputs_json")),
        value.get("contracts") or value.get("public_contracts"),
        value.get("extension_points"),
    )
    summary = _joined(item.get("summary"), value.get("summary"), value.get("detail"))
    symbols = str(item.get("symbol_names") or "")
    alias_source = " ".join((path, name, symbols))
    aliases = " ".join(sorted(goal_terms(split_camel(alias_source))))
    provenance = {
        "deterministic": True,
        "semantic_document_id": (semantic or {}).get("document_id"),
        "semantic_provider": (semantic or {}).get("provider"),
        "semantic_confidence": (semantic or {}).get("confidence"),
        **taxonomy_provenance(assignment),
    }
    identity = (repository_id, snapshot_id, item["artifact_id"], item["artifact_type"], path, name)
    content = (symbols, summary, responsibilities, contracts, aliases)
    return (*identity, *content, json.dumps(provenance, sort_keys=True, separators=(",", ":")))


def _match_expression(query: str) -> str:
    terms = sorted(goal_terms(query))
    if not terms:
        terms = [word.casefold() for word in split_camel(query).split() if len(word) > 1]
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"*' for term in terms[:40])


def _score_match(row: dict[str, Any], query: str) -> float:
    normalized = query.casefold().strip()
    path = str(row["path"]).casefold()
    name = str(row["name"]).casefold()
    symbols = str(row["symbols"] or "").casefold().split()
    score = max(0.0, -float(row["rank"] or 0.0) * 100)
    score += 1_000 if normalized == path else 0
    score += 600 if normalized in {name, PurePosixPath(path).stem} else 0
    score += 400 if normalized in symbols else 0
    score += 100 if normalized and normalized in path else 0
    document_terms = goal_terms(" ".join((path, name, " ".join(symbols))))
    for position, raw in enumerate(split_camel(query).split()[:8]):
        aliases = goal_terms(raw)
        if aliases & document_terms:
            score += max(200, 2_500 - position * 350)
            break
    preferred = goal_artifact_type(query)
    if preferred == row["artifact_type"]:
        score *= 2
    elif row["artifact_type"] == "test":
        score *= 0.45
    return score


def _projection_state(connection: sqlite3.Connection, repository_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (f"{_STATE_PREFIX}{repository_id}",)
    ).fetchone()
    return json.loads(row[0]) if row else {}


def _write_projection_state(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    rows: int,
) -> None:
    value = json.dumps(
        {"snapshot_id": snapshot_id, "rows": rows}, sort_keys=True, separators=(",", ":")
    )
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
        (f"{_STATE_PREFIX}{repository_id}", value),
    )


def _joined(*values: Any) -> str:
    return " ".join(
        value if isinstance(value, str) else json.dumps(value, default=str)
        for value in values
        if value not in (None, "", [], {})
    )
