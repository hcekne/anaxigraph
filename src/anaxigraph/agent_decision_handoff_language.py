"""Readable placement, constraint, and verification handoffs over indexed evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ARCHITECTURE_HANDOFF_LANGUAGE_VERSION = "architecture-handoff-explanation-v1"
VERIFICATION_LANGUAGE_VERSION = "architecture-verification-explanation-v1"


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
            "Use the placement recommendation as the starting point, preserve the listed "
            "contracts and invariants, and follow the verification steps after a small change."
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
            "why": "The selected scope contains no usable module placement evidence.",
            "what_to_do": "Clarify the coding goal or inspect the ranked scope before editing code.",
            "how_to_check": ["Confirm that the next scope request selects at least one module."],
        }
    return {
        "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
        "conclusion": f"Start this change in {path}.",
        "why": guidance or role or "This is the highest-ranked file for the requested coding goal.",
        "what_to_do": guidance
        or f"Make the smallest goal-specific change behind {path}'s public boundary.",
        "examples_to_follow": precedents,
        "how_to_check": [
            f"Confirm that callers and focused tests treat {path} as the right ownership boundary.",
            "If the change needs unrelated modules, request a new scope instead of widening it silently.",
        ],
    }


def constraint_item_explanation(item: Mapping[str, Any]) -> dict[str, Any]:
    path = str(item.get("path") or "this module")
    contracts = _strings(item.get("public_contracts"), 6)
    invariants = _strings(item.get("invariants"), 6)
    risks = _strings(item.get("risks"), 6)
    return {
        "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
        "conclusion": f"Keep the recorded behavior of {path} intact while making this change.",
        "what_must_stay_true": [*contracts, *invariants]
        or ["No current semantic contract was recorded for this module."],
        "what_could_go_wrong": risks
        or ["No specific semantic risk was recorded; normal caller and test checks still apply."],
        "what_to_do": (
            f"Turn the listed behavior for {path} into focused checks before changing its structure."
        ),
    }


def constraints_explanation(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
            "conclusion": "No current semantic constraints were available for the selected code.",
            "what_to_do": (
                "Do not assume there are no constraints. Check callers, tests, configuration, and "
                "stored data before changing behavior."
            ),
        }
    paths = ", ".join(str(item.get("path") or "") for item in items[:4])
    return {
        "version": ARCHITECTURE_HANDOFF_LANGUAGE_VERSION,
        "conclusion": f"Preserve the recorded contracts, invariants, and risks for {paths}.",
        "what_to_do": (
            "Use each module's explanation as a pre-change checklist and keep the relevant focused "
            "tests passing."
        ),
    }


def verification_explanation(verification: Mapping[str, Any]) -> dict[str, Any]:
    comparison = verification.get("post_change_comparison")
    tests = _strings(verification.get("focused_test_paths"), 8)
    if isinstance(comparison, Mapping):
        conclusion = str(comparison.get("summary") or "The before/after comparison is available.")
    else:
        conclusion = (
            "AnaxiGraph captured the before-change architecture facts but has not compared a new "
            "scan yet."
        )
    steps = []
    if tests:
        steps.append(f"Run the focused tests: {', '.join(tests)}.")
    steps.extend(
        [
            "Run `anaxigraph update . --json` after the code change.",
            "Send the saved post-change baseline with the same coding goal and compare the result.",
        ]
    )
    return {
        "version": VERIFICATION_LANGUAGE_VERSION,
        "conclusion": conclusion,
        "what_to_do": steps,
        "what_the_result_can_prove": (
            "It can show which tracked architecture facts changed between two scans."
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
            "This recommendation uses current module meaning and independently reviewed pattern "
            "advice for the selected code."
        ),
        "semantic_current": (
            "This recommendation uses current module meaning, but no finalized pattern review was "
            "available for the selected code."
        ),
        "semantic_partial": (
            "Some selected modules have current semantic understanding and some do not, so treat "
            "the recommendation as incomplete."
        ),
        "deterministic_only": (
            "This recommendation uses source structure and repository facts only; current semantic "
            "understanding was not available."
        ),
    }.get(status, f"AnaxiGraph selected {selected_modules} module(s) for this coding goal.")


def _decision_evidence(
    selected_modules: int, semantic_modules: int, reviewed_patterns: int
) -> list[str]:
    return [
        f"{selected_modules} module(s) were selected for the coding goal.",
        f"{semantic_modules} selected module(s) had current semantic understanding.",
        f"{reviewed_patterns} independently reviewed pattern evaluation(s) were included.",
    ]


def _decision_limits(status: str) -> list[str]:
    if status == "semantic_and_reviewed":
        return [
            "This is architecture advice, not permission to edit beyond the returned scope or skip tests."
        ]
    return [
        "Missing semantic or reviewed-pattern evidence can hide responsibilities and design constraints.",
        "Use the deterministic scope as a starting point and verify the boundary before editing.",
    ]


def _comparison_observations(status: str, value: Any) -> list[str]:
    if status == "rescan_required":
        return ["No newer snapshot was available, so no post-change comparison was possible."]
    if status == "incomparable":
        return ["The two packets did not describe the same repository and coding goal."]
    changes = value if isinstance(value, Mapping) else {}
    modules = changes.get("modules") if isinstance(changes.get("modules"), Mapping) else {}
    findings = changes.get("findings") if isinstance(changes.get("findings"), Mapping) else {}
    patterns = changes.get("patterns") if isinstance(changes.get("patterns"), Mapping) else {}
    counts = {
        "module": sum(len(item) for item in modules.values() if isinstance(item, list)),
        "finding": sum(len(item) for item in findings.values() if isinstance(item, list)),
        "reviewed pattern": sum(len(item) for item in patterns.values() if isinstance(item, list)),
    }
    if not any(counts.values()):
        return ["The tracked module, finding, and reviewed-pattern facts did not change."]
    return [
        f"AnaxiGraph observed {count} {name} change(s)." for name, count in counts.items() if count
    ]


def _comparison_action(status: str) -> str:
    return {
        "rescan_required": "Run a new scan, then compare again with the same baseline and coding goal.",
        "incomparable": "Capture and use a baseline for this repository and the same coding goal.",
        "changed": (
            "Read the changed modules and plain-language findings, then confirm the intended "
            "behavior with focused tests before calling the change an improvement."
        ),
        "unchanged": (
            "If architecture was expected to change, inspect the scan scope and evidence; otherwise "
            "keep the result as confirmation that tracked facts stayed stable."
        ),
    }.get(status, "Read the evidence and focused test results before drawing a conclusion.")


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item)[:700] for item in value[:limit] if str(item or "").strip()]
