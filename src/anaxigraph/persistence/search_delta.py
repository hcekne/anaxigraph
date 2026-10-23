"""Choose search updates by exact source/context and immutable analysis identities."""

from __future__ import annotations

import hashlib
import json

from anaxigraph.persistence.semantic_taxonomy_read import taxonomy_assignments
from anaxigraph.persistence.temporal_hashing import resolver_context_hash
from anaxigraph.persistence.temporal_reads import (
    artifact_types_for_files,
    snapshot_files,
    snapshot_relationship_edges,
)

_SEMANTIC_FIELDS = ("semantic_document_id", "semantic_provider", "semantic_confidence")
_TAXONOMY_FIELDS = ("taxonomy_id", "taxonomy_confidence", "_taxonomy_labels")


def projection_changes(connection, repository, snapshot, previous, selected):
    """Absent scope states may retain only positively unchanged source/context provenance."""
    if not previous.get("snapshot_id"):
        return None
    if selected is not None and previous["snapshot_id"] == snapshot:
        return selected
    existing = {
        row["artifact_id"]: {
            **dict(row),
            "provenance": json.loads(row["provenance"] or "{}"),
        }
        for row in connection.execute(
            "SELECT artifact_id,artifact_type,provenance FROM module_search_rows WHERE repository_id=?",
            (repository,),
        )
    }
    current = source_contexts(connection, snapshot)
    old = (
        current
        if previous["snapshot_id"] == snapshot
        else source_contexts(connection, previous["snapshot_id"])
    )
    states = _semantic_states(connection, snapshot)
    assignments = taxonomy_assignments(connection, snapshot)
    taxonomy = connection.execute(
        "SELECT 1 FROM semantic_taxonomy_values WHERE snapshot_id=? AND status='current' LIMIT 1",
        (snapshot,),
    ).fetchone()
    candidates = set(selected) if selected is not None else set(current) | set(existing)
    return tuple(
        sorted(
            identifier
            for identifier in candidates
            if _needs_update(
                identifier, existing, current, old, states, assignments, bool(taxonomy)
            )
        )
    )


def _needs_update(identifier, existing, current, previous, states, assignments, taxonomy):
    cached = existing.get(identifier)
    if cached is None or current.get(identifier) != previous.get(identifier):
        return True
    if identifier not in current:
        return True
    if cached["artifact_type"] != current[identifier][1]:
        return True
    provenance = cached["provenance"]
    if identifier in states:
        expected = states[identifier]
        if any(provenance.get(key) != expected.get(key) for key in _SEMANTIC_FIELDS):
            return True
    if taxonomy:
        expected = taxonomy_provenance(assignments.get(identifier))
        if any(provenance.get(key) != expected.get(key) for key in _TAXONOMY_FIELDS):
            return True
    return False


def _semantic_states(connection, snapshot):
    rows = connection.execute(
        """SELECT s.artifact_id,s.status,d.id AS document_id,d.provider,d.confidence
        FROM semantic_scope_states s LEFT JOIN semantic_documents d
        ON d.id=COALESCE(s.context_document_id,s.intrinsic_document_id)
        WHERE s.snapshot_id=? AND s.scope_type='module'""",
        (snapshot,),
    )
    return {
        row["artifact_id"]: {
            "semantic_document_id": row["document_id"],
            "semantic_provider": row["provider"],
            "semantic_confidence": row["confidence"],
        }
        if row["status"] in {"current", "intrinsic_current"}
        else {}
        for row in rows
    }


def taxonomy_provenance(assignment):
    assignment = assignment or {}
    return {
        "taxonomy_id": assignment.get("taxonomy_id"),
        "taxonomy_confidence": assignment.get("confidence"),
        "_taxonomy_labels": [assignment.get(key) for key in ("area_name", "subsystem_name")],
    }


def source_contexts(connection, snapshot, *, files=None):
    files = (
        files
        if files is not None
        else {
            item["artifact_id"]: item
            for item in snapshot_files(connection, snapshot, expand_metadata=False)
        }
    )
    types = artifact_types_for_files(connection, list(files.values()))
    hashes = {identifier: _source_hash(item) for identifier, item in files.items()}
    for edge in snapshot_relationship_edges(connection, snapshot):
        source, target = edge["source_artifact_id"], edge["target_artifact_id"]
        value = [
            _endpoint(files.get(source)),
            _endpoint(files.get(target)),
            *[
                edge.get(key)
                for key in (
                    "target_external",
                    "relationship_type",
                    "source",
                    "confidence",
                    "evidence",
                    "source_line",
                    "weight",
                    "metadata_json",
                )
            ],
        ]
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        for identifier in {source, target}:
            if identifier in hashes:
                hashes[identifier].update(encoded)
    return {
        identifier: (value.hexdigest(), types[identifier]) for identifier, value in hashes.items()
    }


def _endpoint(file):
    return [file["path"], file["raw_hash"]] if file else None


def _source_hash(item):
    identity = [
        *[item.get(key) for key in ("path", "raw_hash", "declared_group", "inferred_group")],
        resolver_context_hash(item.get("metadata_json") or "{}"),
    ]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode())
