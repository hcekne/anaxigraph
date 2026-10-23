"""Bind validated saved understanding without copying its hashes and explanatory state."""

from __future__ import annotations

import json

from anaxigraph.clock import utc_now
from anaxigraph.persistence.search_delta import source_contexts
from anaxigraph.persistence.temporal_reads import snapshot_files
from anaxigraph.semantic_freshness import is_expired

_MODULE_SCHEMAS = {
    "graph-annotation-v1",
    "module-dossier-v4",
    "repository-understanding-v5",
    "repository-understanding-v6",
    "repository-understanding-v7",
}


def carry_compatible_states(connection, repository, snapshot, previous, config):
    if previous is None or previous == snapshot:
        return 0
    files = {
        row["artifact_id"]: row
        for row in snapshot_files(connection, snapshot, expand_metadata=False)
    }
    current = source_contexts(connection, snapshot, files=files)
    old = source_contexts(connection, previous)
    rows = connection.execute(
        """SELECT b.*,s.status,s.intrinsic_document_id,s.context_document_id
        FROM semantic_state_bindings b JOIN semantic_state_records s ON s.id=b.state_id
        WHERE b.repository_id=? AND b.snapshot_id=? AND s.status IN ('current','intrinsic_current')""",
        (repository, previous),
    ).fetchall()
    documents = _documents(connection, rows)
    identical = current == old
    now, carried = utc_now(), 0
    for row in rows:
        if not _compatible(row, documents, files, current, old, config.semantic, identical):
            continue
        file = files.get(row["artifact_id"])
        carried += connection.execute(
            """INSERT OR IGNORE INTO semantic_state_bindings(
            repository_id,snapshot_id,scope_type,scope_key,artifact_id,artifact_version_id,
            file_fact_id,state_id,last_checked_at) VALUES(?,?,?,?,?,NULL,?,?,?)""",
            (
                repository,
                snapshot,
                row["scope_type"],
                row["scope_key"],
                row["artifact_id"],
                file["file_fact_id"] if file else row["file_fact_id"],
                row["state_id"],
                now,
            ),
        ).rowcount
    return carried


def _documents(connection, states):
    identifiers = list(
        {
            row[name]
            for row in states
            for name in ("intrinsic_document_id", "context_document_id")
            if row[name] is not None
        }
    )
    return {
        row["id"]: dict(row)
        for row in connection.execute(
            """SELECT d.id,d.scope_type,d.schema_version,d.prompt_version,d.created_at,f.raw_hash
            FROM semantic_documents d LEFT JOIN file_facts f ON f.id=d.file_fact_id
            WHERE d.id IN (SELECT value FROM json_each(?))""",
            (json.dumps(identifiers),),
        )
    }


def _compatible(state, documents, files, current, previous, semantic, identical):
    module = state["scope_type"] == "module"
    file = files.get(state["artifact_id"])
    if module and (
        file is None
        or current.get(state["artifact_id"]) != previous.get(state["artifact_id"])
        or state["scope_key"] != file["path"]
        or not semantic.includes_path(file["path"])
    ):
        return False
    if not module and not identical:
        return False
    if not module and state["scope_type"] not in {
        "group",
        "repository",
        "taxonomy",
        "pattern",
        "pattern_plan",
    }:
        return False
    identifiers = {
        state[name]
        for name in ("intrinsic_document_id", "context_document_id")
        if state[name] is not None
    }
    if not identifiers:
        return False
    return all(
        _valid_document(documents.get(identifier), module, file, semantic)
        for identifier in identifiers
    )


def _valid_document(document, module, file, semantic):
    if document is None or document["prompt_version"] != semantic.prompt_version:
        return False
    if is_expired(document["created_at"], semantic.max_age_days):
        return False
    return not module or (
        document["schema_version"] in _MODULE_SCHEMAS
        and document["scope_type"] == "module"
        and document["raw_hash"] == file["raw_hash"]
    )
