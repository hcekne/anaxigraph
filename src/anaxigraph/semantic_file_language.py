"""Plain-language AI-map state for one file."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SEMANTIC_FILE_LANGUAGE_VERSION = "semantic-file-explanation-v2"


def semantic_file_explanation(path: str, semantic: Mapping[str, Any]) -> dict[str, Any]:
    """Explain one file's saved AI description without workflow-state jargon."""

    status = str(semantic.get("status") or "not_started")
    role = str(semantic.get("architecture_role") or "").strip()
    placement = str(semantic.get("placement_guidance") or "").strip()
    confidence = _confidence(semantic.get("confidence"))
    return {
        "version": SEMANTIC_FILE_LANGUAGE_VERSION,
        "conclusion": _conclusion(path, status),
        "what_this_file_does": role or _missing_role(status),
        "where_related_work_belongs": (
            placement or "The AI map did not record where related work should be added."
        ),
        "evidence_strength": {
            "value": confidence,
            "meaning": _confidence_meaning(status, confidence),
        },
        "how_to_use_the_raw_fields": (
            "The separate fields about patterns, whether nearby code should be combined, and code "
            "that might be unused are early AI notes, not instructions to change code. Before "
            "changing or deleting code, use the architecture_decision section: it checks those "
            "notes against repository evidence and explains the recommended action."
        ),
    }


def _conclusion(path: str, status: str) -> str:
    if status == "current":
        return (
            f"The AI map has an up-to-date description of {path} and its role in this repository."
        )
    if status == "intrinsic_current":
        return (
            f"The AI map has described {path} itself, but has not finished how it fits with the "
            "rest of the repository."
        )
    if status == "excluded":
        return f"{path} is deliberately outside AI mapping."
    if status.startswith("failed_") or status == "failed":
        return f"AI mapping could not finish an up-to-date description of {path}."
    if status.startswith("pending_") or status in {"pending", "stale"}:
        return f"The AI description of {path} is incomplete or waiting for a refresh."
    return f"The AI map has not described {path} yet."


def _missing_role(status: str) -> str:
    if status == "excluded":
        return "No AI description is expected while this file remains outside AI mapping."
    return "The AI map does not have an up-to-date description of what this file does."


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _confidence_meaning(status: str, confidence: float) -> str:
    if status not in {"current", "intrinsic_current"}:
        return "No evidence-strength rating is available because this file has no current AI description."
    strength = "strong" if confidence >= 0.7 else "mixed" if confidence >= 0.4 else "weak"
    return (
        f"Support for this AI description is {strength}. This measures its evidence, not the "
        "quality of the code."
    )
