"""Revision-scoped grouping projections, kept separate from graph subject and facts."""

import json

from anaxigraph.architecture_vocabulary import architecture_layers
from anaxigraph.knowledge_edges import insert_edge
from anaxigraph.persistence.graph_read import group_parents
from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments


def place_files(connection, snapshot_id, files):
    repository_id = connection.execute(
        "SELECT repository_id FROM snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()[0]
    parents = group_parents(connection, repository_id)
    assignments = taxonomy_assignments(connection, snapshot_id)
    for file in files:
        layers = architecture_layers(
            file.get("declared_group"),
            file.get("inferred_group") or "unassigned",
            parents,
            assignments.get(file["artifact_id"]),
        )
        file["architecture_layers"] = {
            name: {key: placement[key] for key in ("area", "subsystem", "map_layer")}
            if placement
            else None
            for name, placement in layers.items()
        }


def selected_placement(node, layer):
    layers = node.get("properties", {}).get("architecture_layers", {})
    return layers.get(layer) or {
        "area": "unconfigured",
        "subsystem": "unconfigured",
        "map_layer": layer,
    }


def place_area(connection, snapshot, node) -> None:
    parent = node["parent_id"]
    connection.execute(
        """INSERT OR IGNORE INTO graph_entities(snapshot_id,entity_id,kind,label,overview,
        provenance_json) VALUES (?,?,'area',?,?,?)""",
        (
            snapshot,
            parent,
            node["area"],
            "Repository responsibility grouping.",
            json.dumps({"method": "grouping", "verification": "not_a_capability_claim"}),
        ),
    )
    insert_edge(connection, snapshot, parent, node["entity_id"], "contains")


def refresh_grouping(connection, snapshot):
    row = connection.execute(
        "SELECT id,updated_at FROM semantic_taxonomy_values WHERE snapshot_id=? AND status='current' ORDER BY id DESC LIMIT 1",
        (snapshot,),
    ).fetchone()
    revision = json.dumps(list(row) if row else [], separators=(",", ":"))
    key = f"graph-grouping:{snapshot}"
    previous = connection.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
    if previous and previous[0] == revision:
        return
    rows = connection.execute(
        "SELECT * FROM graph_entities WHERE snapshot_id=? AND kind='module'", (snapshot,)
    ).fetchall()
    files = [_placement_source(dict(row)) for row in rows]
    place_files(connection, snapshot, files)
    connection.execute(
        "DELETE FROM graph_entities WHERE snapshot_id=? AND kind='area'", (snapshot,)
    )
    for original, file in zip(rows, files):
        layers = file["architecture_layers"]
        placement = layers["current"]
        properties = json.loads(original["properties_json"])
        properties["architecture_layers"] = layers
        parent = "area:" + placement["area"]
        connection.execute(
            "UPDATE graph_entities SET area=?,subsystem=?,parent_id=?,properties_json=? WHERE node_id=?",
            (
                placement["area"],
                placement["subsystem"],
                parent,
                json.dumps(properties),
                original["node_id"],
            ),
        )
        connection.execute(
            "UPDATE graph_entities SET area=?,subsystem=? WHERE snapshot_id=? AND path=? AND kind IN ('function','interface','type')",
            (placement["area"], placement["subsystem"], snapshot, file["path"]),
        )
        place_area(
            connection,
            snapshot,
            {"parent_id": parent, "area": placement["area"], "entity_id": original["entity_id"]},
        )
    connection.execute(
        "INSERT OR REPLACE INTO schema_meta(key,value) VALUES (?,?)", (key, revision)
    )


def _placement_source(row):
    layers = json.loads(row["properties_json"]).get("architecture_layers", {})
    return {
        "artifact_id": row["artifact_id"],
        "path": row["path"],
        "declared_group": (layers.get("declared") or {}).get("subsystem"),
        "inferred_group": (layers.get("path") or {}).get("subsystem", "unassigned"),
    }
