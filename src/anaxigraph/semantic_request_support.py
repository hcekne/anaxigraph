"""Shared payload rules and compaction for AI repository requests."""

from __future__ import annotations

from typing import Any

MAPPING_REQUIREMENTS = {
    "purpose": "Describe what the code does and the essential behavior callers depend on.",
    "writing": (
        "Use short, concrete English sentences. Aim for 40–100 words total; simple files need "
        "less. Summary must fit 600 characters. Keep at most 8 responsibilities, 12 public "
        "contracts and 8 evidence references, each at most 240 characters. State each "
        "fact once. Use real code names and cite supplied paths or symbols. "
        "Put essential invariants and side effects in public_contracts. Do not repeat signatures, "
        "imports, or other facts already supplied by the code reader."
    ),
    "scope": (
        "Do not propose refactors, patterns, consolidation, deletion, or understandability reviews. "
        "Use empty lists when there is no supported claim. Confidence describes evidence, not code quality."
    ),
}
MAPPING_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 600},
        "responsibilities": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 240},
        },
        "public_contracts": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": 240},
        },
        "evidence": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 240},
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["summary", "responsibilities", "public_contracts", "evidence", "confidence"],
    "additionalProperties": False,
}

PLAIN_LANGUAGE_CONTRACT_VERSION = "plain-language-v3"

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
    "taxonomy": "The inferred responsibility map that groups files by the work they perform.",
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
    "understandability": (
        "An evidence-based assessment of maintenance tasks using the repository itself; "
        "it is not measured reader performance or a code-quality grade."
    ),
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


def compact_dossier(value: dict[str, Any], *, detailed: bool = False) -> dict[str, Any]:
    """Keep cross-module reasoning useful without repeatedly nesting full prose."""

    structured = (
        {key: value[key] for key in ("contracts", "capabilities")}
        if "overview" in value and "contracts" in value and "capabilities" in value
        else {}
    )
    if "overview" in value:
        value = {
            **value,
            "summary": value["overview"],
            "responsibilities": [item["purpose"] for item in value.get("capabilities", [])],
            "public_contracts": [item["statement"] for item in value.get("contracts", [])],
        }

    return {
        "summary": value.get("summary", ""),
        "responsibilities": value.get("responsibilities", []),
        "public_contracts": value.get("public_contracts", []),
        "evidence": value.get("evidence", []),
        "confidence": value.get("confidence"),
        **structured,
    }
