"""Resolve coding-agent focus and boundary evidence from canonical graph identities."""

from __future__ import annotations

from anaxigraph.knowledge_unresolved import unresolved_counts
from anaxigraph.knowledge_values import graph_select, node_value

_KINDS = {"module", "function", "interface", "contract", "capability", "type"}


def resolve_entity_focus(connection, snapshot, focus):
    if focus.partition(":")[0] not in _KINDS:
        return None
    row = connection.execute(
        graph_select() + " WHERE g.snapshot_id=? AND g.entity_id=?",
        (snapshot, focus),
    ).fetchone()
    if row is None:
        raise ValueError("The selected entity is absent from this graph revision")
    return node_value(row)


def focus_context(connection, snapshot, node):
    if node is None:
        return None
    owners = _owners(connection, snapshot, node)
    markers = ",".join("?" for _ in owners)
    rows = connection.execute(
        "SELECT e.*,s.path AS source_path,t.path AS target_path FROM graph_connections e "
        "JOIN graph_entities s ON s.snapshot_id=e.snapshot_id AND s.entity_id=e.source_id "
        "JOIN graph_entities t ON t.snapshot_id=e.snapshot_id AND t.entity_id=e.target_id "
        f"WHERE e.snapshot_id=? AND (e.source_id IN ({markers}) OR e.target_id IN ({markers})) "
        "AND e.relationship_type IN ('calls','tests','requires_contract') ORDER BY e.edge_id LIMIT 201",
        (snapshot, *owners, *owners),
    ).fetchall()
    selected = rows[:200]
    uncertainty = unresolved_counts(connection, snapshot, owners, direction="outgoing")
    return {
        **{key: node[key] for key in ("id", "kind", "path", "overview", "readiness")},
        "unresolved_connections": uncertainty["connections"],
        "unresolved_call_sites": uncertainty["call_sites"],
        "connections": [
            {
                "source": row["source_id"],
                "target": row["target_id"],
                "type": row["relationship_type"],
                "resolution": row["resolution"],
            }
            for row in selected[:12]
        ],
        "tests": sorted(
            {row["source_path"] for row in selected if row["relationship_type"] == "tests"}
        ),
        "bounded": len(rows) > 12,
        "details": {"tool": "ANAXIGRAPH_ENTITY", "arguments": {"entity_id": node["id"]}},
        "change_rule": "Reachability is context, not a required edit. Preserve caller obligations when implementation changes; check consumers when the contract changes.",
    }


def scoped_dependencies(connection, snapshot, node):
    owners = _owners(connection, snapshot, node)
    markers = ",".join("?" for _ in owners)
    rows = connection.execute(
        "SELECT e.source_id,e.target_id,s.artifact_id AS source,t.artifact_id AS target "
        "FROM graph_connections e JOIN graph_entities s ON s.snapshot_id=e.snapshot_id AND s.entity_id=e.source_id "
        "JOIN graph_entities t ON t.snapshot_id=e.snapshot_id AND t.entity_id=e.target_id "
        f"WHERE e.snapshot_id=? AND (e.source_id IN ({markers}) OR e.target_id IN ({markers})) "
        "AND e.relationship_type='calls' AND e.resolution='resolved_internal'",
        (snapshot, *owners, *owners),
    ).fetchall()
    return (
        {row["source"] for row in rows if row["target_id"] in owners and row["source"] is not None},
        {row["target"] for row in rows if row["source_id"] in owners and row["target"] is not None},
    )


def _owners(connection, snapshot, node):
    if node["kind"] == "interface":
        return [node["parent_id"]]
    if node["kind"] == "contract":
        rows = connection.execute(
            "SELECT source_id FROM graph_connections WHERE snapshot_id=? AND target_id=? AND relationship_type='requires_contract'",
            (snapshot, node["id"]),
        ).fetchall()
        return [row[0] for row in rows] or [node["id"]]
    return [node["id"]]
