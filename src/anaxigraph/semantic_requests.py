"""Build evidence-bounded provider requests for semantic jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_ports import SemanticConfig, SemanticIndex
from anaxigraph.semantic_records import _document_by_id
from anaxigraph.semantic_request_support import (
    INPUT_TERM_MEANINGS,
    MAPPING_REQUIREMENTS,
    PLAIN_LANGUAGE_CONTRACT_VERSION,
    PLAIN_LANGUAGE_REQUIREMENTS,
    compact_dossier,
)

_REPOSITORY_CHARTER_CONTRACT = (
    "Create the Living Architecture Charter for this repository. Explain its purpose, actors, "
    "observable capabilities, responsibility areas, important execution flows, behavior other "
    "systems rely on, invariants, safe extension points, recurring patterns, and current coherence "
    "concerns. Treat README and documentation statements as claims to compare with code evidence, "
    "not automatic truth; record contradictions and unknowns. Every material statement needs "
    "specific supplied evidence and counter-evidence when present. The embedded Capability Brief "
    "must describe the problem and externally visible behavior for a fresh architect without "
    "leaking current file, package, framework, storage, or internal-boundary names unless one is "
    "itself a public compatibility obligation. Do not propose or approve code changes."
)


class SemanticEvidenceService:
    def __init__(self, database: SemanticIndex) -> None:
        self._database = database

    def job_request(
        self,
        job: dict[str, Any],
        root: Path,
        semantic: SemanticConfig,
    ) -> dict[str, Any]:
        if job["job_kind"] == "annotation":
            from anaxigraph.knowledge_annotation_request import annotation_request

            return annotation_request(self._database, job, root)
        request: dict[str, Any]
        if job["job_kind"] in {"intrinsic", "context"}:
            raise SupersededSemanticJob(
                "The two-description pipeline was replaced by graph annotation; resume Mapping"
            )
        if job["job_kind"] in {"taxonomy_proposal", "taxonomy_review"}:
            from anaxigraph.semantic_taxonomy_requests import taxonomy_request

            request = taxonomy_request(self._database, job, semantic)
        elif job["job_kind"] in {"pattern_assessment", "pattern_review"}:
            from anaxigraph.semantic_pattern_requests import pattern_request

            request = pattern_request(self._database, job, root, semantic)
        elif job["job_kind"] == "architecture_plan":
            from anaxigraph.architecture_plan import plan_request

            request = plan_request(job)
        elif str(job["job_kind"]).startswith("fresh_"):
            from anaxigraph.semantic_fresh_eyes_requests import fresh_eyes_request

            request = fresh_eyes_request(self._database, job)
        else:
            request = self._synthesis_request(job, semantic)
        return _writing_contract(request, job, semantic)

    def _synthesis_request(self, job: dict[str, Any], semantic: SemanticConfig) -> dict[str, Any]:
        with self._database.connect() as connection:
            documents = [
                _document_by_id(connection, int(document_id))
                for document_id in job["metadata"].get("document_ids", [])
            ]
            previous = (
                _document_by_id(connection, int(job["metadata"]["previous_document_id"]))
                if job["metadata"].get("previous_document_id")
                else None
            )
        repository = job["scope_type"] == "repository"
        return {
            "contract": _REPOSITORY_CHARTER_CONTRACT
            if repository
            else (
                "Summarize this responsibility area concisely from its supplied member summaries. "
                "Describe shared functionality and caller obligations with evidence. Preserve "
                "uncertainty; Pattern analysis and Planning own design recommendations."
            ),
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "analysis_kind": "synthesis",
            "scope_type": job["scope_type"],
            "scope_key": job["scope_key"],
            "taxonomy": job["metadata"].get("taxonomy"),
            "child_dossiers": [
                {
                    "scope": item["scope_key"],
                    "kind": item["document_kind"],
                    "confidence": item["confidence"],
                    "value": compact_dossier(item["value"], detailed=False),
                }
                for item in documents
            ],
            "missing_children": job["metadata"].get("missing_members", [])[:100],
            "missing_child_count": len(job["metadata"].get("missing_members", [])),
            "previous_dossier": _previous_value(previous, semantic, repository=repository),
        }


def _previous_value(
    document: dict[str, Any] | None, semantic: SemanticConfig, *, repository: bool = False
) -> dict[str, Any] | None:
    if document is None:
        return None
    return document["value"] if repository else compact_dossier(document["value"])


def _writing_contract(request, job, semantic):
    lean = job["job_kind"] == "synthesis" and job["scope_type"] != "repository"
    request["detailed_reviews"] = semantic.detailed_reviews and not lean
    if semantic.max_output_tokens is not None:
        request["max_output_tokens"] = semantic.max_output_tokens
    request["writing_contract_version"] = PLAIN_LANGUAGE_CONTRACT_VERSION
    request["writing_requirements"] = MAPPING_REQUIREMENTS if lean else PLAIN_LANGUAGE_REQUIREMENTS
    if lean:
        request["contract"] = MAPPING_REQUIREMENTS["purpose"]
    elif not request.get("functional_stage"):
        request["input_term_meanings"] = INPUT_TERM_MEANINGS
    return request
