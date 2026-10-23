"""Read unresolved call evidence lazily from canonical parser facts, without source access."""

from __future__ import annotations

import hashlib
import json

from anaxigraph.ir_codec import decode_metadata
from anaxigraph.knowledge_nodes import entity_id

_EMPTY_METRICS = dict.fromkeys(
    (
        "lines_of_code",
        "complexity",
        "function_count",
        "interface_count",
        "contract_count",
        "line_coverage",
        "change_count",
        "first_changed_at",
        "last_commit_at",
    )
)


def unresolved_connections(connection, snapshot, ids, direction="both"):
    selected = set(ids)
    result = {}
    for owner, call, position in _records(connection, snapshot, ids, direction):
        source = owner["entity_id"]
        target = entity_id("unresolved", owner["path"], call["target"])
        outgoing = direction != "incoming" and source in selected
        incoming = direction != "outgoing" and target in selected
        if not (outgoing or incoming):
            continue
        key = (source, target)
        edge = result.setdefault(key, _edge(snapshot, source, target))
        evidence = {"path": owner["path"], **call, "call_site_index": position}
        edge["evidence"].append(evidence)
    for edge in result.values():
        edge["evidence_json"] = json.dumps(edge.pop("evidence"))
    return list(result.values())


def unresolved_node(connection, snapshot, identifier, *, detail=False):
    if not identifier.startswith("unresolved:"):
        return None
    records = (
        (owner, call, position)
        for owner, call, position in _records(connection, snapshot, [identifier], "incoming")
        if entity_id("unresolved", owner["path"], call["target"]) == identifier
    )
    group = next(iter(_groups(records).values()), None)
    return _node(identifier, group, detail) if group else None


def all_unresolved_nodes(connection, snapshot):
    return list(iter_unresolved_nodes(connection, snapshot))


def iter_unresolved_nodes(connection, snapshot):
    for identifier, group in _iter_groups(_records(connection, snapshot)):
        yield _node(identifier, group, False)


def unresolved_counts(connection, snapshot, ids=None, direction="both"):
    if ids is not None:
        edges = unresolved_connections(connection, snapshot, ids, direction)
        return {
            "nodes": len({edge["target_id"] for edge in edges}),
            "connections": len(edges),
            "call_sites": sum(len(json.loads(edge["evidence_json"])) for edge in edges),
        }
    totals = {"nodes": 0, "connections": 0, "call_sites": 0}
    for _identifier, group in _iter_groups(_records(connection, snapshot)):
        totals["nodes"] += 1
        totals["connections"] += group["callers"]
        totals["call_sites"] += group["call_sites"]
    return totals


def _owners(connection, snapshot, ids, direction):
    if direction not in {"incoming", "outgoing", "both"}:
        raise ValueError("Invalid unresolved-call direction")
    where = "g.snapshot_id=? AND json_extract(g.properties_json,'$.unresolved_call_count')>0"
    parameters = [snapshot]
    if ids is not None:
        sources = list(ids) if direction != "incoming" else []
        paths = [
            item.removeprefix("unresolved:").partition("#")[0]
            for item in ids
            if direction != "outgoing" and item.startswith("unresolved:")
        ]
        if not (sources or paths):
            return []
        where += " AND (g.entity_id IN (SELECT value FROM json_each(?)) OR g.path IN (SELECT value FROM json_each(?)))"
        parameters.extend((json.dumps(sources), json.dumps(paths)))
    return connection.execute(
        "SELECT g.entity_id,g.path,g.artifact_id,g.file_fact_id,g.properties_json,g.area,g.subsystem,"
        "g.language,g.reference,m.properties_json AS module_properties FROM graph_entities g "
        "JOIN graph_entities m ON m.snapshot_id=g.snapshot_id AND m.entity_id='module:'||g.path "
        "WHERE " + where + " ORDER BY g.file_fact_id,g.entity_id",
        parameters,
    )


def _records(connection, snapshot, ids=None, direction="both"):
    fact_id, calls = None, []
    for row in _owners(connection, snapshot, ids, direction):
        owner = dict(row)
        if owner["file_fact_id"] != fact_id:
            fact_id = owner["file_fact_id"]
            fact = connection.execute(
                "SELECT metadata_json FROM file_facts WHERE id=?", (fact_id,)
            ).fetchone()
            if fact is None:
                raise ValueError("Unresolved call references a missing canonical source fact")
            calls = decode_metadata(fact[0] or "{}").get("call_sites", [])
        for position in json.loads(owner["properties_json"])["unresolved_call_sites"]:
            if (
                not isinstance(position, int)
                or isinstance(position, bool)
                or not 0 <= position < len(calls)
            ):
                raise ValueError("Unresolved call index does not match its canonical source fact")
            yield owner, calls[position], position


def _groups(records):
    groups = {}
    for owner, call, _position in records:
        _add_group(groups, owner, call)
    return groups


def _iter_groups(records):
    fact, groups = None, {}
    for owner, call, _position in records:
        if fact != owner["file_fact_id"]:
            yield from groups.items()
            fact, groups = owner["file_fact_id"], {}
        _add_group(groups, owner, call)
    yield from groups.items()


def _add_group(groups, owner, call):
    identifier = entity_id("unresolved", owner["path"], call["target"])
    group = groups.setdefault(
        identifier,
        {
            "owner": owner,
            "target": call["target"],
            "line": call["line"],
            "call_sites": 0,
            "callers": 0,
            "last_owner": None,
        },
    )
    group["call_sites"] += 1
    if group["last_owner"] != owner["entity_id"]:
        group["callers"] += 1
        group["last_owner"] = owner["entity_id"]


def _node(identifier, group, detail):
    owner = group["owner"]
    result = {
        "id": identifier,
        "kind": "unresolved",
        "label": group["target"],
        "path": owner["path"],
        "parent_id": entity_id("module", owner["path"]),
        "artifact_id": owner["artifact_id"],
        "overview": "Target not statically resolved.",
        "readiness": "structural",
        "language": owner["language"],
        "reference": bool(owner["reference"]),
        "placement": {"area": owner["area"], "subsystem": owner["subsystem"]},
        "architecture_layers": json.loads(owner["module_properties"]).get(
            "architecture_layers", {}
        ),
        "provenance": {"method": "extracted", "verification": "unresolved"},
        "properties": {
            "resolution": "unresolved",
            "line": group["line"],
            "call_site_count": group["call_sites"],
            "caller_count": group["callers"],
        },
        "metrics": {**_EMPTY_METRICS, "fan_in": group["callers"], "fan_out": 0},
    }
    if detail:
        result["detail"] = (
            "A static link was not established; this is not evidence that code is unused."
        )
    return result


def _edge(snapshot, source, target):
    identity = json.dumps([source, target, "calls"], separators=(",", ":"))
    return {
        "snapshot_id": snapshot,
        "edge_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
        "source_id": source,
        "target_id": target,
        "relationship_type": "calls",
        "confidence": 0.0,
        "resolution": "unresolved",
        "provenance_json": '{"method":"extracted"}',
        "evidence": [],
    }
