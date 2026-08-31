"""One rebuildable FTS projection for module discovery and task seeding."""

from __future__ import annotations

import json
import sqlite3
from pathlib import PurePosixPath
from typing import Any, Iterable

from anaxigraph.agent_lexicon import goal_artifact_type, goal_terms, split_camel
from anaxigraph.persistence.module_read import read_modules
from anaxigraph.persistence.row_decoding import _decode_json_value
from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection

SEARCH_CONTRACT_VERSION = "module-search-fts-v1"
_CONTRACT_KEY = "module_search_contract"
_STATE_PREFIX = "module_search_state:"
_CREATE_SEARCH = """
CREATE VIRTUAL TABLE module_search USING fts5(
    repository_id UNINDEXED,
    snapshot_id UNINDEXED,
    artifact_id UNINDEXED,
    artifact_type UNINDEXED,
    path,
    name,
    symbols,
    summary,
    responsibilities,
    contracts,
    aliases,
    provenance UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""


def ensure_search_schema(connection: sqlite3.Connection) -> None:
    """Install or replace the disposable projection without changing canonical schema."""

    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (_CONTRACT_KEY,)
    ).fetchone()
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'module_search'"
    ).fetchone()
    if row is not None and row[0] == SEARCH_CONTRACT_VERSION and table is not None:
        return
    connection.execute("DROP TABLE IF EXISTS module_search")
    connection.execute(_CREATE_SEARCH)
    connection.execute("DELETE FROM schema_meta WHERE key LIKE ?", (f"{_STATE_PREFIX}%",))
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
        (_CONTRACT_KEY, SEARCH_CONTRACT_VERSION),
    )


def invalidate_search_projection(connection: sqlite3.Connection, repository_id: int) -> None:
    """Make the next query rebuild after same-snapshot semantic state changes."""

    connection.execute(
        "DELETE FROM schema_meta WHERE key = ?", (f"{_STATE_PREFIX}{repository_id}",)
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
    if selected is not None and state.get("snapshot_id") != snapshot_id:
        selected = None

    install_snapshot_projection(connection, snapshot_id)
    if selected is None:
        connection.execute("DELETE FROM module_search WHERE repository_id = ?", (repository_id,))
    elif selected:
        placeholders = ",".join("?" for _ in selected)
        connection.execute(
            f"DELETE FROM module_search WHERE repository_id = ? "
            f"AND artifact_id IN ({placeholders})",
            (repository_id, *selected),
        )
    rows = _search_rows(connection, selected)
    semantics = _semantic_documents(connection, snapshot_id, selected)
    assignments = taxonomy_assignments(connection, snapshot_id, artifact_ids=selected)
    connection.executemany(
        "INSERT INTO module_search VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    )
    count_sql = "SELECT COUNT(*) FROM module_search WHERE repository_id = ?"
    count = int(connection.execute(count_sql, (repository_id,)).fetchone()[0])
    _write_projection_state(connection, repository_id, snapshot_id, count)
    return count


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
        SELECT artifact_id, artifact_type, path, name, symbols, provenance,
               bm25(module_search, 0, 0, 0, 0, 12, 14, 8, 4, 3, 2, 2, 0) AS rank
        FROM module_search
        WHERE module_search MATCH ? AND repository_id = ? AND snapshot_id = ?
        ORDER BY rank, path LIMIT ?
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
                "provenance": json.loads(row["provenance"] or "{}"),
            },
        }
        for score, row in ranked
    ]


def _search_rows(
    connection: sqlite3.Connection, artifact_ids: tuple[int, ...] | None
) -> list[sqlite3.Row]:
    restriction = ""
    parameters: tuple[Any, ...] = ()
    if artifact_ids is not None:
        if not artifact_ids:
            return []
        placeholders = ",".join("?" for _ in artifact_ids)
        restriction = f"WHERE a.id IN ({placeholders})"
        parameters = artifact_ids
    return connection.execute(
        f"""
        SELECT a.id AS artifact_id, a.artifact_type, fv.path, fv.summary,
               fv.declared_group, fv.inferred_group,
               fv.responsibilities_json, fv.inputs_json, fv.outputs_json,
               fv.public_interfaces_json, GROUP_CONCAT(s.name, ' ') AS symbol_names
        FROM projected_file_versions fv JOIN artifacts a ON a.id = fv.artifact_id
        LEFT JOIN projected_symbols s ON s.artifact_version_id = fv.id
        {restriction}
        GROUP BY fv.id ORDER BY fv.path
        """,
        parameters,
    ).fetchall()


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
        JOIN semantic_documents sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
          AND ss.status IN ('current', 'intrinsic_current') {restriction}
        """,
        parameters,
    ).fetchall()
    return {
        int(row["artifact_id"]): {**dict(row), "value": json.loads(row["value_json"] or "{}")}
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
        (assignment or {}).values(),
    )
    contracts = _joined(
        _decode_json_value(item.get("public_interfaces_json")),
        _decode_json_value(item.get("inputs_json")),
        _decode_json_value(item.get("outputs_json")),
        value.get("public_contracts"),
        value.get("extension_points"),
    )
    summary = _joined(item.get("summary"), value.get("summary"), value.get("detailed_summary"))
    symbols = str(item.get("symbol_names") or "")
    alias_source = " ".join((path, name, symbols, summary, responsibilities, contracts))
    aliases = " ".join(sorted(goal_terms(split_camel(alias_source))))
    provenance = {
        "deterministic": True,
        "semantic_document_id": (semantic or {}).get("document_id"),
        "semantic_provider": (semantic or {}).get("provider"),
        "semantic_confidence": (semantic or {}).get("confidence"),
        "taxonomy_id": (assignment or {}).get("taxonomy_id"),
        "taxonomy_confidence": (assignment or {}).get("confidence"),
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
