"""Calibrated architectural advice from one durable before/after evidence packet."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from anaxigraph.finding_language import finding_caveats
from anaxigraph.reassessment_semantic_advice import (
    pattern_effect_spec,
    semantic_effect_specs,
)

REASSESSMENT_ADVICE_VERSION = "reassessment-advice-v1"
REASSESSMENT_CATEGORIES = (
    "responsibility",
    "placement",
    "dependencies",
    "complexity",
    "duplication",
    "pattern_fit",
    "boundary_coherence",
    "possible_unused_code",
)

_FINDING_CATEGORIES = {
    "architecture_violation": "boundary_coherence",
    "architecture_drift": "boundary_coherence",
    "dependency_cycle": "boundary_coherence",
    "possible_dead_code": "possible_unused_code",
    "module_complexity": "complexity",
    "symbol_complexity": "complexity",
    "long_function": "complexity",
    "high_fan_in": "dependencies",
    "high_fan_out": "dependencies",
}


def reassessment_advice(
    evidence: dict[str, Any],
    *,
    patterns: list[dict[str, Any]],
    change_coupling: dict[str, Any],
) -> dict[str, Any]:
    effects = [
        *(_finding_effect(item) for item in evidence.get("finding_changes") or []),
        *(_module_effects(evidence)),
        *(_effect(**item) for item in semantic_effect_specs(evidence)),
        *(_effect(**spec) for item in patterns if (spec := pattern_effect_spec(item)) is not None),
    ]
    effects = _deduplicate(effect for effect in effects if effect is not None)
    effects.sort(key=_effect_sort_key)
    returned = effects[:30]
    return {
        "contract_version": REASSESSMENT_ADVICE_VERSION,
        "effects": returned,
        "coverage": _coverage(evidence, returned, patterns),
        "history_evidence": change_coupling,
        "counts": {
            "total": len(effects),
            "returned": len(returned),
            "omitted": max(0, len(effects) - len(returned)),
            "improvements": sum(
                item["classification"] in {"improved", "resolved"} for item in effects
            ),
            "regressions": sum(
                item["classification"] in {"worsened", "regressed", "introduced"}
                for item in effects
            ),
        },
    }


def _finding_effect(finding: dict[str, Any]) -> dict[str, Any]:
    finding_type = str(finding.get("finding_type") or "observation")
    transition = str(finding.get("transition") or "introduced")
    resolved = transition == "resolved"
    classification = _finding_classification(finding, resolved)
    subject, summary, action = _finding_terms(finding, finding_type)
    language = _finding_transition_language(finding, summary, action, resolved)
    caveats = _strings(finding_caveats(finding_type), 4)
    return _effect(
        category=_FINDING_CATEGORIES.get(finding_type, "boundary_coherence"),
        classification=classification,
        subject=subject,
        observation=language["observation"],
        consequence=language["consequence"],
        recommendation=language["recommendation"],
        confidence=float(finding.get("confidence") or 0.5),
        basis=f"deterministic finding {finding_type}",
        counter_evidence=caveats,
        reasons_to_leave_alone=language["reasons"],
        follow_up=language["follow_up"],
        verification="Run focused tests, refresh the scan, and confirm this stable finding remains resolved or does not recur.",
        evidence=_finding_evidence(finding),
    )


def _finding_terms(finding: dict[str, Any], finding_type: str) -> tuple[str, str, str]:
    subject = ", ".join(str(value) for value in finding.get("affected_artifacts") or [])
    subject = subject or str(finding.get("stable_key") or "repository")
    summary = str(finding.get("summary") or finding_type.replace("_", " "))
    action = str(finding.get("recommended_action") or "Review the smallest affected scope.")
    return subject, summary, action


def _finding_transition_language(
    finding: dict[str, Any], summary: str, action: str, resolved: bool
) -> dict[str, Any]:
    if resolved:
        return {
            "observation": f"The previous architecture signal is no longer present: {summary}",
            "consequence": "The measured architecture moved in the intended direction; preserve the behavior that removed this signal.",
            "recommendation": "Retain the refactor unless focused behavior checks reveal a regression.",
            "reasons": [
                "The signal is resolved; no further structural change is supported by this evidence."
            ],
            "follow_up": "Keep the current boundary and run the focused tests.",
        }
    return {
        "observation": f"The current scan now reports: {summary}",
        "consequence": str(
            finding.get("explanation") or "The change may weaken the current design."
        ),
        "recommendation": action,
        "reasons": _strings(finding_caveats(str(finding.get("finding_type") or "")), 3),
        "follow_up": action,
    }


def _finding_classification(finding: dict[str, Any], resolved: bool) -> str:
    if resolved:
        return "resolved"
    return "regressed" if finding.get("status") == "regressed" else "introduced"


def _finding_evidence(finding: dict[str, Any]) -> list[dict[str, Any]]:
    reference = str(finding.get("stable_key") or "")
    return [
        {"kind": "finding", "reference": reference, "detail": value}
        for value in _strings(finding.get("evidence"), 5)
    ]


def _module_effects(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    relationship = evidence.get("relationship_changes") or {}
    result: list[dict[str, Any]] = []
    for change in evidence.get("module_changes") or []:
        before = change.get("before")
        after = change.get("after")
        if before is None or after is None:
            result.append(_presence_effect(change))
            continue
        result.extend(_metric_effects(change, before, after))
        placement = _placement_effect(change, before, after)
        if placement:
            result.append(placement)
        dependency = _dependency_effect(change, relationship)
        if dependency:
            result.append(dependency)
        responsibility = _responsibility_effect(change, before, after)
        if responsibility:
            result.append(responsibility)
        if change.get("changed_fields") == ["raw_hash"]:
            result.append(_raw_only_effect(change))
    return result


def _presence_effect(change: dict[str, Any]) -> dict[str, Any]:
    added = change.get("change") == "added"
    path = str(change.get("path") or "module")
    return _effect(
        category="responsibility",
        classification="introduced" if added else "removed",
        subject=path,
        observation=f"{path} was {'added to' if added else 'removed from'} the repository map.",
        consequence=(
            "A new file now owns behavior or support work and needs an explicit place in the current responsibility map."
            if added
            else "A previous responsibility or support path left the current system."
        ),
        recommendation=(
            "Confirm the file has one clear responsibility and follows an existing extension point."
            if added
            else "Confirm callers, configuration, runtime registration, and focused tests no longer require it."
        ),
        confidence=0.9,
        basis="saved file presence",
        counter_evidence=[
            "Generated or vendored files can appear without representing a new product responsibility."
        ],
        reasons_to_leave_alone=[
            "Keep the change if it is the smallest coherent owner of the behavior."
        ],
        follow_up=f"Inspect {path} with its direct callers and tests.",
        verification="Refresh the map after focused checks and confirm no unresolved internal references were introduced.",
        evidence=[{"kind": "module", "reference": path, "detail": str(change.get("change"))}],
    )


def _metric_effects(
    change: dict[str, Any], before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    old = float(before.get("complexity") or 0)
    new = float(after.get("complexity") or 0)
    if old == new:
        return []
    improved = new < old
    path = str(change.get("path") or "module")
    direction = "fell" if improved else "rose"
    return [
        _effect(
            category="complexity",
            classification="improved" if improved else "worsened",
            subject=path,
            observation=f"Measured file complexity {direction} from {old:g} to {new:g}.",
            consequence=(
                "The file now has fewer measured decision paths to understand and test."
                if improved
                else "The file now has more measured decision paths, which may raise maintenance and test cost."
            ),
            recommendation=(
                "Retain the simpler structure if focused behavior checks still pass."
                if improved
                else "Check whether one cohesive decision or responsibility can be extracted without adding a parallel abstraction."
            ),
            confidence=0.8,
            basis="parser-reported cyclomatic estimate",
            counter_evidence=[
                "A higher branch count can be inherent to a clear protocol or validation boundary."
            ],
            reasons_to_leave_alone=[
                "Do not split cohesive policy solely to reduce a numeric score."
            ],
            follow_up=f"Review the changed decision paths in {path} and its focused tests.",
            verification="Run focused tests and compare complexity after the next scan.",
            evidence=[
                {"kind": "metric", "reference": path, "detail": f"complexity {old:g} → {new:g}"}
            ],
        )
    ]


def _placement_effect(
    change: dict[str, Any], before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any] | None:
    old = str(before.get("group") or "ungrouped")
    new = str(after.get("group") or "ungrouped")
    if old == new:
        return None
    path = str(change.get("path") or "module")
    return _effect(
        category="placement",
        classification="changed",
        subject=path,
        observation=f"The current map places {path} in {new}; the comparison placed it in {old}.",
        consequence="The file's architectural neighborhood and applicable boundary rules may have changed.",
        recommendation="Confirm the new area owns the responsibility and that dependencies point in the intended direction.",
        confidence=0.75,
        basis="current architecture placement",
        counter_evidence=[
            "A path-policy edit can change the label without changing runtime responsibility."
        ],
        reasons_to_leave_alone=[
            "Keep the placement when it matches the file's responsibility and stable local conventions."
        ],
        follow_up=f"Check {path}, its direct callers, and the boundary rule between {old} and {new}.",
        verification="Refresh the scan and confirm no architecture-violation finding appears.",
        evidence=[{"kind": "placement", "reference": path, "detail": f"{old} → {new}"}],
    )


def _dependency_effect(
    change: dict[str, Any], relationship: dict[str, Any]
) -> dict[str, Any] | None:
    path = str(change.get("path") or "")
    added = [
        item for item in relationship.get("added") or [] if path in {item["source"], item["target"]}
    ]
    removed = [
        item
        for item in relationship.get("removed") or []
        if path in {item["source"], item["target"]}
    ]
    if not added and not removed:
        return None
    return _effect(
        category="dependencies",
        classification="changed",
        subject=path,
        observation=f"Direct code links around {path} changed: {len(added)} added and {len(removed)} removed.",
        consequence="Callers, dependencies, and the file's blast radius may differ from the previous saved map.",
        recommendation="Read the changed direct links before editing more files; prefer the existing boundary when it remains coherent.",
        confidence=0.82,
        basis="extracted relationship delta",
        counter_evidence=[
            "Dynamic wiring and runtime registration may be absent from static links."
        ],
        reasons_to_leave_alone=[
            "A new direct link is not itself a design problem when it follows the intended dependency direction."
        ],
        follow_up=f"Inspect the {len(added) + len(removed)} changed links touching {path}.",
        verification="Run focused tests for both sides and confirm resolution provenance remains honest after a scan.",
        evidence=[
            {
                "kind": "relationship",
                "reference": f"{item['source']} → {item['target']}",
                "detail": f"{verb} {item['type']}",
            }
            for verb, values in (("added", added), ("removed", removed))
            for item in values[:5]
        ],
    )


def _responsibility_effect(
    change: dict[str, Any], before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any] | None:
    left = before.get("semantic") or {}
    right = after.get("semantic") or {}
    keys = ("summary", "architecture_role", "responsibilities")
    if right.get("status") != "current" or all(left.get(key) == right.get(key) for key in keys):
        return None
    path = str(change.get("path") or "module")
    return _effect(
        category="responsibility",
        classification="changed",
        subject=path,
        observation=f"The current AI dossier describes a changed responsibility for {path}.",
        consequence=str(
            right.get("architecture_role")
            or right.get("summary")
            or "Its role in the repository changed."
        ),
        recommendation="Confirm the new responsibility is cohesive and not already owned by a related module.",
        confidence=float(right.get("confidence") or 0.6),
        basis="current module dossier compared with its prior dossier",
        counter_evidence=_strings(right.get("risks"), 3),
        reasons_to_leave_alone=[
            "A wording change alone is not proof that code should move or split."
        ],
        follow_up=f"Compare {path} with the related modules named in its current dossier.",
        verification="Ask for architecture guidance on this responsibility after focused tests and a current semantic refresh.",
        evidence=[
            {
                "kind": "semantic_dossier",
                "reference": path,
                "detail": str(right.get("summary") or "updated responsibility"),
            }
        ],
    )


def _raw_only_effect(change: dict[str, Any]) -> dict[str, Any]:
    path = str(change.get("path") or "module")
    return _effect(
        category="responsibility",
        classification="coherent_no_change",
        subject=path,
        observation=f"{path} changed textually, but its structural hash stayed the same.",
        consequence="The saved structural and semantic contracts do not currently show an architectural change.",
        recommendation="Leave the architecture alone unless behavior or runtime evidence says otherwise.",
        confidence=0.78,
        basis="content hash changed while structural hash stayed stable",
        counter_evidence=[
            "Configuration strings or dynamic behavior can change without altering the parsed structure."
        ],
        reasons_to_leave_alone=["No structural rewrite is supported by the current evidence."],
        follow_up=f"Run the focused behavior checks for {path}; avoid an architecture-only refactor.",
        verification="Refresh the scan after tests and confirm no dependency or finding delta appears.",
        evidence=[
            {"kind": "hash", "reference": path, "detail": "raw changed; structural unchanged"}
        ],
    )


def _effect(
    *,
    category: str,
    classification: str,
    subject: str,
    observation: str,
    consequence: str,
    recommendation: str,
    confidence: float,
    basis: str,
    counter_evidence: list[str],
    reasons_to_leave_alone: list[str],
    follow_up: str,
    verification: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    core = {
        "category": category,
        "classification": classification,
        "subject": subject,
        "observed_change": observation,
        "architectural_consequence": consequence,
        "recommendation": recommendation,
        "confidence": _confidence(confidence, basis),
        "counter_evidence": counter_evidence,
        "reasons_to_leave_alone": reasons_to_leave_alone,
        "smallest_safe_follow_up": follow_up,
        "verification": verification,
        "evidence": evidence,
    }
    identity = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:20]
    return {"id": f"reassessment:{identity}", **core}


def _confidence(score: float, basis: str) -> dict[str, Any]:
    bounded = round(min(1.0, max(0.0, score)), 3)
    return {
        "score": bounded,
        "label": "high" if bounded >= 0.8 else "medium" if bounded >= 0.55 else "limited",
        "basis": basis,
    }


def _coverage(
    evidence: dict[str, Any], effects: list[dict[str, Any]], patterns: list[dict[str, Any]]
) -> dict[str, Any]:
    represented = {str(item["category"]) for item in effects}
    semantic_states = (evidence.get("semantic_scopes") or {}).get("states") or []
    pending = any(str(item.get("status") or "").startswith("pending") for item in semantic_states)
    return {
        category: (
            "observed"
            if category in represented
            else "waiting_for_semantic_refresh"
            if pending
            and category in {"responsibility", "duplication", "pattern_fit", "possible_unused_code"}
            else "no_change_observed"
        )
        for category in REASSESSMENT_CATEGORIES
    } | {"reviewed_pattern_results": len(patterns)}


def _deduplicate(effects: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for effect in effects:
        key = (effect["category"], effect["classification"], effect["subject"])
        if key in seen:
            continue
        seen.add(key)
        result.append(effect)
    return result


def _effect_sort_key(item: dict[str, Any]) -> tuple[int, float, str, str]:
    priority = {
        "regressed": 0,
        "introduced": 1,
        "worsened": 2,
        "candidate": 3,
        "opportunity": 4,
        "changed": 5,
        "removed": 6,
        "resolved": 7,
        "improved": 8,
        "coherent_no_change": 9,
    }
    return (
        priority.get(str(item["classification"]), 10),
        -float((item.get("confidence") or {}).get("score") or 0),
        str(item["category"]),
        str(item["subject"]),
    )


def _strings(values: Any, limit: int) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [str(value)[:1_000] for value in values if str(value).strip()][:limit]
