"""Read functional and proposed graph subjects from immutable saved graph records."""

from __future__ import annotations

import hashlib
import json
from contextlib import closing

from anaxigraph.knowledge_nodes import sentence
from anaxigraph.knowledge_schema import KNOWLEDGE_VERSION
from anaxigraph.knowledge_sync import ensure_knowledge
from anaxigraph.knowledge_values import EVIDENCE_STATES, classify_evidence


def graph_subjects(database, repository_id, snapshot_id=None):
    snapshot = ensure_knowledge(database, repository_id, snapshot_id)
    with closing(database.connect()) as connection:
        definitions = _definitions(connection, repository_id, snapshot)
        revision = connection.execute(
            "SELECT content_fingerprint FROM snapshots WHERE id=?", (snapshot,)
        ).fetchone()[0]
    return {
        "repository_id": repository_id,
        "snapshot_id": snapshot,
        "subjects": [
            {
                "id": "observed",
                "graph_kind": "observed",
                "label": "Observed implementation",
                "snapshot_id": snapshot,
                "revision": revision,
                "entity_kinds": [
                    "capability",
                    "module",
                    "function",
                    "interface",
                    "contract",
                    "unresolved",
                ],
                "default_kind": "module",
            },
            *[
                {
                    key: item[key]
                    for key in (
                        "id",
                        "graph_kind",
                        "label",
                        "revision",
                        "snapshot_id",
                        "entity_kinds",
                        "default_kind",
                    )
                }
                for item in definitions
            ],
        ],
    }


def subject_page(graph, **filters):
    nodes = graph["nodes"]
    state = filters.get("evidence_state", "")
    if state not in EVIDENCE_STATES:
        raise ValueError("Unsupported graph evidence state")
    query = str(filters.get("q", "")).casefold()
    selected = [
        node
        for node in nodes
        if _matches(node, filters, query) and (not state or classify_evidence(node) == state)
    ]
    sort = filters.get("sort", "label")
    field = "overview" if sort in {"overview", "summary"} else "label"
    selected.sort(
        key=lambda node: (str(node[field]), node["id"]), reverse=filters.get("direction") == "desc"
    )
    offset, limit = (
        max(0, int(filters.get("offset", 0))),
        min(1000, max(1, int(filters.get("limit", 100)))),
    )
    page = selected[offset : offset + limit]
    ids = {node["id"] for node in page}
    edges = [
        edge
        for edge in graph["edges"]
        if edge["source"] in ids
        and edge["target"] in ids
        and (not state or classify_evidence(edge) == state)
    ]
    return {
        "context": graph["context"],
        "nodes": [_brief_node(node) for node in page],
        "edges": edges[: limit * 2],
        "total_nodes": len(selected),
        "returned_nodes": len(page),
        "total_edges": len(edges),
        "returned_edges": min(len(edges), limit * 2),
        "next_offset": offset + limit if offset + limit < len(selected) else None,
        "facets": {"areas": [], "subsystems": [], "languages": []},
        "inapplicable_filters": [
            key for key in ("area", "subsystem", "language") if filters.get(key)
        ]
        + (["sort:" + sort] if sort not in {"path", "label", "overview", "summary"} else []),
    }


def subject_detail(graph, identifier):
    node = next((node for node in graph["nodes"] if node["id"] == identifier), None)
    if node is None:
        raise ValueError("Entity does not belong to the selected graph subject")
    incoming = [edge for edge in graph["edges"] if edge["target"] == identifier]
    outgoing = [edge for edge in graph["edges"] if edge["source"] == identifier]
    contracts = {
        edge["target"] for edge in outgoing if edge["relationship_type"] == "requires_contract"
    }
    children = [node for node in graph["nodes"] if node["id"] in contracts]
    return {
        "context": graph["context"],
        "node": node,
        "functions": [],
        "interfaces": [],
        "contracts": children,
        "connections": {"incoming": incoming, "outgoing": outgoing, "tests": []},
        "counts": {
            "children_total": len(children),
            "children_returned": len(children),
            "connections_total": len(incoming) + len(outgoing),
            "connections_returned": len(incoming) + len(outgoing),
            "omitted_children": 0,
            "omitted_connections": 0,
        },
    }


def subject_neighborhood(
    graph,
    identifier,
    *,
    direction="both",
    depth=1,
    limit=100,
    relationship_type="",
    evidence_state="",
):
    subject_detail(graph, identifier)
    if evidence_state not in EVIDENCE_STATES:
        raise ValueError("Unsupported graph evidence state")
    if direction not in {"both", "incoming", "outgoing"} or not 1 <= depth <= 3:
        raise ValueError("Invalid neighborhood direction or depth")
    limit = min(500, max(1, int(limit)))
    eligible_edges = _eligible_edges(graph, relationship_type, evidence_state)
    selected = _reachable(eligible_edges, identifier, direction, depth)
    visible = set(sorted(selected - {identifier})[: limit - 1]) | {identifier}
    nodes = [node for node in graph["nodes"] if node["id"] in visible]
    scoped_edges = [
        edge for edge in eligible_edges if edge["source"] in selected and edge["target"] in selected
    ]
    edges = [
        edge for edge in scoped_edges if edge["source"] in visible and edge["target"] in visible
    ]
    return {
        "context": graph["context"],
        "nodes": [_brief_node(node) for node in nodes],
        "edges": edges,
        "total_nodes": len(selected),
        "returned_nodes": len(nodes),
        "total_edges": len(scoped_edges),
        "returned_edges": len(edges),
        "bounded": len(selected) > len(nodes),
        "counts_are_complete": len(selected) <= len(nodes),
        "next_offset": None,
    }


def _eligible_edges(graph, relationship_type, evidence_state):
    return [
        edge
        for edge in graph["edges"]
        if (not relationship_type or edge["relationship_type"] == relationship_type)
        and (not evidence_state or classify_evidence(edge) == evidence_state)
    ]


def _reachable(eligible_edges, identifier, direction, depth):
    selected, frontier = {identifier}, {identifier}
    for _level in range(depth):
        candidates = [edge for edge in eligible_edges if _incident(edge, frontier, direction, "")]
        added = {edge[side] for edge in candidates for side in ("source", "target")}
        frontier = added - selected
        selected.update(frontier)
    return selected


def _brief_node(node):
    return {key: value for key, value in node.items() if key not in {"detail", "properties"}}


def load_subject(database, repository_id, subject, snapshot_id=None, graph_kind=""):
    snapshot = ensure_knowledge(database, repository_id, snapshot_id)
    with closing(database.connect()) as connection:
        definitions = _definitions(connection, repository_id, snapshot)
        chosen = next((item for item in definitions if item["id"] == subject), None)
        if chosen is None or graph_kind and graph_kind != chosen["graph_kind"]:
            raise ValueError(
                "Graph subject is absent from the selected revision or has another kind"
            )
        checkout = connection.execute(
            "SELECT path FROM repositories WHERE id=?", (repository_id,)
        ).fetchone()[0]
    nodes, edges = _projection(chosen)
    return {
        "context": {
            "repository_id": repository_id,
            "snapshot_id": snapshot,
            "source_snapshot_id": chosen["snapshot_id"],
            "checkout_path": checkout,
            "graph_kind": chosen["graph_kind"],
            "graph_subject": subject,
            "revision": chosen["revision"],
            "contract_version": KNOWLEDGE_VERSION,
            "map_layer": "functional" if chosen["graph_kind"] == "functional_brief" else "proposed",
        },
        "nodes": nodes,
        "edges": edges,
    }


def _definitions(connection, repository, snapshot):
    rows = connection.execute(
        """SELECT d.*,s.interface_hash AS controls FROM semantic_scope_states s
        JOIN semantic_document_values d ON d.id=s.context_document_id
        WHERE s.repository_id=? AND s.snapshot_id=? AND s.status='current'
        AND ((s.scope_type='fresh_eyes' AND (s.scope_key='functional:brief' OR s.scope_key LIKE 'functional:%:proposal:%')) OR s.scope_type='architecture_plan')
        ORDER BY d.id""",
        (repository, snapshot),
    ).fetchall()
    result = []
    for row in rows:
        value = json.loads(row["value_json"])
        if value.get("contract_version") == "functional-brief-v2":
            result.append(
                _definition(row, "functional_brief", "Functional purpose and capabilities", value)
            )
        elif value.get("contract_version") == "functional-proposal-v2":
            label = (
                f"Fresh Eyes · {value['scope_id']} · {row['scope_key'].rsplit(':', 1)[-1].upper()}"
            )
            result.append(_definition(row, "fresh_alternative", label, value["design"]))
        elif row["document_kind"] == "architecture_plan":
            selected = json.loads(row["controls"] or "{}").get("selected_option") or value.get(
                "selected_option"
            )
            for option in value.get("options", []):
                label = f"Planning · {option['title']}" + (
                    " · selected" if option["key"] == selected else ""
                )
                result.append(
                    _definition(row, "planning_target", label, option["target"], option["key"])
                )
    return result


def _definition(row, kind, label, graph, key=""):
    digest = hashlib.sha256(
        json.dumps([kind, row["input_hash"], key], separators=(",", ":")).encode()
    ).hexdigest()[:32]
    return {
        "id": "subject:" + digest,
        "graph_kind": kind,
        "label": label,
        "revision": row["input_hash"],
        "snapshot_id": row["snapshot_id"],
        "entity_kinds": ["capability", "subsystem"]
        if kind == "functional_brief"
        else ["component", "contract"],
        "default_kind": "",
        "graph": graph,
        "provenance": {
            key: row[key]
            for key in ("provider", "model", "executor_id", "executor_model", "created_at")
        },
    }


def _projection(subject):
    graph = subject["graph"]
    if subject["graph_kind"] == "functional_brief":
        return _functional_projection(subject)
    raw_nodes = graph.get("components", graph.get("nodes", []))
    nodes, edges = [], []
    for raw in raw_nodes:
        node = _node(
            subject,
            raw["key"],
            "component",
            raw.get("name", raw.get("label", raw["key"])),
            raw.get("responsibility", ""),
            raw,
        )
        if "paths" in node["properties"]:
            node["properties"]["planned_paths"] = node["properties"].pop("paths")
        nodes.append(node)
        for index, obligation in enumerate(raw.get("contracts", [])):
            contract = _node(
                subject,
                f"{raw['key']}:contract:{index}",
                "contract",
                f"{node['label']} contract {index + 1}",
                obligation,
                {"statement": obligation},
            )
            nodes.append(contract)
            edges.append(_edge(subject, node["id"], contract["id"], "requires_contract", []))
    for raw in graph.get("relationships", graph.get("edges", [])):
        edges.append(
            _edge(
                subject,
                _id(subject, raw["source"]),
                _id(subject, raw["target"]),
                raw.get("relationship", raw.get("label", "interacts_with")),
                raw.get("evidence", [raw.get("rationale", "")]),
            )
        )
    return nodes, edges


def _functional_projection(subject):
    nodes, edges = [], []
    for scope in subject["graph"].get("scopes", []):
        node = _node(
            subject,
            scope["id"],
            "capability" if scope["level"] != "subsystem" else "subsystem",
            scope["id"],
            scope["purpose"],
            scope,
        )
        node["readiness"] = "functional_requirement"
        nodes.append(node)
        if scope["parent_id"]:
            node["parent_id"] = _id(subject, scope["parent_id"])
            edges.append(
                _edge(subject, node["parent_id"], node["id"], "contains_functionality", [])
            )
        for dependency in scope["dependencies"]:
            edges.append(
                _edge(subject, node["id"], _id(subject, dependency), "requires_functionality", [])
            )
    return nodes, edges


def _id(subject, key):
    return subject["id"] + ":" + key


def _node(subject, key, kind, label, description, properties):
    return {
        "id": _id(subject, key),
        "kind": kind,
        "label": label,
        "path": "",
        "parent_id": None,
        "artifact_id": None,
        "overview": sentence(description),
        "detail": description,
        "metrics": {},
        "placement": {"area": subject["label"], "subsystem": ""},
        "language": "",
        "reference": False,
        "readiness": "proposed",
        "properties": dict(properties),
        "provenance": {
            **subject["provenance"],
            "method": "functional_projection"
            if subject["graph_kind"] == "functional_brief"
            else "proposed",
            "verification": "unverified",
            "observed_implementation": False,
        },
    }


def _edge(subject, source, target, relationship, evidence):
    key = hashlib.sha256(json.dumps([source, target, relationship]).encode()).hexdigest()[:24]
    return {
        "id": key,
        "source": source,
        "target": target,
        "relationship_type": relationship,
        "confidence": None,
        "resolution": "functional" if subject["graph_kind"] == "functional_brief" else "proposed",
        "evidence": evidence,
        "provenance": {"method": "proposed", "observed_implementation": False},
    }


def _matches(node, filters, query):
    return (
        (not filters.get("kind") or node["kind"] == filters["kind"])
        and (not query or query in (node["label"] + " " + node["overview"]).casefold())
        and (
            not filters.get("scope")
            or node["parent_id"] == filters["scope"]
            or node["id"] == filters["scope"]
        )
    )


def _incident(edge, frontier, direction, relationship):
    return (not relationship or edge["relationship_type"] == relationship) and (
        (direction != "incoming" and edge["source"] in frontier)
        or (direction != "outgoing" and edge["target"] in frontier)
    )
