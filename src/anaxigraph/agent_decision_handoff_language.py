"""Readable placement, constraint, and verification handoffs over indexed evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from anaxigraph.semantic_file_language import (
    semantic_file_explanation as semantic_file_explanation,
)

ARCHITECTURE_HANDOFF_LANGUAGE_VERSION = "architecture-handoff-explanation-v2"
VERIFICATION_LANGUAGE_VERSION = "architecture-verification-explanation-v2"


def decision_explanation(
    status: str, *, selected_modules: int, semantic_modules: int, reviewed_patterns: int
) -> dict[str, Any]:
    return {
        "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
        "conclusion": _decision_conclusion(status, selected_modules),
        "what_anaxigraph_used": _decision_evidence(
            selected_modules, semantic_modules, reviewed_patterns
        ),
        "what_to_do": (
            "Start with the suggested file. Keep the listed caller-visible behavior and other "
            "must-stay-true rules. After a small change, run the listed checks."
        ),
        "limits": _decision_limits(status),
    }


def placement_explanation(placement: Mapping[str, Any]) -> dict[str, Any]:
    path = str(placement.get("preferred_path") or "")
    guidance = str(placement.get("guidance") or "").strip()
    role = str(placement.get("architecture_role") or "").strip()
    precedents = _strings(placement.get("local_precedents"), 4)
    if not path:
        return {
            "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
            "conclusion": "AnaxiGraph could not identify a file where this change should start.",
            "why": "The selected files contain no usable evidence about which file owns this job.",
            "what_to_do": "Clarify the coding goal or inspect the ranked files before editing code.",
            "how_to_check": ["Confirm that the next map request selects at least one file."],
        }
    return {
        "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
        "conclusion": f"Start this change in {path}.",
        "why": guidance or role or "This is the highest-ranked file for the requested coding goal.",
        "what_to_do": guidance
        or f"Make the smallest change in {path} that completes the goal without changing unrelated behavior.",
        "examples_to_follow": precedents,
        "how_to_check": [
            f"Confirm that callers and focused tests show {path} is responsible for the behavior you need to change.",
            "If you must change unrelated files, request a new map for the wider goal instead of silently expanding the change.",
        ],
    }


def constraint_item_explanation(item: Mapping[str, Any]) -> dict[str, Any]:
    path = str(item.get("path") or "this file")
    contracts = _strings(item.get("public_contracts"), 6)
    invariants = _strings(item.get("invariants"), 6)
    risks = _strings(item.get("risks"), 6)
    return {
        "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
        "conclusion": f"Keep the recorded behavior of {path} intact while making this change.",
        "what_must_stay_true": [*contracts, *invariants]
        or ["The AI map did not record specific behavior that must stay true for this file."],
        "what_could_go_wrong": risks
        or ["The AI map did not record a specific risk. Still check callers and focused tests."],
        "what_to_do": (
            f"Turn the listed behavior for {path} into focused checks before changing its structure."
        ),
    }


def constraints_explanation(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
            "conclusion": (
                "The AI map did not provide up-to-date, file-specific rules about behavior that "
                "must stay true."
            ),
            "what_to_do": (
                "Do not assume any behavior is safe to change. Check callers, tests, configuration, "
                "and stored data first."
            ),
        }
    paths = ", ".join(str(item.get("path") or "") for item in items[:4])
    return {
        "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
        "conclusion": f"Keep the listed behavior true and watch for the listed risks in {paths}.",
        "what_to_do": (
            "Treat each file's explanation as a checklist before changing it, and keep the relevant "
            "focused tests passing."
        ),
    }


def verification_explanation(verification: Mapping[str, Any]) -> dict[str, Any]:
    comparison = verification.get("post_change_comparison")
    tests = _strings(verification.get("focused_test_paths"), 8)
    if isinstance(comparison, Mapping):
        conclusion = str(comparison.get("summary") or "The before/after comparison is available.")
    else:
        conclusion = (
            "AnaxiGraph saved what the selected code looked like before the change, but it has not "
            "compared a newer scan yet."
        )
    steps = []
    if tests:
        steps.append(f"Run the focused tests: {', '.join(tests)}.")
    steps.extend(
        [
            "Run `anaxigraph update . --json` after the code change.",
            "Send the saved before-change record with the same coding goal and compare the result.",
        ]
    )
    return {
        "version": VERIFICATION_LANGUAGE_VERSION,
        "conclusion": conclusion,
        "what_to_do": steps,
        "what_the_result_can_prove": (
            "It can show which tracked facts about files, findings, and pattern ratings changed "
            "between two scans."
        ),
        "what_it_cannot_prove": (
            "A changed score or disappeared finding does not by itself prove that the code improved. "
            "The expected behavior and focused tests must also pass."
        ),
    }


def comparison_explanation(comparison: Mapping[str, Any]) -> dict[str, Any]:
    status = str(comparison.get("status") or "")
    return {
        "version": VERIFICATION_LANGUAGE_VERSION,
        "conclusion": str(comparison.get("summary") or "No comparison summary is available."),
        "what_anaxigraph_saw": _comparison_observations(status, comparison.get("changes")),
        "what_to_do": _comparison_action(status),
        "what_it_does_not_prove": str(
            comparison.get("interpretation")
            or "The comparison does not prove that the code became better or worse."
        ),
    }


def compact_explanation(value: Any, *fields: str) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    return {
        key: source.get(key)
        for key in ("version", *fields)
        if source.get(key) not in (None, "", [])
    }


def _decision_conclusion(status: str, selected_modules: int) -> str:
    return {
        "semantic_and_reviewed": (
            "This advice uses up-to-date AI descriptions of the selected files and pattern results "
            "that completed a separate AI check."
        ),
        "semantic_current": (
            "This advice uses up-to-date AI descriptions of the selected files, but no pattern "
            "result had completed its separate AI check."
        ),
        "semantic_partial": (
            "Some selected files have up-to-date AI descriptions and others do not, so this advice "
            "may miss responsibilities or behavior that must stay true."
        ),
        "deterministic_only": (
            "This advice uses imports, file structure, Git history, and other facts AnaxiGraph read "
            "directly. No up-to-date AI description of the selected files was available."
        ),
    }.get(status, f"AnaxiGraph selected {_items(selected_modules, 'file', 'files')} for this goal.")


def _decision_evidence(
    selected_modules: int, semantic_modules: int, reviewed_patterns: int
) -> list[str]:
    return [
        f"{_items(selected_modules, 'file was', 'files were')} selected for the coding goal.",
        f"{_items(semantic_modules, 'selected file had', 'selected files had')} an up-to-date AI description.",
        f"{_items(reviewed_patterns, 'pattern result had', 'pattern results had')} completed a separate AI check.",
    ]


def _decision_limits(status: str) -> list[str]:
    if status == "semantic_and_reviewed":
        return [
            "This advice says where the change may belong. It does not grant permission to edit "
            "files outside the returned list or skip tests."
        ]
    return [
        "Without up-to-date AI descriptions or separate pattern checks, AnaxiGraph may miss what "
        "files are responsible for or what behavior must stay true.",
        "Start with the returned files, but inspect their callers and focused tests before editing.",
    ]


def _comparison_observations(status: str, value: Any) -> list[str]:
    if status == "rescan_required":
        return ["No newer saved scan was available, so no after-change comparison was possible."]
    if status == "incomparable":
        return ["The two saved records did not describe the same repository and coding goal."]
    changes = value if isinstance(value, Mapping) else {}
    modules = changes.get("modules") if isinstance(changes.get("modules"), Mapping) else {}
    findings = changes.get("findings") if isinstance(changes.get("findings"), Mapping) else {}
    patterns = changes.get("patterns") if isinstance(changes.get("patterns"), Mapping) else {}
    counts = [
        (
            "file record",
            "file records",
            sum(len(item) for item in modules.values() if isinstance(item, list)),
        ),
        (
            "finding",
            "findings",
            sum(len(item) for item in findings.values() if isinstance(item, list)),
        ),
        (
            "AI-checked pattern result",
            "AI-checked pattern results",
            sum(len(item) for item in patterns.values() if isinstance(item, list)),
        ),
    ]
    if not any(count for _, _, count in counts):
        return ["The tracked files, findings, and AI-checked pattern results did not change."]
    return [
        f"AnaxiGraph found {_items(count, singular, plural)} that changed."
        for singular, plural, count in counts
        if count
    ]


def _comparison_action(status: str) -> str:
    return {
        "rescan_required": (
            "Run a new scan, then compare again with the same saved before-change record and coding goal."
        ),
        "incomparable": (
            "Save a before-change record for this repository and use the same coding goal."
        ),
        "changed": (
            "Read the changed file records and plain-language findings, then confirm the intended "
            "behavior with focused tests before calling the change an improvement."
        ),
        "unchanged": (
            "If the code map was expected to change, inspect which files were scanned and what "
            "evidence was available. Otherwise, keep this as confirmation that the tracked facts "
            "stayed the same."
        ),
    }.get(status, "Read the evidence and focused test results before drawing a conclusion.")


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item)[:700] for item in value[:limit] if str(item or "").strip()]


def _items(value: int, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}"
