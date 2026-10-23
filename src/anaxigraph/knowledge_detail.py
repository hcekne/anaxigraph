"""Bounded entity inspection and directed neighborhood traversal."""

from __future__ import annotations

from contextlib import closing

from anaxigraph.knowledge_legacy import legacy_connections, legacy_node, legacy_obligations
from anaxigraph.knowledge_query import graph_context
from anaxigraph.knowledge_sync import ensure_knowledge
from anaxigraph.knowledge_unresolved import (
    unresolved_connections,
    unresolved_counts,
    unresolved_node,
)
from anaxigraph.knowledge_values import (
    EVIDENCE_STATES,
    classify_evidence,
    edge_value,
    evidence_predicate,
    graph_select,
    node_value,
)


def entity_detail(
    database, repository_id, entity_id, snapshot_id=None, *, legacy_offset=0, legacy_limit=25
):
    snapshot = ensure_knowledge(database, repository_id, snapshot_id)
    with closing(database.connect()) as connection:
        connection.execute("BEGIN")
        node = _node(connection, snapshot, entity_id)
        clause, parameters = _child_scope(node, snapshot)
        children = connection.execute(
            graph_select(detail=True) + " WHERE g.snapshot_id=? AND (" + clause + ") "
            "AND g.kind IN ('function','interface','contract') ORDER BY g.entity_id LIMIT 100",
            (snapshot, *parameters),
        ).fetchall()
        links = _incident(connection, snapshot, [entity_id], "both", "", 250)
        legacy = (
            legacy_obligations(
                connection,
                snapshot,
                node["path"],
                offset=max(0, legacy_offset),
                limit=min(100, max(1, legacy_limit)),
            )
            if node["kind"] == "module"
            else {"items": [], "total": 0, "returned": 0}
        )
        counts = _detail_counts(connection, snapshot, node, children, links, legacy)
        return {
            "context": graph_context(connection, repository_id, snapshot),
            "node": node,
            **{
                key: [node_value(row, detail=True) for row in children if row["kind"] == kind]
                for key, kind in (
                    ("functions", "function"),
                    ("interfaces", "interface"),
                    ("contracts", "contract"),
                )
            },
            "connections": {
                "incoming": [edge_value(e) for e in links if e["target_id"] == entity_id],
                "outgoing": [edge_value(e) for e in links if e["source_id"] == entity_id],
                "tests": [edge_value(e) for e in links if e["relationship_type"] == "tests"],
            },
            "counts": counts,
            "legacy_obligations": legacy,
            "limits": {"children": 100, "connections": 250},
        }


def _detail_counts(connection, snapshot, node, children, links, legacy):
    clause, parameters = _child_scope(node, snapshot)
    counts = dict(
        connection.execute(
            "SELECT g.kind,COUNT(*) FROM graph_entities g WHERE g.snapshot_id=? AND ("
            + clause
            + ") GROUP BY g.kind",
            (snapshot, *parameters),
        ).fetchall()
    )
    total = connection.execute(
        "SELECT COUNT(*) FROM graph_links WHERE source_node IN (SELECT node_id FROM graph_entities WHERE snapshot_id=? AND entity_id=?) OR target_node IN (SELECT node_id FROM graph_entities WHERE snapshot_id=? AND entity_id=?)",
        (snapshot, node["id"], snapshot, node["id"]),
    ).fetchone()[0]
    total += legacy["total"] + int(node.get("properties", {}).get("legacy_obligation", False))
    total += unresolved_counts(connection, snapshot, [node["id"]])["connections"]
    child_total = sum(counts.get(kind, 0) for kind in ("function", "interface", "contract"))
    return {
        **counts,
        "children_total": child_total,
        "children_returned": len(children),
        "connections_total": total,
        "connections_returned": len(links),
        "omitted_children": max(0, child_total - len(children)),
        "omitted_connections": max(0, total - len(links)),
        "legacy_obligations_total": legacy["total"],
        "legacy_obligations_returned": legacy["returned"],
        "omitted_legacy_obligations": legacy["total"] - legacy["returned"],
    }


def _child_scope(node, snapshot):
    if node["kind"] == "module":
        return "g.path=?", (node["path"],)
    owner = node["parent_id"] if node["kind"] == "interface" else node["id"]
    if node["kind"] == "contract":
        return (
            "g.node_id IN (SELECT source_node FROM graph_links WHERE snapshot_id=? AND target_node=(SELECT node_id FROM graph_entities WHERE snapshot_id=? AND entity_id=?) AND relationship_type='requires_contract')",
            (snapshot, snapshot, node["id"]),
        )
    return (
        "g.node_id IN (SELECT target_node FROM graph_links WHERE snapshot_id=? AND source_node=(SELECT node_id FROM graph_entities WHERE snapshot_id=? AND entity_id=?) AND relationship_type IN ('requires_contract','implements'))",
        (snapshot, snapshot, owner),
    )


def _node(connection, snapshot, entity_id):
    row = connection.execute(
        graph_select(detail=True) + " WHERE g.snapshot_id=? AND g.entity_id=?",
        (snapshot, entity_id),
    ).fetchone()
    if row is not None:
        return node_value(row, detail=True)
    node = unresolved_node(connection, snapshot, entity_id, detail=True) or legacy_node(
        connection, snapshot, entity_id, detail=True
    )
    if node is None:
        raise ValueError("Entity does not exist in the selected graph revision")
    return node


def neighborhood(
    database,
    repository_id,
    entity_id,
    snapshot_id=None,
    *,
    depth=1,
    direction="both",
    relationship_type="",
    limit=100,
    evidence_state="",
):
    snapshot = ensure_knowledge(database, repository_id, snapshot_id)
    if direction not in {"incoming", "outgoing", "both"} or not 1 <= depth <= 3:
        raise ValueError("Invalid neighborhood direction or depth")
    if evidence_state not in EVIDENCE_STATES:
        raise ValueError("Unsupported evidence state")
    limit = min(500, max(1, int(limit)))
    with closing(database.connect()) as connection:
        connection.execute("BEGIN")
        _node(connection, snapshot, entity_id)
        selected, links, bounded = _walk(
            connection,
            snapshot,
            entity_id,
            depth,
            direction,
            relationship_type,
            limit,
            evidence_state,
        )
        nodes = _neighborhood_nodes(connection, snapshot, selected)
        return _neighborhood_result(
            connection,
            repository_id,
            snapshot,
            nodes,
            links,
            bounded,
            entity_id,
            direction,
            depth,
            evidence_state,
        )


def _neighborhood_nodes(connection, snapshot, selected):
    markers = ",".join("?" for _ in selected)
    rows = connection.execute(
        graph_select()
        + f" WHERE g.snapshot_id=? AND g.entity_id IN ({markers}) ORDER BY g.entity_id",
        (snapshot, *sorted(selected)),
    ).fetchall()
    nodes = [node_value(row) for row in rows]
    present = {node["id"] for node in nodes}
    for identifier in sorted(selected - present):
        if node := unresolved_node(connection, snapshot, identifier) or legacy_node(
            connection, snapshot, identifier
        ):
            nodes.append(node)
    return sorted(nodes, key=lambda node: node["id"])


def _neighborhood_result(
    connection,
    repository,
    snapshot,
    nodes,
    links,
    bounded,
    identifier,
    direction,
    depth,
    evidence_state,
):
    selected = {node["id"] for node in nodes}
    visible = [
        edge
        for edge in links.values()
        if edge["source_id"] in selected and edge["target_id"] in selected
    ]
    return {
        "context": graph_context(connection, repository, snapshot),
        "nodes": nodes,
        "edges": [edge_value(row) for row in visible],
        "returned_nodes": len(nodes),
        "returned_edges": len(visible),
        "total_nodes": None if bounded else len(selected),
        "total_edges": None if bounded else len(visible),
        "known_nodes": len(selected),
        "known_edges": len(links),
        "counts_are_complete": not bounded,
        "bounded": bounded,
        "scope": {
            "entity_id": identifier,
            "direction": direction,
            "depth": depth,
            "evidence_state": evidence_state,
        },
        "next_offset": None,
    }


def _walk(
    connection, snapshot, entity_id, depth, direction, relationship_type, limit, evidence_state
):
    selected, frontier, links = {entity_id}, {entity_id}, {}
    bounded = False
    for level in range(depth):
        rows = _incident(
            connection,
            snapshot,
            sorted(frontier),
            direction,
            relationship_type,
            limit * 3 + 1,
            evidence_state,
        )
        bounded = bounded or len(rows) > limit * 3
        frontier, omitted = _expand(rows[: limit * 3], selected, links, limit)
        bounded = bounded or omitted
        if not frontier or len(selected) >= limit:
            bounded = bounded or bool(frontier and level + 1 < depth)
            break
    return selected, links, bounded


def _expand(rows, selected, links, limit):
    frontier, omitted = set(), False
    for edge in rows:
        links[edge["edge_id"]] = edge
        for key in ("source_id", "target_id"):
            identifier = edge[key]
            if identifier not in selected and len(selected) < limit:
                selected.add(identifier)
                frontier.add(identifier)
            elif identifier not in selected:
                omitted = True
    return frontier, omitted


def _incident(connection, snapshot, ids, direction, relationship_type, limit, evidence_state=""):
    markers = ",".join("?" for _ in ids)
    columns = {
        "incoming": ["target_node"],
        "outgoing": ["source_node"],
        "both": ["source_node", "target_node"],
    }[direction]
    queries, parameters = [], [snapshot, *ids]
    for column in columns:
        index = "graph_links_source" if column == "source_node" else "graph_links_target"
        clause = f"snapshot_id=? AND {column} IN (SELECT node_id FROM selected)"
        parameters.append(snapshot)
        if relationship_type:
            clause += " AND relationship_type=?"
            parameters.append(relationship_type)
        if evidence_state:
            clause += " AND (" + evidence_predicate(edges=True, physical=True) + ")=?"
            parameters.append(evidence_state)
        queries.append(f"SELECT edge_id FROM graph_links INDEXED BY {index} WHERE {clause}")
    sql = (
        f"WITH selected AS (SELECT node_id FROM graph_entities WHERE snapshot_id=? AND entity_id IN ({markers})), matched AS ({' UNION '.join(queries)}) "
        "SELECT * FROM graph_connections WHERE snapshot_id=? AND edge_id IN (SELECT edge_id FROM matched ORDER BY edge_id LIMIT ?) ORDER BY edge_id"
    )
    native = connection.execute(sql, (*parameters, snapshot, limit)).fetchall()
    virtual = legacy_connections(connection, snapshot, ids, direction, relationship_type, limit)
    if relationship_type in {"", "calls"}:
        virtual.extend(unresolved_connections(connection, snapshot, ids, direction))
    virtual = [
        edge
        for edge in virtual
        if not evidence_state or classify_evidence(edge_value(edge)) == evidence_state
    ]
    return sorted([*native, *virtual], key=lambda edge: edge["edge_id"])[:limit]
