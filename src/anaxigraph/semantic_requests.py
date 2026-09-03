"""Build evidence-bounded provider requests for semantic jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.persistence.semantic_evidence import module_facts, relationships_for_artifact
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_records import _document_by_id
from anaxigraph.semantic_request_support import (
    INPUT_TERM_MEANINGS,
    PLAIN_LANGUAGE_CONTRACT_VERSION,
    PLAIN_LANGUAGE_REQUIREMENTS,
    compact_dossier,
)
from anaxigraph.semantic_target_source import read_mounted_source, require_unchanged_source

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
_TARGET_MISSING = "The target module no longer exists in the mounted tree"
_TARGET_CHANGED = "The module changed after this semantic job was planned"


class SemanticEvidenceService:
    def __init__(self, database: SemanticIndex) -> None:
        self._database = database

    def job_request(
        self,
        job: dict[str, Any],
        root: Path,
        semantic: SemanticConfig,
    ) -> dict[str, Any]:
        request: dict[str, Any]
        if job["job_kind"] == "intrinsic":
            request = self._intrinsic_request(job, root)
        elif job["job_kind"] == "context":
            request = self._context_request(job, semantic)
        elif job["job_kind"] in {"taxonomy_proposal", "taxonomy_review"}:
            from anaxigraph.semantic_taxonomy_requests import taxonomy_request

            request = taxonomy_request(self._database, job)
        elif job["job_kind"] in {"pattern_assessment", "pattern_review"}:
            from anaxigraph.semantic_pattern_requests import pattern_request

            request = pattern_request(self._database, job, root, semantic)
        elif str(job["job_kind"]).startswith("fresh_"):
            from anaxigraph.semantic_fresh_eyes_requests import fresh_eyes_request

            request = fresh_eyes_request(self._database, job)
        else:
            request = self._synthesis_request(job)
        request["writing_contract_version"] = PLAIN_LANGUAGE_CONTRACT_VERSION
        request["writing_requirements"] = PLAIN_LANGUAGE_REQUIREMENTS
        request["input_term_meanings"] = INPUT_TERM_MEANINGS
        return request

    def _intrinsic_request(self, job: dict[str, Any], root: Path) -> dict[str, Any]:
        path = str(job["scope_key"])
        raw_content = read_mounted_source(root, path, missing=_TARGET_MISSING)
        content = raw_content.decode("utf-8", errors="replace")
        with self._database.connect() as connection:
            version, symbols = module_facts(
                connection,
                int(job["snapshot_id"]),
                int(job["artifact_id"]),
            )
            require_unchanged_source(raw_content, version, changed=_TARGET_CHANGED)
            relations = relationships_for_artifact(
                connection, int(job["snapshot_id"]), int(job["artifact_id"])
            )
            history = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT commit_sha, committed_at, subject, change_type, additions, deletions
                    FROM git_changes WHERE repository_id = ? AND path = ?
                    ORDER BY committed_at DESC LIMIT 8
                    """,
                    (job["repository_id"], path),
                ).fetchall()
            ]
            previous = (
                _document_by_id(connection, int(job["metadata"]["previous_document_id"]))
                if job["metadata"].get("previous_document_id")
                else None
            )
        return {
            "contract": (
                "Describe what this file does using only its supplied source, named code parts, "
                "and direct links to other files. Explain behavior callers rely on and places "
                "intentionally designed for adding behavior. Leave repository-wide pattern, "
                "combine-or-separate, placement, and deletion judgments empty until the next pass."
            ),
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "analysis_kind": "intrinsic",
            "path": path,
            "language": version["language"],
            "deterministic_facts": _intrinsic_facts(version, symbols, relations, history),
            "source": content,
            "previous_dossier": previous["value"] if previous else None,
        }

    def _context_request(self, job: dict[str, Any], semantic: SemanticConfig) -> dict[str, Any]:
        with self._database.connect() as connection:
            intrinsic = _document_by_id(connection, int(job["metadata"]["intrinsic_document_id"]))
            relations = relationships_for_artifact(
                connection, int(job["snapshot_id"]), int(job["artifact_id"])
            )
            neighbors = self._neighbor_dossiers(connection, job, semantic)
            previous = (
                _document_by_id(connection, int(job["metadata"]["previous_document_id"]))
                if job["metadata"].get("previous_document_id")
                else None
            )
        return {
            "contract": (
                "Explain this file's job in the repository, which files it works with, and where "
                "work is duplicated. Identify similar files, patterns that fit this repository, "
                "possible combinations or splits, and where nearby behavior should be added. "
                "Score pattern fit from 0 to 100 using examples already in this repository, likely "
                "benefit, direct code links, change cost, and evidence against the idea. Use scores "
                "above 80 only when the repository itself gives strong support. A combine-or-split "
                "score says how strongly the evidence supports that advice; it is not a code-quality "
                "grade. Say code may be unused only when the supplied link evidence supports that "
                "possibility, and state what may make the conclusion wrong. A missing source-code "
                "link does not prove that running code never reaches it."
            ),
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "analysis_kind": "context",
            "path": job["scope_key"],
            "intrinsic_dossier": intrinsic["value"],
            "relationships": relations,
            "neighbor_dossiers": neighbors,
            "previous_dossier": previous["value"] if previous else None,
        }

    def _neighbor_dossiers(
        self, connection: Any, job: dict[str, Any], semantic: SemanticConfig
    ) -> list[dict[str, Any]]:
        result = []
        paths = job["metadata"].get("neighbors", [])[: semantic.max_context_modules]
        for path in paths:
            state = connection.execute(
                """
                SELECT * FROM semantic_scope_states
                WHERE snapshot_id = ? AND scope_type = 'module' AND scope_key = ?
                """,
                (job["snapshot_id"], path),
            ).fetchone()
            if state is None:
                continue
            document_id = state["context_document_id"] or state["intrinsic_document_id"]
            if document_id:
                document = _document_by_id(connection, int(document_id))
                result.append(
                    {
                        "path": path,
                        "confidence": document["confidence"],
                        "dossier": compact_dossier(document["value"]),
                    }
                )
        return result

    def _synthesis_request(self, job: dict[str, Any]) -> dict[str, Any]:
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
                "Combine the supplied descriptions into one clear explanation of this repository "
                "area. Keep important differences between files, identify work they share, and "
                "summarize supported pattern ideas, combine-or-separate advice, and where new work "
                "belongs. Include evidence against each idea and do not state uncertainty as fact. "
                "Pattern scores must reflect fit in this repository and the cost of changing it, "
                "not how popular a pattern is in textbooks."
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
                    "value": compact_dossier(item["value"]),
                }
                for item in documents
            ],
            "missing_children": job["metadata"].get("missing_members", [])[:100],
            "missing_child_count": len(job["metadata"].get("missing_members", [])),
            "previous_dossier": previous["value"] if previous else None,
        }


def _intrinsic_facts(
    version: dict[str, Any],
    symbols: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = json.loads(version.get("metadata_json") or "{}")
    ir = metadata.get("ir") or {}
    return {
        "deterministic_summary": version["summary"],
        "declared_group": version["declared_group"],
        "inferred_group": version["inferred_group"],
        "lines_of_code": version["lines_of_code"],
        "complexity": version["complexity"],
        "analysis_contract": {
            "analyzer": version["analyzer"],
            "analyzer_version": ir.get("analyzer_version"),
            "parse_status": ir.get("parse_status"),
            "capabilities": ir.get("analyzer_capabilities"),
            "parse_diagnostics": metadata.get("parse_diagnostics", []),
        },
        "public_interfaces": json.loads(version["public_interfaces_json"] or "[]"),
        "symbols": symbols[:250],
        "evidence_facts": (ir.get("evidence_facts") or [])[:250],
        "relationships": relations[:250],
        "recent_changes": history,
    }
