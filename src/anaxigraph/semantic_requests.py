"""Build evidence-bounded provider requests for semantic jobs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.persistence.semantic_evidence import module_facts, relationships_for_artifact
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_records import _document_by_id
from anaxigraph.semantic_request_support import compact_dossier


class SemanticEvidenceService:
    def __init__(self, database: SemanticIndex) -> None:
        self._database = database

    def job_request(
        self,
        job: dict[str, Any],
        root: Path,
        semantic: SemanticConfig,
    ) -> dict[str, Any]:
        if job["job_kind"] == "intrinsic":
            return self._intrinsic_request(job, root)
        if job["job_kind"] == "context":
            return self._context_request(job, semantic)
        if job["job_kind"] in {"taxonomy_proposal", "taxonomy_review"}:
            from anaxigraph.semantic_taxonomy_requests import taxonomy_request

            return taxonomy_request(self._database, job)
        if job["job_kind"] in {"pattern_assessment", "pattern_review"}:
            from anaxigraph.semantic_pattern_requests import pattern_request

            return pattern_request(self._database, job, root, semantic)
        return self._synthesis_request(job)

    def _intrinsic_request(self, job: dict[str, Any], root: Path) -> dict[str, Any]:
        path = str(job["scope_key"])
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
            raise SupersededSemanticJob("The target module no longer exists in the mounted tree")
        raw_content = candidate.read_bytes()
        raw_hash = hashlib.sha256(raw_content).hexdigest()
        content = raw_content.decode("utf-8", errors="replace")
        with self._database.connect() as connection:
            version, symbols = module_facts(
                connection,
                int(job["snapshot_id"]),
                int(job["artifact_id"]),
            )
            if version is None or version["raw_hash"] != raw_hash:
                raise SupersededSemanticJob(
                    "The module changed after this semantic job was planned"
                )
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
                "Describe this module's intrinsic meaning. Ground claims in supplied source, "
                "symbols, and deterministic relationships. Describe contracts and extension "
                "seams, but leave cross-module pattern, consolidation, placement, and deletion "
                "judgments empty until the contextual pass."
            ),
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "analysis_kind": "intrinsic",
            "path": path,
            "language": version["language"],
            "deterministic_facts": {
                "deterministic_summary": version["summary"],
                "declared_group": version["declared_group"],
                "inferred_group": version["inferred_group"],
                "lines_of_code": version["lines_of_code"],
                "complexity": version["complexity"],
                "public_interfaces": json.loads(version["public_interfaces_json"] or "[]"),
                "symbols": symbols[:250],
                "relationships": relations[:250],
                "recent_changes": history,
            },
            "source": content,
            "previous_dossier": previous["value"] if previous else None,
        }

    def _context_request(self, job: dict[str, Any], semantic: SemanticConfig) -> dict[str, Any]:
        with self._database.connect() as connection:
            intrinsic = _document_by_id(connection, int(job["metadata"]["intrinsic_document_id"]))
            relations = relationships_for_artifact(
                connection, int(job["snapshot_id"]), int(job["artifact_id"])
            )
            neighbors = []
            for path in job["metadata"].get("neighbors", [])[: semantic.max_context_modules]:
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
                    neighbors.append(
                        {
                            "path": path,
                            "confidence": document["confidence"],
                            "dossier": compact_dossier(document["value"]),
                        }
                    )
            previous = (
                _document_by_id(connection, int(job["metadata"]["previous_document_id"]))
                if job["metadata"].get("previous_document_id")
                else None
            )
        return {
            "contract": (
                "Explain this module's architectural role and how it collaborates, overlaps, or "
                "acts as an extension point. Identify similar modules, locally appropriate design "
                "patterns, consolidation or split opportunities, and where adjacent functionality "
                "should be placed. Score pattern fit from 0 to 100 using local precedent, expected "
                "benefit, coupling, change cost, and counter-evidence; reserve scores above 80 for "
                "strong repository-specific evidence. The consolidation score represents the "
                "strength of its recommendation, not generic code quality. List a dead-code "
                "candidate only when supplied reachability "
                "evidence supports it, and state uncertainty in the candidate text. Use only "
                "supplied dossiers and graph evidence; absence of a static edge is not proof of "
                "runtime unreachability."
            ),
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "analysis_kind": "context",
            "path": job["scope_key"],
            "intrinsic_dossier": intrinsic["value"],
            "relationships": relations,
            "neighbor_dossiers": neighbors,
            "previous_dossier": previous["value"] if previous else None,
        }

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
        return {
            "contract": (
                "Synthesize the supplied child dossiers into a coherent architectural description "
                "of this scope. Preserve important differences, identify shared responsibilities, "
                "and summarize evidence-backed patterns, consolidation opportunities, placement "
                "guidance, and counter-evidence without turning uncertainty into fact. Pattern "
                "scores must reflect local fit and migration cost, not textbook popularity."
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
