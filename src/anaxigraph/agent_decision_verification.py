"""Bounded before/after comparison for architecture-decision handoffs."""

from __future__ import annotations

import hashlib
from typing import Any

from anaxigraph.agent_change_effects import structural_effects
from anaxigraph.agent_decision_handoff_language import comparison_explanation
from anaxigraph.agent_verification_contract import (
    ARCHITECTURE_BASELINE_V1,
    ARCHITECTURE_BASELINE_VERSION,
    _short_string,
    validated_baseline,
)

ARCHITECTURE_COMPARISON_VERSION = "architecture-verification-comparison-v2"

_SCORE_NAMES = ("suitability", "conformance", "opportunity", "confidence")


def verification_baseline(
    *,
    repository_identity: str,
    goal: str,
    snapshot_id: int,
    modules: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Capture the small set of facts a later scope request can compare."""

    finding_records = [_finding_baseline(item) for item in findings[:20]]
    finding_records = [item for item in finding_records if item is not None]
    return {
        "contract_version": ARCHITECTURE_BASELINE_VERSION,
        "repository_fingerprint": _fingerprint(repository_identity),
        "goal_fingerprint": _fingerprint(_normalized_goal(goal)),
        "snapshot_id": int(snapshot_id),
        "modules": [_module_baseline(item) for item in modules[:8]],
        "finding_keys": sorted(item["key"] for item in finding_records),
        "findings": sorted(finding_records, key=lambda item: item["key"]),
        "patterns": [
            {
                "target": str(item.get("target") or ""),
                "key": str(item.get("key") or ""),
                "scores": {
                    name: int((item.get("scores") or {}).get(name) or 0) for name in _SCORE_NAMES
                },
            }
            for item in patterns[:8]
        ],
    }


def compare_verification_baselines(
    previous_value: dict[str, Any], current_value: dict[str, Any]
) -> dict[str, Any]:
    """Compare two bounded baselines without pretending that change means improvement."""

    previous = validated_baseline(previous_value, label="previous")
    current = validated_baseline(current_value, label="current")
    shared = _shared_identity(previous, current)
    if shared is not None:
        return _incomparable(previous, current, shared)
    if current["snapshot_id"] < previous["snapshot_id"]:
        return _incomparable(
            previous,
            current,
            "The current snapshot is older than the baseline snapshot.",
        )

    changes = {
        "modules": _module_changes(previous["modules"], current["modules"]),
        "findings": _finding_changes(previous["findings"], current["findings"]),
        "patterns": _pattern_changes(previous["patterns"], current["patterns"]),
        "structural_effects": structural_effects(
            previous["modules"],
            current["modules"],
            previous["findings"],
            current["findings"],
        ),
    }
    status, summary = _comparison_status(previous, current, changes)
    if status == "rescan_required":
        changes["structural_effects"] = structural_effects([], [], [], [])
    result = {
        "contract_version": ARCHITECTURE_COMPARISON_VERSION,
        "status": status,
        "summary": summary,
        "baseline_snapshot_id": previous["snapshot_id"],
        "current_snapshot_id": current["snapshot_id"],
        "changes": changes,
        "interpretation": (
            "Improved and worsened describe the direction of a measured structural signal. "
            "They do not prove the code is better or worse overall without the intended outcome "
            "and passing tests."
        ),
        "caveats": _legacy_caveats(previous),
    }
    result["plain_language"] = comparison_explanation(result)
    return result


def _comparison_status(
    previous: dict[str, Any], current: dict[str, Any], changes: dict[str, Any]
) -> tuple[str, str]:
    before, after = previous["snapshot_id"], current["snapshot_id"]
    if after == before:
        return (
            "rescan_required",
            f"Both packets use snapshot {after}. Run a scan before treating this as "
            "post-change evidence.",
        )
    if _has_changes(changes):
        return "changed", _change_summary(before, after, changes)
    return (
        "unchanged",
        f"The index advanced from snapshot {before} to {after}, but the tracked architecture "
        "facts did not change.",
    )


def _module_baseline(item: dict[str, Any]) -> dict[str, Any]:
    semantic = item.get("semantic") if isinstance(item.get("semantic"), dict) else {}
    return {
        "path": str(item.get("path") or ""),
        "structural_hash": str(item.get("structural_hash") or ""),
        "lines_of_code": int(item.get("lines_of_code") or 0),
        "complexity": float(item.get("complexity") or 0),
        "fan_in": int(item.get("fan_in") or 0),
        "fan_out": int(item.get("fan_out") or 0),
        "group": item.get("declared_group") or item.get("inferred_group") or item.get("group"),
        "responsibilities": _baseline_strings(
            semantic.get("responsibilities") or item.get("responsibilities"), 6
        ),
        "public_contracts": _baseline_strings(
            semantic.get("public_contracts") or item.get("public_interfaces"), 6
        ),
    }


def _shared_identity(previous: dict[str, Any], current: dict[str, Any]) -> str | None:
    for key, message in (
        ("repository_fingerprint", "The baseline belongs to a different repository."),
        ("goal_fingerprint", "The baseline belongs to a different coding goal."),
    ):
        before, after = previous[key], current[key]
        if before and after and before != after:
            return message
    return None


def _incomparable(previous: dict[str, Any], current: dict[str, Any], reason: str) -> dict[str, Any]:
    result = {
        "contract_version": ARCHITECTURE_COMPARISON_VERSION,
        "status": "incomparable",
        "summary": f"{reason} AnaxiGraph did not compare their results.",
        "baseline_snapshot_id": previous["snapshot_id"],
        "current_snapshot_id": current["snapshot_id"],
        "changes": {
            "modules": {},
            "findings": {},
            "patterns": {},
            "structural_effects": structural_effects([], [], [], []),
        },
        "interpretation": "Use a baseline captured for this repository and the same coding goal.",
        "caveats": _legacy_caveats(previous),
    }
    result["plain_language"] = comparison_explanation(result)
    return result


def _module_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    old = {item["path"]: item for item in before}
    new = {item["path"]: item for item in after}
    changed = []
    for path in sorted(old.keys() & new.keys()):
        details = _changed_module(old[path], new[path])
        if details:
            changed.append({"path": path, **details})
    return {
        "newly_tracked": sorted(new.keys() - old.keys()),
        "no_longer_tracked": sorted(old.keys() - new.keys()),
        "changed": changed,
    }


def _changed_module(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if before["structural_hash"] != after["structural_hash"]:
        result["source_structure_changed"] = True
    for name in ("lines_of_code", "complexity", "fan_in", "fan_out"):
        if (
            before["measurements_available"]
            and after["measurements_available"]
            and before[name] != after[name]
        ):
            result[name] = {
                "before": before[name],
                "after": after[name],
                "change": after[name] - before[name],
            }
    if before["group"] != after["group"]:
        result["architecture_group"] = {"before": before["group"], "after": after["group"]}
    for name in ("responsibilities", "public_contracts"):
        if (
            before["semantic_details_available"]
            and after["semantic_details_available"]
            and before[name] != after[name]
        ):
            result[name] = {"before": before[name], "after": after[name]}
    return result


def _finding_changes(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[str, list[str]]:
    old = {item["key"] for item in before}
    new = {item["key"] for item in after}
    return {
        "newly_reported": sorted(new - old),
        "no_longer_reported": sorted(old - new),
    }


def _pattern_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    old = {(item["target"], item["key"]): item for item in before}
    new = {(item["target"], item["key"]): item for item in after}
    changed = []
    for target, key in sorted(old.keys() & new.keys()):
        score_changes = {
            name: {
                "before": old[(target, key)]["scores"][name],
                "after": new[(target, key)]["scores"][name],
                "change": new[(target, key)]["scores"][name] - old[(target, key)]["scores"][name],
            }
            for name in _SCORE_NAMES
            if old[(target, key)]["scores"][name] != new[(target, key)]["scores"][name]
        }
        if score_changes:
            changed.append({"target": target, "key": key, "score_changes": score_changes})
    return {
        "newly_reported": [_pattern_identity(item) for item in sorted(new.keys() - old.keys())],
        "no_longer_reported": [_pattern_identity(item) for item in sorted(old.keys() - new.keys())],
        "changed": changed,
    }


def _pattern_identity(value: tuple[str, str]) -> dict[str, str]:
    return {"target": value[0], "key": value[1]}


def _has_changes(changes: dict[str, Any]) -> bool:
    for name, group in changes.items():
        if not isinstance(group, dict):
            continue
        if name == "structural_effects":
            if any(group.get(classification) for classification in _effect_change_classes()):
                return True
            continue
        if any(value for value in group.values() if isinstance(value, list)):
            return True
    return False


def _change_summary(before: int, after: int, changes: dict[str, Any]) -> str:
    modules = changes["modules"]
    patterns = changes["patterns"]
    module_count = sum(len(modules[name]) for name in modules)
    finding_count = sum(len(value) for value in changes["findings"].values())
    pattern_count = sum(len(patterns[name]) for name in patterns)
    effects = changes["structural_effects"]
    effect_count = sum(len(effects.get(name) or ()) for name in _effect_change_classes())
    return (
        f"Between snapshots {before} and {after}, AnaxiGraph observed {module_count} tracked "
        f"module changes, {finding_count} finding changes, and {pattern_count} reviewed pattern "
        f"changes. It classified {effect_count} structural effects that were introduced, worsened, "
        "improved, or resolved."
    )


def _effect_change_classes() -> tuple[str, ...]:
    return ("introduced", "worsened", "improved", "resolved")


def _legacy_caveats(previous: dict[str, Any]) -> list[str]:
    if previous["contract_version"] == "legacy":
        return [
            "This older baseline has no repository or goal fingerprint, so identity could not be checked.",
            "It also lacks full structural measurements and finding explanations, so some change classifications may be incomplete.",
        ]
    if previous["contract_version"] == ARCHITECTURE_BASELINE_V1:
        return [
            "This version-1 baseline lacks full structural measurements and finding explanations, so some change classifications may be incomplete."
        ]
    return []


def _finding_baseline(item: dict[str, Any]) -> dict[str, Any] | None:
    key = _short_string(item.get("stable_key") or item.get("id"), 500)
    if not key:
        return None
    language = item.get("plain_language") if isinstance(item.get("plain_language"), dict) else {}
    return {
        "key": key,
        "type": _short_string(item.get("finding_type"), 100) or "architecture_finding",
        "severity": _short_string(item.get("severity"), 20) or "info",
        "paths": _baseline_strings(item.get("affected_artifacts"), 20),
        "observation": _short_string(language.get("what") or item.get("summary"), 1_000)
        or "An architecture check needs attention.",
        "why_it_matters": _short_string(
            language.get("why_it_matters") or item.get("explanation"), 1_000
        )
        or "This may make the code harder to change safely.",
        "next_step": _short_string(
            language.get("next_step") or item.get("recommended_action"), 1_000
        )
        or "Inspect the affected code and make the smallest safe correction.",
        "when_no_change_may_be_needed": _baseline_strings(
            language.get("when_no_change_may_be_needed"), 4
        ),
        "how_to_check": _short_string(language.get("how_to_check"), 1_000)
        or "Run focused tests and scan again.",
    }


def _baseline_strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [text for item in value if (text := _short_string(item, 1_000))][:limit]


def _normalized_goal(value: str) -> str:
    return " ".join(str(value).lower().split())


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""
