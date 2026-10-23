"""Canonical property-graph identities and bounded snapshot indexes."""

from __future__ import annotations

import json
import sqlite3

KNOWLEDGE_VERSION = "semantic-graph-v4"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS graph_entities (
        node_id INTEGER PRIMARY KEY,
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
        entity_id TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
        path TEXT NOT NULL DEFAULT '', parent_id TEXT,
        artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
        file_fact_id INTEGER REFERENCES file_facts(id) ON DELETE CASCADE,
        symbol_id INTEGER REFERENCES fact_symbols(id) ON DELETE CASCADE,
        annotation_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
        annotation_selector TEXT NOT NULL DEFAULT '',
        overview TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
        lines_of_code INTEGER, complexity REAL, function_count INTEGER,
        fan_in INTEGER NOT NULL DEFAULT 0, fan_out INTEGER NOT NULL DEFAULT 0,
        line_coverage REAL, change_count INTEGER, first_changed_at TEXT, last_commit_at TEXT,
        area TEXT NOT NULL DEFAULT '', subsystem TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '', reference INTEGER NOT NULL DEFAULT 0,
        properties_json TEXT NOT NULL DEFAULT '{}', provenance_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(snapshot_id, entity_id)
    )""",
    """CREATE TABLE IF NOT EXISTS graph_links (
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
        edge_id TEXT NOT NULL,
        source_node INTEGER NOT NULL REFERENCES graph_entities(node_id) ON DELETE CASCADE,
        target_node INTEGER NOT NULL REFERENCES graph_entities(node_id) ON DELETE CASCADE,
        relationship_type TEXT NOT NULL, confidence REAL NOT NULL,
        resolution TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '[]',
        method TEXT NOT NULL DEFAULT 'extracted',
        PRIMARY KEY(snapshot_id, edge_id)
    )""",
    """CREATE VIEW IF NOT EXISTS graph_connections AS SELECT e.snapshot_id,e.edge_id,
        s.entity_id AS source_id,t.entity_id AS target_id,e.relationship_type,e.confidence,
        e.resolution,anaxigraph_graph_evidence(e.evidence_json,s.path) AS evidence_json,json_object('method',e.method) AS provenance_json
        FROM graph_links e JOIN graph_entities s ON s.node_id=e.source_node
        JOIN graph_entities t ON t.node_id=e.target_node""",
    """CREATE TRIGGER IF NOT EXISTS graph_connections_insert INSTEAD OF INSERT ON graph_connections
        BEGIN INSERT OR REPLACE INTO graph_links VALUES(NEW.snapshot_id,NEW.edge_id,
        (SELECT node_id FROM graph_entities WHERE snapshot_id=NEW.snapshot_id AND entity_id=NEW.source_id),
        (SELECT node_id FROM graph_entities WHERE snapshot_id=NEW.snapshot_id AND entity_id=NEW.target_id),
        NEW.relationship_type,NEW.confidence,NEW.resolution,NEW.evidence_json,
        COALESCE(json_extract(NEW.provenance_json,'$.method'),'extracted')); END""",
    """CREATE TRIGGER IF NOT EXISTS graph_connections_delete INSTEAD OF DELETE ON graph_connections
        BEGIN DELETE FROM graph_links WHERE snapshot_id=OLD.snapshot_id AND edge_id=OLD.edge_id; END""",
    """CREATE TABLE IF NOT EXISTS graph_revisions (
        snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
        contract_version TEXT NOT NULL, source_fingerprint TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS graph_entities_by_kind ON graph_entities(snapshot_id,kind)",
    "CREATE INDEX IF NOT EXISTS graph_modules_loc ON graph_entities(snapshot_id,lines_of_code) WHERE kind='module'",
    "CREATE INDEX IF NOT EXISTS graph_entities_fact ON graph_entities(file_fact_id)",
    "CREATE INDEX IF NOT EXISTS graph_links_source ON graph_links(source_node)",
    "CREATE INDEX IF NOT EXISTS graph_links_target ON graph_links(target_node)",
)


def install_knowledge_schema(connection: sqlite3.Connection) -> None:
    _retire_development_cache(connection)
    connection.execute("DROP INDEX IF EXISTS graph_entities_loc")
    connection.execute("DROP INDEX IF EXISTS graph_entities_kind")
    old = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='graph_connections'"
    ).fetchone()
    if old and "anaxigraph_graph_evidence" not in old[0]:
        connection.execute("DROP TRIGGER IF EXISTS graph_connections_insert")
        connection.execute("DROP TRIGGER IF EXISTS graph_connections_delete")
        connection.execute("DROP VIEW graph_connections")
    for statement in _SCHEMA:
        connection.execute(statement)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(graph_entities)")}
    for name, kind in (
        ("line_coverage", "REAL"),
        ("change_count", "INTEGER"),
        ("first_changed_at", "TEXT"),
        ("last_commit_at", "TEXT"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE graph_entities ADD COLUMN {name} {kind}")


def _retire_development_cache(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(graph_entities)")}
    if columns and "node_id" not in columns:
        # Only derived graph rows are replaced. Canonical source facts and all paid
        # annotations remain intact and rebuild this cache on the next graph read.
        connection.execute("DROP TABLE IF EXISTS graph_connections")
        connection.execute("DROP TABLE IF EXISTS graph_revisions")
        connection.execute("DROP TABLE graph_entities")


def compact_edge_evidence(evidence, source):
    kind, _, path = source.partition(":")
    if kind not in {"module", "function", "interface", "type"} or not isinstance(evidence, list):
        return evidence
    path = path.partition("#")[0]
    return [
        {**{key: value for key, value in item.items() if key != "path"}, "_source_path": True}
        if isinstance(item, dict) and item.get("path") == path and "_source_path" not in item
        else item
        for item in evidence
    ]


def expand_edge_evidence(value, source_path):
    if "_source_path" not in value:
        return value
    result = json.loads(value)
    for item in result:
        if isinstance(item, dict) and item.get("_source_path") is True:
            item.pop("_source_path")
            item["path"] = source_path
    return json.dumps(result)
