"""Build exact evidence packets for the fixed fresh-eyes review stages."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_fresh_eyes_contract import (
    FRESH_EYES_PROTOCOL_VERSION,
    semantic_input_hash,
)
from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_index_port import SemanticIndex

_CONTRACTS = {
    "fresh_proposal": (
        "Design a clean-sheet software architecture that delivers the supplied behavior and "
        "constraints. You have deliberately not been shown the existing implementation. Define "
        "the smallest useful responsibilities, boundaries, information flows, extension strategy, "
        "operating model, and justified patterns. Explain trade-offs and avoid infrastructure the "
        "stated scale does not need. Cite capability or constraint evidence, not repository paths."
    ),
    "fresh_adjudication": (
        "Blindly adjudicate the independent clean-sheet proposals using only the same Capability "
        "Brief. Preserve meaningful disagreement, identify shared assumptions and likely common "
        "blind spots, and synthesize the strongest compatible reference design. Agreement is not "
        "proof. Do not infer or discuss the current repository implementation."
    ),
    "fresh_comparison": (
        "Compare the blind reference design with the supplied current system. Search as carefully "
        "for existing strengths and justified differences as for weaknesses. Map responsibilities, "
        "classify every material difference using the allowed result labels, and do not treat an "
        "idea's absence from the clean-sheet design as evidence that current code should be deleted."
    ),
    "fresh_review": (
        "Filter the comparison into a small ranked refactor strategy. Keep only changes that "
        "materially advance the mission after accounting for user value, coherence, expected code "
        "reduction, operational simplicity, compatibility, migration risk, reversibility, and "
        "verification cost. Reject attractive overengineering. This is advice, not permission to "
        "edit code, and retaining the current design is valid when evidence supports it."
    ),
}
_INPUT_CONTRACTS = {
    "fresh_proposal": "fresh-eyes-proposal-v1",
    "fresh_adjudication": "fresh-eyes-adjudication-v1",
    "fresh_comparison": "fresh-eyes-comparison-v1",
    "fresh_review": "fresh-eyes-review-v1",
}


def fresh_eyes_request(
    database: SemanticIndex,
    job: dict[str, Any],
) -> dict[str, Any]:
    kind = str(job["job_kind"])
    if kind not in _CONTRACTS:
        raise ValueError(f"unsupported fresh-eyes job kind: {kind}")
    metadata = job["metadata"]
    _validate_manifest(job, metadata)
    request = {
        "contract": _CONTRACTS[kind],
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "protocol_version": FRESH_EYES_PROTOCOL_VERSION,
        "analysis_kind": kind,
        "input_manifest": metadata["input_manifest"],
        "information_boundary": metadata["information_boundary"],
    }
    request.update(_stage_evidence(database, kind, metadata))
    return request


def _stage_evidence(
    database: SemanticIndex,
    kind: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if kind == "fresh_proposal":
        return _proposal_evidence(metadata)
    if kind == "fresh_adjudication":
        return _adjudication_evidence(database, metadata)
    if kind == "fresh_comparison":
        adjudication = _document(database, metadata["adjudication_document_id"])
        return {
            "capability_brief": metadata["capability_brief"],
            "reference_design": adjudication["value"]["reference_design"],
            "current_system": metadata["current_system"],
        }
    comparison = _document(database, metadata["comparison_document_id"])
    return {
        "capability_brief": metadata["capability_brief"],
        "comparison": comparison["value"],
        "engineering_economics": {
            "prefer": [
                "small coherent changes",
                "deleting or consolidating code when behavior is preserved",
                "reversible steps with explicit verification",
                "retaining good existing decisions",
            ],
            "reject": [
                "speculative infrastructure",
                "rewrites without capability benefit",
                "new abstractions whose migration cost exceeds likely value",
            ],
        },
    }


def _proposal_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_slot": metadata["slot"],
        "capability_brief": metadata["capability_brief"],
        "external_constraints": metadata["external_constraints"],
        "isolation_request": {
            "mode": "fresh_context",
            "instruction": (
                "Use a fresh subagent or session when the host supports it; otherwise report "
                "isolation as unverified."
            ),
        },
    }


def _adjudication_evidence(database: SemanticIndex, metadata: dict[str, Any]) -> dict[str, Any]:
    proposals = _documents(database, metadata["proposal_document_ids"])
    return {
        "capability_brief": metadata["capability_brief"],
        "proposals": [
            {
                "proposal": item["scope_key"],
                "value": item["value"],
                "reviewer": _reviewer(item),
            }
            for item in proposals
        ],
        "diversity": proposal_diversity(proposals),
    }


def _documents(database: SemanticIndex, document_ids: list[int]) -> list[dict[str, Any]]:
    with database.connect() as connection:
        return [_read_document(connection, int(document_id)) for document_id in document_ids]


def _document(database: SemanticIndex, document_id: int) -> dict[str, Any]:
    with database.connect() as connection:
        return _read_document(connection, int(document_id))


def _read_document(connection: Any, document_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM semantic_documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise SupersededSemanticJob(f"Fresh-eyes document {document_id} no longer exists")
    document = dict(row)
    document["value"] = json.loads(document.get("value_json") or "{}")
    return document


def _reviewer(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": document.get("provider"),
        "model": document.get("model"),
        "executor_id": document.get("executor_id"),
        "executor_model": document.get("executor_model"),
    }


def _validate_manifest(job: dict[str, Any], metadata: dict[str, Any]) -> None:
    manifest = metadata.get("input_manifest")
    if not isinstance(manifest, dict):
        raise SupersededSemanticJob("Fresh-eyes work no longer has its exact input manifest")
    expected = semantic_input_hash(
        _INPUT_CONTRACTS[str(job["job_kind"])],
        str(job["prompt_version"]),
        manifest,
    )
    if expected != str(job["input_hash"]):
        raise SupersededSemanticJob("Fresh-eyes input manifest no longer matches its planned job")
