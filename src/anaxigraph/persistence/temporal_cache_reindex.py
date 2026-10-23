"""Reuse current deterministic facts for identical historical source, preserving paid rows."""

from __future__ import annotations

import json

from anaxigraph.ir_codec import decode_metadata, encode_metadata
from anaxigraph.persistence.temporal_cache_merge import merge_current_fact_identities
from anaxigraph.persistence.temporal_hashing import resolver_context_hash
from anaxigraph.persistence.temporal_reconstruction import (
    _insert_checkpoint,
    reconstruct_files,
    reconstruct_relationships,
)
from anaxigraph.persistence.temporal_relationships import _edges_by_value


def reindex_identical_source(connection, repository_id, current_snapshot_id, *, detailed=False):
    if (
        detailed
        or connection.execute(
            "SELECT 1 FROM schema_meta WHERE key=?", (f"history-opt-in:{repository_id}",)
        ).fetchone()
    ):
        return {"reindexed_snapshots": 0, "evicted_facts": 0}
    current = reconstruct_files(connection, current_snapshot_id)
    facts = _facts(connection, current)
    aliases = _aliases(current, facts)
    if not aliases:
        return {"reindexed_snapshots": 0, "evicted_facts": 0}
    current_relations = reconstruct_relationships(connection, current_snapshot_id)
    frames = _frames(connection, repository_id, current_snapshot_id)
    coverage = {}
    for row in connection.execute(
        "SELECT id,relationship_edge_id FROM coverage_measurements WHERE relationship_edge_id IS NOT NULL"
    ):
        coverage.setdefault(row["relationship_edge_id"], []).append(row["id"])
    changed = 0
    for snapshot, files, relations in frames:
        if _reindex_frame(
            connection, snapshot, files, relations, current, aliases, current_relations, coverage
        ):
            changed += 1
    evicted = _evict_unused_facts(connection, aliases, facts)
    merged = merge_current_fact_identities(connection, aliases, facts)
    _collect_relationships(connection, repository_id)
    return {"reindexed_snapshots": changed, "evicted_facts": evicted, "merged_identities": merged}


def _facts(connection, current):
    ids = json.dumps(list(current))
    return {
        int(row["id"]): dict(row)
        for row in connection.execute(
            "SELECT * FROM file_facts WHERE artifact_id IN (SELECT value FROM json_each(?))", (ids,)
        )
    }


def _aliases(current, facts):
    aliases = {}
    for old in facts.values():
        file = current.get(old["artifact_id"])
        new = facts[file["file_fact_id"]] if file else None
        if not new or old["id"] == new["id"] or old["raw_hash"] != new["raw_hash"]:
            continue
        if old["analysis_signature"] == new["analysis_signature"]:
            continue
        metadata = decode_metadata(old["metadata_json"])
        if metadata.get("structural_cache_reindex", {}).get("effective_file_fact_id") == new["id"]:
            continue
        if resolver_context_hash(old["metadata_json"]) != resolver_context_hash(
            new["metadata_json"]
        ):
            continue
        aliases[old["id"]] = (new["id"], file["path"], new["analysis_signature"])
    return aliases


def _frames(connection, repository_id, current_snapshot_id):
    frames = []
    for row in connection.execute(
        "SELECT * FROM snapshots WHERE repository_id=? AND id!=? AND snapshot_kind!='portable_analysis'",
        (repository_id, current_snapshot_id),
    ).fetchall():
        if json.loads(row["metadata_json"] or "{}").get("structural_analysis") == "as_recorded":
            _pin_frame(connection, row)
            continue
        frames.append(
            (
                dict(row),
                reconstruct_files(connection, row["id"]),
                reconstruct_relationships(connection, row["id"]),
            )
        )
    return frames


def _pin_frame(connection, snapshot):
    files = reconstruct_files(connection, snapshot["id"])
    relations = reconstruct_relationships(connection, snapshot["id"])
    connection.execute("DELETE FROM snapshot_checkpoints WHERE snapshot_id=?", (snapshot["id"],))
    _insert_checkpoint(
        connection,
        snapshot["id"],
        snapshot["repository_id"],
        snapshot["sequence"],
        0,
        files,
        relations,
    )


def _reindex_frame(
    connection, snapshot, files, relations, current, aliases, current_relations, coverage
):
    replaced = {
        artifact: aliases[file["file_fact_id"]]
        for artifact, file in files.items()
        if file["file_fact_id"] in aliases and aliases[file["file_fact_id"]][1] == file["path"]
    }
    if not replaced:
        return False
    same_source = _same_source(files, current, connection)
    for artifact, (fact, _path, _signature) in replaced.items():
        files[artifact] = {**files[artifact], "file_fact_id": fact}
        old, new = relations.get(artifact), current_relations.get(artifact)
        if same_source or _same_edges(connection, old, new):
            _remap_coverage(connection, old, new, coverage)
            if new is None:
                relations.pop(artifact, None)
            else:
                relations[artifact] = new
    for table in ("snapshot_checkpoints", "snapshot_file_changes", "snapshot_relationship_changes"):
        connection.execute(f"DELETE FROM {table} WHERE snapshot_id=?", (snapshot["id"],))
    _insert_checkpoint(
        connection,
        snapshot["id"],
        snapshot["repository_id"],
        snapshot["sequence"],
        0,
        files,
        relations,
    )
    _record_contract(connection, snapshot, replaced)
    connection.execute("DELETE FROM graph_revisions WHERE snapshot_id=?", (snapshot["id"],))
    return True


def _same_source(files, current, connection):
    if {file["path"] for file in files.values()} != {file["path"] for file in current.values()}:
        return False
    ids = {file["file_fact_id"] for file in (*files.values(), *current.values())}
    hashes = dict(
        connection.execute(
            "SELECT id,raw_hash FROM file_facts WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(ids)),),
        )
    )
    return all(
        artifact in current
        and hashes[file["file_fact_id"]] == hashes[current[artifact]["file_fact_id"]]
        for artifact, file in files.items()
    )


def _same_edges(connection, old, new):
    if old is None or new is None:
        return old == new
    return _edges_by_value(connection, old).keys() == _edges_by_value(connection, new).keys()


def _remap_coverage(connection, old, new, coverage):
    if old is None or new is None:
        return
    original = _edges_by_value(connection, old)
    if not any(identifier in coverage for identifier in original.values()):
        return
    effective = _edges_by_value(connection, new)
    updates = [
        (effective[value], measurement)
        for value, identifier in original.items()
        if value in effective
        for measurement in coverage.get(identifier, ())
    ]
    connection.executemany(
        "UPDATE coverage_measurements SET relationship_edge_id=? WHERE id=?", updates
    )


def _record_contract(connection, snapshot, replaced):
    metadata = json.loads(snapshot["metadata_json"] or "{}")
    metadata["structural_cache_reindex"] = {
        "original_analysis_signature": metadata.get("analysis_signature"),
        "effective_analysis_signatures": sorted({value[2] for value in replaced.values()}),
        "rule": "same_path_raw_hash_and_resolver_context",
        "reindexed_files": len(replaced),
        "interpretation": "Current deterministic extraction; original paid analyses and recorded snapshot provenance retained",
    }
    connection.execute(
        "UPDATE snapshots SET metadata_json=? WHERE id=?", (json.dumps(metadata), snapshot["id"])
    )


def _evict_unused_facts(connection, aliases, facts):
    retained = {
        row[0]
        for row in connection.execute(
            "SELECT file_fact_id FROM snapshot_file_changes WHERE file_fact_id IS NOT NULL UNION SELECT file_fact_id FROM checkpoint_files"
        )
    }
    evicted = 0
    for identifier, (effective, _path, contract) in aliases.items():
        if identifier in retained:
            continue
        original = decode_metadata(facts[identifier]["metadata_json"])
        ir = original.get("ir") or {}
        metadata = {
            "analysis_version": original.get("analysis_version"),
            "ir": {
                key: ir[key]
                for key in ("schema_version", "analyzer_version", "parse_status")
                if key in ir
            },
            "original_parser_capability_fingerprint": (ir.get("analyzer_capabilities") or {}).get(
                "fingerprint"
            ),
            "structural_cache_reindex": {
                "effective_file_fact_id": effective,
                "effective_analysis_signature": contract,
                "state": "rebuildable_cache_evicted",
            },
        }
        connection.execute("DELETE FROM fact_symbols WHERE file_fact_id=?", (identifier,))
        connection.execute(
            "UPDATE file_facts SET summary='',responsibilities_json='[]',inputs_json='[]',outputs_json='[]',side_effects_json='[]',public_interfaces_json='[]',metadata_json=? WHERE id=?",
            (encode_metadata(metadata), identifier),
        )
        evicted += 1
    return evicted


def _collect_relationships(connection, repository_id):
    connection.execute(
        """DELETE FROM relationship_sets WHERE repository_id=?
        AND id NOT IN (SELECT relationship_set_id FROM snapshot_relationship_changes WHERE relationship_set_id IS NOT NULL
        UNION SELECT relationship_set_id FROM checkpoint_relationships)
        AND id NOT IN (SELECT e.relationship_set_id FROM relationship_edges e JOIN coverage_measurements c ON c.relationship_edge_id=e.id)""",
        (repository_id,),
    )
