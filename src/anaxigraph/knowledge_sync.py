"""Build the canonical graph once per source revision, without retaining source text."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.knowledge_annotation import attach_annotation
from anaxigraph.knowledge_edges import function_links, prepare_function_links, structural_links
from anaxigraph.knowledge_grouping import place_area, place_files
from anaxigraph.knowledge_legacy import attach_legacy
from anaxigraph.knowledge_nodes import (
    insert_entity,
    interface_node,
    module_node,
    symbol_node,
)
from anaxigraph.knowledge_schema import KNOWLEDGE_VERSION, install_knowledge_schema
from anaxigraph.persistence.semantic_evidence import knowledge_snapshot_inputs


def sync_knowledge(connection: sqlite3.Connection, snapshot_id: int, *, force=False) -> None:
    install_knowledge_schema(connection)
    previous = connection.execute(
        "SELECT contract_version FROM graph_revisions WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()
    if previous and previous[0] == KNOWLEDGE_VERSION and not force:
        return
    snapshot = connection.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
    if snapshot is None:
        raise ValueError("Graph snapshot does not exist")
    clear_knowledge_cache(connection, keep_snapshot_id=snapshot_id)
    files, symbols, relationships = knowledge_snapshot_inputs(connection, snapshot_id)
    place_files(connection, snapshot_id, files)
    by_fact = _symbol_inventory(files, symbols)
    calls, references = prepare_function_links(files, symbols)
    _install_nodes(connection, snapshot_id, files, by_fact, references)
    _restore_annotations(connection, snapshot_id)
    structural_links(connection, snapshot_id, files, symbols, relationships)
    function_links(connection, snapshot_id, calls)
    refresh_degrees(connection, snapshot_id)
    refresh_metrics(connection, snapshot_id, snapshot["repository_id"])
    connection.execute(
        "INSERT OR REPLACE INTO graph_revisions VALUES (?,?,?)",
        (snapshot_id, KNOWLEDGE_VERSION, snapshot["content_fingerprint"]),
    )


def clear_knowledge_cache(connection, *, keep_snapshot_id=None):
    """Release rebuildable projection pages inside the caller's atomic transaction."""
    where = " WHERE snapshot_id!=?" if keep_snapshot_id is not None else ""
    parameters = (keep_snapshot_id,) if keep_snapshot_id is not None else ()
    for table in ("graph_links", "graph_entities", "graph_revisions"):
        connection.execute(f"DELETE FROM {table}{where}", parameters)


def _restore_annotations(connection, snapshot):
    rows = connection.execute(
        """SELECT g.path,g.annotation_id,d.id,d.document_kind,d.value_json FROM graph_entities g
        JOIN semantic_document_values d ON d.id=g.annotation_id
        WHERE g.snapshot_id=? AND g.kind='module'""",
        (snapshot,),
    ).fetchall()
    for row in rows:
        if row["document_kind"] != "annotation":
            attach_legacy(connection, snapshot, row["path"], dict(row))
            continue
        attach_annotation(
            connection,
            {"snapshot_id": snapshot, "scope_key": row["path"]},
            row["annotation_id"],
            json.loads(row["value_json"]),
        )


def refresh_metrics(connection, snapshot, repository):
    connection.execute(
        """UPDATE graph_entities SET
        line_coverage=(SELECT MAX(line_coverage) FROM coverage_measurements c
            WHERE c.snapshot_id=? AND c.artifact_id=graph_entities.artifact_id),
        change_count=(SELECT change_count FROM git_path_metrics h WHERE h.repository_id=?
            AND h.path=graph_entities.path),
        first_changed_at=(SELECT first_changed_at FROM git_path_metrics h WHERE h.repository_id=?
            AND h.path=graph_entities.path),
        last_commit_at=(SELECT last_changed_at FROM git_path_metrics h WHERE h.repository_id=?
            AND h.path=graph_entities.path)
        WHERE snapshot_id=? AND kind='module'""",
        (snapshot, repository, repository, repository, snapshot),
    )


def _symbol_inventory(files, symbols):
    by_fact = defaultdict(list)
    file_by_fact = {file["file_fact_id"]: file for file in files}
    for symbol in symbols:
        file = file_by_fact[symbol["file_fact_id"]]
        symbol.update(path=file["path"], artifact_id=file["artifact_id"])
        by_fact[symbol["file_fact_id"]].append(symbol)
    return by_fact


def _install_nodes(connection, snapshot, files, by_fact, references) -> None:
    connection.execute("DELETE FROM graph_links WHERE snapshot_id=?", (snapshot,))
    connection.execute("DELETE FROM graph_entities WHERE snapshot_id=?", (snapshot,))
    for file in files:
        node = module_node(file, by_fact[file["file_fact_id"]])
        _annotation_reference(connection, snapshot, node)
        _insert_call_owner(connection, snapshot, node, references)
        place_area(connection, snapshot, node)
        for symbol in by_fact[file["file_fact_id"]]:
            item = symbol_node(file, symbol)
            _insert_call_owner(connection, snapshot, item, references)
            if item["kind"] == "function" and symbol.get("visibility") == "public":
                insert_entity(connection, snapshot, interface_node(item))


def _insert_call_owner(connection, snapshot, node, references):
    properties = references.get(node["entity_id"])
    if properties:
        node = {
            **node,
            "properties_json": json.dumps(
                {**json.loads(node["properties_json"]), **properties}, separators=(",", ":")
            ),
        }
    insert_entity(connection, snapshot, node)


def _annotation_reference(connection, snapshot, node) -> None:
    row = connection.execute(
        """SELECT d.id FROM semantic_scope_states s JOIN semantic_document_values d
        ON d.id=COALESCE(s.context_document_id,s.intrinsic_document_id)
        JOIN file_facts f ON f.id=d.file_fact_id WHERE s.snapshot_id=?
        AND s.scope_type='module' AND s.scope_key=? AND f.raw_hash=?""",
        (snapshot, node["path"], json.loads(node["properties_json"])["source_fingerprint"]),
    ).fetchone()
    if row and row[0]:
        node["annotation_id"] = row[0]
        node["annotation_selector"] = "$"


def refresh_degrees(connection: sqlite3.Connection, snapshot_id: int) -> None:
    connection.execute(
        """UPDATE graph_entities SET
        fan_in=(SELECT COUNT(DISTINCT source_node) FROM graph_links e
                JOIN graph_entities neighbor ON neighbor.node_id=e.source_node
                WHERE e.target_node=graph_entities.node_id
                AND neighbor.reference=0 AND graph_entities.reference=0
                AND e.relationship_type IN ('calls','imports','extends','references')),
        fan_out=(SELECT COUNT(DISTINCT target_node) FROM graph_links e
                 JOIN graph_entities neighbor ON neighbor.node_id=e.target_node
                 WHERE e.source_node=graph_entities.node_id
                 AND neighbor.reference=0 AND graph_entities.reference=0
                 AND e.relationship_type IN ('calls','imports','extends','references'))
        WHERE snapshot_id=?""",
        (snapshot_id,),
    )


def ensure_knowledge(database: Any, repository_id: int, snapshot_id: int | None = None) -> int:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT current_snapshot_id FROM repositories WHERE id=?", (repository_id,)
        ).fetchone()
        chosen = snapshot_id if snapshot_id is not None else (row[0] if row else None)
        if not chosen:
            raise ValueError("Repository has not been mapped")
        snapshot = connection.execute(
            "SELECT repository_id FROM snapshots WHERE id=?", (chosen,)
        ).fetchone()
        if not snapshot or snapshot[0] != repository_id:
            raise ValueError("Snapshot does not belong to this repository")
        ready = connection.execute(
            "SELECT 1 FROM graph_revisions WHERE snapshot_id=? AND contract_version=?",
            (chosen, KNOWLEDGE_VERSION),
        ).fetchone()
    if not ready:
        database.rebuild_graph_cache(int(chosen))
    return int(chosen)
