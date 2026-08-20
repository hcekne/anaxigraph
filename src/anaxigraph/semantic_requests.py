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
from anaxigraph.semantic_records import _document_by_id


class SemanticRequestMixin:
    def _job_request(
        self,
        job: dict[str, Any],
        root: Path,
        semantic: SemanticConfig,
    ) -> dict[str, Any]:
        if job["job_kind"] == "intrinsic":
            return self._intrinsic_request(job, root)
        if job["job_kind"] == "context":
            return self._context_request(job, semantic)
        return self._synthesis_request(job)

    def _intrinsic_request(self, job: dict[str, Any], root: Path) -> dict[str, Any]:
        path = str(job["scope_key"])
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
            raise SupersededSemanticJob("The target module no longer exists in the mounted tree")
        raw_content = candidate.read_bytes()
        raw_hash = hashlib.sha256(raw_content).hexdigest()
        content = raw_content.decode("utf-8", errors="replace")
        with self.database.connect() as connection:
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
        with self.database.connect() as connection:
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
                            "dossier": _compact_dossier(document["value"]),
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
        with self.database.connect() as connection:
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
            "child_dossiers": [
                {
                    "scope": item["scope_key"],
                    "kind": item["document_kind"],
                    "confidence": item["confidence"],
                    "value": _compact_dossier(item["value"]),
                }
                for item in documents
            ],
            "missing_children": job["metadata"].get("missing_members", [])[:100],
            "missing_child_count": len(job["metadata"].get("missing_members", [])),
            "previous_dossier": previous["value"] if previous else None,
        }


def _compact_dossier(value: dict[str, Any]) -> dict[str, Any]:
    """Keep cross-module reasoning useful without repeatedly nesting full prose."""

    return {
        "summary": str(value.get("summary") or "")[:2_000],
        "responsibilities": _compact_strings(value, "responsibilities"),
        "public_contracts": _compact_strings(value, "public_contracts"),
        "invariants": _compact_strings(value, "invariants"),
        "architecture_role": str(value.get("architecture_role") or "")[:1_000],
        "domain_concepts": _compact_strings(value, "domain_concepts"),
        "collaborators": _compact_strings(value, "collaborators"),
        "overlaps": _compact_strings(value, "overlaps"),
        "extension_points": _compact_strings(value, "extension_points"),
        "similar_modules": _compact_strings(value, "similar_modules"),
        "pattern_opportunities": _compact_patterns(value),
        "consolidation_assessment": _compact_consolidation(value),
        "dead_code_candidates": _compact_dead_code(value),
        "placement_guidance": str(value.get("placement_guidance") or "")[:2_000],
        "risks": _compact_strings(value, "risks"),
        "confidence": value.get("confidence"),
    }


def _compact_strings(value: dict[str, Any], key: str, limit: int = 12) -> list[str]:
    return [str(item)[:1_000] for item in (value.get(key) or [])[:limit]]


def _compact_patterns(value: dict[str, Any]) -> list[Any]:
    result = []
    for item in (value.get("pattern_opportunities") or [])[:8]:
        if isinstance(item, dict):
            result.append(
                {
                    "name": str(item.get("name") or "")[:300],
                    "scope": str(item.get("scope") or "")[:200],
                    "score": item.get("score"),
                    "confidence": item.get("confidence"),
                    "rationale": str(item.get("rationale") or "")[:1_000],
                    "evidence": [str(entry)[:500] for entry in (item.get("evidence") or [])[:4]],
                    "counter_evidence": [
                        str(entry)[:500] for entry in (item.get("counter_evidence") or [])[:4]
                    ],
                    "migration_cost": item.get("migration_cost"),
                }
            )
        else:
            result.append(str(item)[:1_000])
    return result


def _compact_dead_code(value: dict[str, Any]) -> list[Any]:
    result = []
    for item in (value.get("dead_code_candidates") or [])[:8]:
        if isinstance(item, dict):
            result.append(
                {
                    "path_or_symbol": str(item.get("path_or_symbol") or "")[:500],
                    "confidence": item.get("confidence"),
                    "rationale": str(item.get("rationale") or "")[:1_000],
                    "verification": str(item.get("verification") or "")[:1_000],
                }
            )
        else:
            result.append(str(item)[:1_000])
    return result


def _compact_consolidation(value: dict[str, Any]) -> Any:
    consolidation = value.get("consolidation_assessment")
    if not isinstance(consolidation, dict):
        return consolidation
    return {
        "recommendation": consolidation.get("recommendation"),
        "score": consolidation.get("score"),
        "rationale": str(consolidation.get("rationale") or "")[:1_000],
        "candidates": [str(item)[:500] for item in (consolidation.get("candidates") or [])[:12]],
    }
