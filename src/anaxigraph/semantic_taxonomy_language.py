"""Plain-language projection for one AI-created repository group."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from anaxigraph.semantic_file_language import explain_specialist_terms

SEMANTIC_TAXONOMY_LANGUAGE_VERSION = "semantic-taxonomy-explanation-v2"

# Taxonomy prompts already require ordinary language. Keep only stable, generic label
# substitutions here; repository-specific phrases belong in the saved taxonomy itself.
_PLAIN_NAME_TERMS = (
    ("repository projections", "repository views"),
    ("persistence", "saved data"),
    ("semantic", "AI understanding"),
    ("projection", "view"),
    ("adapters", "connections"),
    ("adapter", "connection"),
    ("boundaries", "handoffs"),
    ("boundary", "handoff"),
    ("composition roots", "startup wiring"),
    ("composition root", "startup wiring"),
    ("oracles", "expected answers"),
    ("oracle", "expected answer"),
)


def semantic_taxonomy_explanation(node: Mapping[str, Any]) -> dict[str, Any]:
    """Explain a repository area without requiring architecture vocabulary."""

    label = str(node.get("label") or node.get("name") or "Unnamed code group")
    level = str(node.get("level") or "subsystem")
    responsibility = _plain_sentence(node.get("responsibility"))
    description = _plain_sentence(node.get("description"))
    rationale = _plain_sentence(_visible_group_words(node.get("rationale")))
    confidence = _confidence(node.get("confidence"))
    display_name = _plain_name(label)
    return {
        "version": SEMANTIC_TAXONOMY_LANGUAGE_VERSION,
        "conclusion": f"The AI-created map uses {display_name} as {_level_meaning(level)}.",
        "display_name": display_name,
        "name_and_meaning": display_name,
        "what_this_group_does": responsibility
        or "The AI-created map did not state this group's concrete job.",
        "what_belongs_here": description
        or "The AI-created map did not explain which work belongs in this group.",
        "why_these_files_are_together": rationale
        or "The AI-created map did not record a reason for grouping these files.",
        "evidence_strength": {
            "value": confidence,
            "meaning": _confidence_meaning(confidence),
        },
    }


def semantic_taxonomy_assignment_explanation(assignment: Mapping[str, Any]) -> dict[str, Any]:
    """Explain one file's placement without repeating an AI-generated internal note."""

    area = _plain_name(str(assignment.get("area_name") or assignment.get("area") or "code area"))
    subsystem = _plain_name(
        str(assignment.get("subsystem_name") or assignment.get("subsystem") or "code group")
    )
    confidence = _confidence(assignment.get("confidence"))
    destination = subsystem if subsystem == area else f"{subsystem}, inside {area}"
    reason = (
        "Repository map configuration explicitly puts this file in this group."
        if assignment.get("locked")
        else (
            "The AI map compared the file's saved description and direct code links with the "
            "jobs of the other groups. This group was its strongest match."
        )
    )
    return {
        "version": SEMANTIC_TAXONOMY_LANGUAGE_VERSION,
        "conclusion": f"The AI-created map places this file in {destination}.",
        "area_name": area,
        "subsystem_name": subsystem,
        "why_this_file_is_here": reason,
        "evidence_strength": {
            "value": confidence,
            "meaning": _confidence_meaning(confidence),
        },
    }


def _level_meaning(level: str) -> str:
    if level == "area":
        return "a broad area containing smaller groups of related repository work"
    return "a smaller group of files that perform closely related work"


def _plain_name(label: str) -> str:
    text = label.replace(" & ", " and ").replace("-", " ")
    for phrase, replacement in _PLAIN_NAME_TERMS:
        text = re.sub(
            rf"(?<![\w]){re.escape(phrase)}(?![\w])",
            lambda match: _matching_case(replacement, match.start()),
            text,
            flags=re.IGNORECASE,
        )
    return text


def _visible_group_words(value: Any) -> str:
    text = str(value or "").strip()
    replacements = (
        (r"\b(?:cluster|group)-\d+\s+is\b", "these files are"),
        (r"\b(?:cluster|group)-\d+\s+supplies\b", "these files supply"),
        (r"\b(?:cluster|group)-\d+\s+focuses\b", "these files focus"),
        (r"\b(?:cluster|group)-\d+\s+documents\b", "these files document"),
        (r"\b(?:cluster|group)-\d+\b", "this group"),
        (r"\bthe supplied cluster\s+is\b", "these files are"),
        (r"\bthe cluster\s+is\b", "these files are"),
        (r"\bthe cluster\s+defines\b", "these files define"),
        (r"\bthe cluster\s+performs\b", "these files perform"),
        (r"\bthe clusters\s+are\b", "these groups are"),
        (r"\bboth clusters\s+are\b", "these groups are"),
        (r"\beach cluster\s+is\b", "each group is"),
        (r"\bclusters\b", "groups"),
        (r"\bcluster\b", "group"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text[:1].upper() + text[1:] if text else ""


def _plain_sentence(value: Any) -> str:
    return _sentence(explain_specialist_terms(value))


def _matching_case(replacement: str, offset: int) -> str:
    if offset == 0:
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _confidence_meaning(confidence: float) -> str:
    strength = "strong" if confidence >= 0.7 else "mixed" if confidence >= 0.4 else "weak"
    return (
        f"Support for this grouping is {strength}. This describes the evidence behind the AI "
        "grouping; it is not a grade for the files."
    )


def _sentence(value: str) -> str:
    return value if not value or value.endswith((".", "?", "!")) else f"{value}."
