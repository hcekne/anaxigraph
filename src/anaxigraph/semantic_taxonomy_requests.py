"""Evidence-bounded requests for autonomous taxonomy proposal and criticism."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_records import _document_by_id
from anaxigraph.semantic_request_support import compact_dossier
from anaxigraph.semantic_taxonomy_partition import (
    bounded_relationships,
    chunk_constraints,
    filter_previous,
    filter_taxonomy,
)
from anaxigraph.semantic_taxonomy_runner import review_reconciliation


def taxonomy_request(database: Any, job: dict[str, Any], semantic: Any = None) -> dict[str, Any]:
    with database.connect() as connection:
        inventory, relationship_map = semantic_inventory(connection, int(job["snapshot_id"]))
        documents = _module_documents(connection, job)
        modules = _modules(inventory, documents)
        paths = job["metadata"].get("eligible_paths") or list(documents)
        relationships = _relationships(relationship_map, set(paths))
        previous = _previous_taxonomy(connection, job)
        if job["job_kind"] == "taxonomy_review":
            request = _review_request(connection, job, modules, relationships, previous)
            if job["metadata"].get("review_phase") == "batch":
                return _batch_request(request, job["metadata"], semantic)
            if job["metadata"].get("review_batches"):
                return saved_review_reconciliation(connection, job, request, semantic)[0]
            request["review_phase"] = job["metadata"].get("review_phase")
            return request
    return _proposal_request(job, modules, relationships, previous)


def _batch_request(
    request: dict[str, Any], metadata: dict[str, Any], semantic: Any
) -> dict[str, Any]:
    paths = {item["path"] for item in request["modules"]}
    return {
        **request,
        "analysis_kind": "taxonomy_review_chunk",
        "chunk": {"index": metadata["batch_index"], "total": metadata["batch_total"]},
        "constraints": chunk_constraints(request["constraints"], metadata["batch_total"]),
        "candidate_taxonomy": filter_taxonomy(request["candidate_taxonomy"], paths),
        "relationships": bounded_relationships(
            request["relationships"], paths, semantic.max_source_chars
        ),
        "previous_taxonomy": filter_previous(request["previous_taxonomy"], paths),
        "locked_memberships": {
            path: value for path, value in request["locked_memberships"].items() if path in paths
        },
        "contract": request["contract"]
        + " Review only this independent batch. Its result is saved immediately; a later reconciliation combines all batch findings.",
    }


def saved_review_reconciliation(
    connection: Any, job: dict[str, Any], request: dict[str, Any], semantic: Any
) -> Any:
    by_path = {item["path"]: item for item in request["modules"]}
    batches, results = [], []
    for batch in job["metadata"]["review_batches"]:
        batches.append([by_path[path] for path in batch["paths"]])
        document = _document_by_id(connection, batch["document_id"])
        results.append(SemanticResult(document["value"], document["confidence"], ()))
    return review_reconciliation(request, semantic, batches, results)


def review_plan_inputs(connection: Any, metadata: dict[str, Any]) -> tuple[Any, Any]:
    documents = _module_documents(connection, {"metadata": metadata})
    modules = [
        {
            "path": path,
            "document_id": document["id"],
            "dossier": _taxonomy_dossier(document["value"]),
        }
        for path, document in sorted(documents.items())
    ]
    candidate = _document_by_id(connection, metadata["candidate_document_id"])["value"]
    return modules, candidate


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
    compact = compact_dossier(value, detailed="detailed_summary" in value)
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
        if key in compact
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
            "meaningfully changed. Write every name, description, responsibility, and reason so "
            "a smart twelve-year-old and another coding agent understand it on the first reading. "
            "Describe concrete behavior in the sentence itself; never move unexplained wording to "
            "a technical-details field. Show uncertainty, but still complete the map."
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
            "Rewrite every label, description, responsibility, reason, issue, and recommendation "
            "that a smart twelve-year-old or another coding agent would not understand on the "
            "first reading. State what the files actually do in that same sentence; moving dense "
            "wording to a technical-details field does not fix it. Keep useful names from the "
            "prior map. Complete the check without asking a person to approve it."
        ),
        "schema_version": job["schema_version"],
        "analysis_kind": "taxonomy_review",
        "scope_type": "repository",
        "scope_key": job["scope_key"],
        "review_pass": int(job["metadata"].get("review_pass", 1)),
        "source_changes": job["metadata"].get("source_changes", []),
        "constraints": job["metadata"].get("taxonomy_settings") or {},
        "deterministic_validation": job["metadata"].get("validation") or {},
        "hints": job["metadata"].get("map_hints", []),
        "locked_memberships": job["metadata"].get("locked_memberships", {}),
        "candidate_taxonomy": candidate_value,
        "modules": modules,
        "relationships": relationships,
        "previous_taxonomy": previous,
    }
