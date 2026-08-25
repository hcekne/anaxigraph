"""Evidence-bounded requests for autonomous taxonomy proposal and criticism."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.semantic_records import _document_by_id
from anaxigraph.semantic_request_support import compact_dossier


def taxonomy_request(database: Any, job: dict[str, Any]) -> dict[str, Any]:
    with database.connect() as connection:
        inventory, relationship_map = semantic_inventory(connection, int(job["snapshot_id"]))
        documents = _module_documents(connection, job)
        modules = _modules(inventory, documents)
        relationships = _relationships(relationship_map, set(documents))
        previous = _previous_taxonomy(connection, job)
        if job["job_kind"] == "taxonomy_review":
            return _review_request(connection, job, modules, relationships, previous)
    return _proposal_request(job, modules, relationships, previous)


def _module_documents(
    connection: sqlite3.Connection,
    job: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for document_id in job["metadata"].get("document_ids", []):
        document = _document_by_id(connection, int(document_id))
        if document["scope_type"] == "module":
            documents[str(document["scope_key"])] = document
    return documents


def _modules(
    inventory: dict[str, dict[str, Any]],
    documents: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for path, document in sorted(documents.items()):
        module = inventory.get(path) or {}
        result.append(
            {
                "path": path,
                "artifact_id": module.get("artifact_id"),
                "artifact_type": module.get("artifact_type"),
                "language": module.get("language"),
                "lines_of_code": module.get("lines_of_code"),
                "declared_policy_group": module.get("declared_group"),
                "inferred_fallback_group": module.get("inferred_group"),
                "dossier": _taxonomy_dossier(document["value"]),
            }
        )
    return result


def _taxonomy_dossier(value: dict[str, Any]) -> dict[str, Any]:
    compact = compact_dossier(value)
    return {
        key: compact.get(key)
        for key in (
            "summary",
            "responsibilities",
            "public_contracts",
            "architecture_role",
            "domain_concepts",
            "collaborators",
            "overlaps",
            "extension_points",
            "placement_guidance",
            "confidence",
        )
    }


def _relationships(
    relationship_map: dict[str, list[dict[str, Any]]],
    eligible_paths: set[str],
) -> list[dict[str, Any]]:
    result = []
    for source in sorted(eligible_paths):
        for edge in relationship_map.get(source, []):
            target = edge.get("path")
            if edge.get("direction") != "uses" or target not in eligible_paths:
                continue
            result.append(
                {
                    "source": source,
                    "target": target,
                    "type": edge.get("type"),
                    "resolution": edge.get("resolution"),
                }
            )
    return result


def _previous_taxonomy(
    connection: sqlite3.Connection,
    job: dict[str, Any],
) -> dict[str, Any] | None:
    taxonomy_id = job["metadata"].get("previous_taxonomy_id")
    if not taxonomy_id:
        return None
    taxonomy = connection.execute(
        "SELECT * FROM semantic_taxonomies WHERE id = ?", (int(taxonomy_id),)
    ).fetchone()
    if taxonomy is None:
        return None
    nodes = [
        dict(row)
        for row in connection.execute(
            """
            SELECT node_key, name, level, parent_key, description, responsibility, confidence
            FROM semantic_taxonomy_nodes WHERE taxonomy_id = ?
            ORDER BY display_order, node_key
            """,
            (int(taxonomy_id),),
        ).fetchall()
    ]
    memberships = [
        dict(row)
        for row in connection.execute(
            """
            SELECT a.canonical_path AS path, stm.node_key, stm.confidence
            FROM semantic_taxonomy_memberships stm
            JOIN artifacts a ON a.id = stm.artifact_id
            WHERE stm.taxonomy_id = ? ORDER BY a.canonical_path
            """,
            (int(taxonomy_id),),
        ).fetchall()
    ]
    return {
        "snapshot_id": taxonomy["snapshot_id"],
        "confidence": taxonomy["confidence"],
        "nodes": nodes,
        "memberships": memberships,
    }


def _proposal_request(
    job: dict[str, Any],
    modules: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    settings = job["metadata"].get("taxonomy_settings") or {}
    return {
        "contract": (
            "Create a two-level map of what the repository does: broad areas containing smaller "
            "groups of related work. Put every supplied file in exactly one main group. Group "
            "files by the job they share, how they call one another, behavior other code relies "
            "on, and links between tests and source—not by folder names alone. Record work that "
            "cuts across several groups as an extra label instead of placing a file in several "
            "main groups. Use short stable keys and keep an old key when the group's job has not "
            "meaningfully changed. Show uncertainty, but still complete the map."
        ),
        "schema_version": job["schema_version"],
        "analysis_kind": "taxonomy_proposal",
        "scope_type": "repository",
        "scope_key": job["scope_key"],
        "constraints": settings,
        "hints": job["metadata"].get("map_hints", []),
        "locked_memberships": job["metadata"].get("locked_memberships", {}),
        "modules": modules,
        "relationships": relationships,
        "previous_taxonomy": previous,
    }


def _review_request(
    connection: sqlite3.Connection,
    job: dict[str, Any],
    modules: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate = _document_by_id(connection, int(job["metadata"]["candidate_document_id"]))
    candidate_value = candidate["value"]
    if "taxonomy" in candidate_value:
        candidate_value = candidate_value["taxonomy"]
    return {
        "contract": (
            "Independently check and revise the proposed code map, then return the complete "
            "corrected map. Check that every file has one main group, the number of groups stays "
            "within the supplied limits, vague 'other' groups are avoided, and very small or very "
            "large groups have a clear reason. Files in a group should share a real job. Explain "
            "how groups call one another, which tests cover them, where saved data or specially "
            "protected code sits, what supports each choice, and what evidence points elsewhere. "
            "Rewrite labels and explanations that use expert terms without saying what the files "
            "actually do. Keep useful names from the prior map. Complete the check without asking "
            "a person to approve it."
        ),
        "schema_version": job["schema_version"],
        "analysis_kind": "taxonomy_review",
        "scope_type": "repository",
        "scope_key": job["scope_key"],
        "review_pass": int(job["metadata"].get("review_pass", 1)),
        "constraints": job["metadata"].get("taxonomy_settings") or {},
        "deterministic_validation": job["metadata"].get("validation") or {},
        "hints": job["metadata"].get("map_hints", []),
        "locked_memberships": job["metadata"].get("locked_memberships", {}),
        "candidate_taxonomy": candidate_value,
        "modules": modules,
        "relationships": relationships,
        "previous_taxonomy": previous,
    }
