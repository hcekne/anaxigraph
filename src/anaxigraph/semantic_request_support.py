"""Shared payload rules and compaction for AI repository requests."""

from __future__ import annotations

from typing import Any

PLAIN_LANGUAGE_CONTRACT_VERSION = "plain-language-v2"

PLAIN_LANGUAGE_REQUIREMENTS = {
    "audience": (
        "Write for a smart twelve-year-old and for another coding agent. Both should understand "
        "the meaning on the first reading."
    ),
    "sentence_rule": (
        "Use short, ordinary, concrete sentences. Say what the code does, what evidence supports "
        "the statement, why it matters, and what is uncertain."
    ),
    "term_rule": (
        "Do not use labels such as adapter, facade, contract, boundary, composition root, "
        "persistence, semantic, transport, projection, deterministic, canonical, metadata, "
        "schema, lifecycle, pipeline, provenance, cohesion, topology, oracle, seam, surface, "
        "protocol, taxonomy, synthesis, or orchestration as substitutes for an explanation. "
        "State the concrete action first. When a precise technical term is necessary, define it "
        "in the same sentence."
    ),
    "score_rule": (
        "Never copy a field name, detector phrase, or score into prose without saying in ordinary "
        "language what it measured and what the number can and cannot mean."
    ),
    "final_review": (
        "Before returning the result, reread every sentence as someone new to the repository. "
        "Rewrite any sentence that merely names an expert concept, process, score, or code shape "
        "instead of explaining the concrete fact in ordinary words."
    ),
}

INPUT_TERM_MEANINGS = {
    "module": "A machine field may call one repository file a module.",
    "symbol": "A named part of code such as a function, method, class, interface, or type.",
    "artifact": "A saved identity for a file or another indexed piece of repository content.",
    "dossier": "A structured AI description of what code does and what evidence supports it.",
    "intrinsic": "A description based on one file itself, before using the rest of the repository.",
    "context": "A description that also uses related files and repository-wide evidence.",
    "taxonomy": "The AI-created map that groups files into broad areas and smaller groups.",
    "synthesis": "A summary that combines several completed code descriptions.",
    "scope": "The exact file, named code part, code area, or whole repository being described.",
    "area": "A broad group of files that contribute to the same kind of repository work.",
    "subsystem": "A smaller group of related work inside a broad repository area.",
    "facet": "An extra label for work that crosses several main groups; it does not move a file.",
    "public_interface": (
        "A name or caller-visible behavior that other code may rely on, such as a function, "
        "class, command, route, or file format."
    ),
    "responsibility": "One clear job that the described code performs.",
    "architecture_role": "How the described code helps the rest of this repository work.",
    "placement_guidance": "Advice about where code with a related job should be added.",
    "consolidation": "A suggestion to combine overlapping code or separate unrelated jobs.",
    "snapshot_id": (
        "The numeric id of one saved repository scan. It identifies a version; it is not a score."
    ),
    "complexity": (
        "The file-wide count of decision branches found by the code reader. It is not a code-quality grade."
    ),
    "relationship": (
        "A direct code link AnaxiGraph found between files. A missing link does not prove running code never connects them."
    ),
    "evidence": "A supplied fact or observation that supports a statement.",
    "counter_evidence": "A supplied fact or observation that points against a statement.",
    "provenance": "Which worker, model, instructions, and evidence created a saved AI result.",
    "deterministic": "Counted or traced by AnaxiGraph's code readers without asking an AI to decide.",
    "confidence": "How strongly the supplied evidence supports an AI statement, not code quality.",
}


def plain_language_instruction() -> str:
    """Return the shared writing rule as one provider instruction."""

    return " ".join(PLAIN_LANGUAGE_REQUIREMENTS.values())


def compact_dossier(value: dict[str, Any]) -> dict[str, Any]:
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
