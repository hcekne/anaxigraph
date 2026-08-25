"""Bounded before/after comparison for architecture-decision handoffs."""

from __future__ import annotations

import hashlib
from typing import Any

from anaxigraph.agent_decision_handoff_language import comparison_explanation

ARCHITECTURE_BASELINE_VERSION = "architecture-verification-baseline-v1"
ARCHITECTURE_COMPARISON_VERSION = "architecture-verification-comparison-v1"

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

    return {
        "contract_version": ARCHITECTURE_BASELINE_VERSION,
        "repository_fingerprint": _fingerprint(repository_identity),
        "goal_fingerprint": _fingerprint(_normalized_goal(goal)),
        "snapshot_id": int(snapshot_id),
        "modules": [_module_baseline(item) for item in modules[:8]],
        "finding_keys": sorted(
            {
                str(item.get("stable_key") or item.get("id") or "")
                for item in findings
                if item.get("stable_key") or item.get("id")
            }
        )[:20],
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

    previous = _validated_baseline(_unwrap(previous_value), label="previous")
    current = _validated_baseline(_unwrap(current_value), label="current")
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
        "findings": _finding_changes(previous["finding_keys"], current["finding_keys"]),
        "patterns": _pattern_changes(previous["patterns"], current["patterns"]),
    }
    status, summary = _comparison_status(previous, current, changes)
    result = {
        "contract_version": ARCHITECTURE_COMPARISON_VERSION,
        "status": status,
        "summary": summary,
        "baseline_snapshot_id": previous["snapshot_id"],
        "current_snapshot_id": current["snapshot_id"],
        "changes": changes,
        "interpretation": (
            "This comparison says what the index observed. It does not call the change better "
            "or worse without an expected outcome and passing tests."
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
    return {
        "path": str(item.get("path") or ""),
        "structural_hash": str(item.get("structural_hash") or ""),
        "fan_in": int(item.get("fan_in") or 0),
        "fan_out": int(item.get("fan_out") or 0),
        "group": item.get("declared_group") or item.get("inferred_group") or item.get("group"),
    }


def _unwrap(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("The verification baseline must be a JSON object.")
    candidate: Any = value
    for key in ("architecture_decision", "verification", "post_change_baseline"):
        nested = candidate.get(key) if isinstance(candidate, dict) else None
        if isinstance(nested, dict):
            candidate = nested
    return candidate


def _validated_baseline(value: dict[str, Any], *, label: str) -> dict[str, Any]:
    version = value.get("contract_version")
    if version not in {None, "", ARCHITECTURE_BASELINE_VERSION}:
        raise ValueError(f"Unsupported {label} verification baseline version: {version}")
    snapshot_id = _integer(value.get("snapshot_id"), f"{label} snapshot_id", minimum=1)
    modules = _validated_modules(value.get("modules"), label)
    findings = _validated_strings(value.get("finding_keys"), 20, f"{label} finding_keys")
    patterns = _validated_patterns(value.get("patterns"), label)
    return {
        "contract_version": str(version or "legacy"),
        "repository_fingerprint": _short_string(value.get("repository_fingerprint"), 64),
        "goal_fingerprint": _short_string(value.get("goal_fingerprint"), 64),
        "snapshot_id": snapshot_id,
        "modules": modules,
        "finding_keys": findings,
        "patterns": patterns,
    }


def _validated_modules(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError(f"The {label} verification baseline must contain at most 8 modules.")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Every {label} verification module must be a JSON object.")
        path = _short_string(item.get("path"), 1_000)
        if not path or path in seen:
            raise ValueError(f"Every {label} verification module needs a unique path.")
        seen.add(path)
        result.append(
            {
                "path": path,
                "structural_hash": _short_string(item.get("structural_hash"), 200),
                "fan_in": _integer(item.get("fan_in", 0), f"{label} fan_in", minimum=0),
                "fan_out": _integer(item.get("fan_out", 0), f"{label} fan_out", minimum=0),
                "group": _short_string(item.get("group"), 500),
            }
        )
    return result


def _validated_patterns(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError(f"The {label} verification baseline must contain at most 8 patterns.")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Every {label} verification pattern must be a JSON object.")
        target = _short_string(item.get("target"), 1_000)
        key = _short_string(item.get("key"), 200)
        identity = (target, key)
        if not all(identity) or identity in seen:
            raise ValueError(f"Every {label} verification pattern needs a unique target and key.")
        scores = item.get("scores")
        if not isinstance(scores, dict):
            raise ValueError(f"Every {label} verification pattern needs score values.")
        seen.add(identity)
        result.append(
            {
                "target": target,
                "key": key,
                "scores": {
                    name: _integer(scores.get(name, 0), f"{label} {name}", minimum=0, maximum=100)
                    for name in _SCORE_NAMES
                },
            }
        )
    return result


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
        "changes": {"modules": {}, "findings": {}, "patterns": {}},
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
    for name in ("fan_in", "fan_out"):
        if before[name] != after[name]:
            result[name] = {
                "before": before[name],
                "after": after[name],
                "change": after[name] - before[name],
            }
    if before["group"] != after["group"]:
        result["architecture_group"] = {"before": before["group"], "after": after["group"]}
    return result


def _finding_changes(before: list[str], after: list[str]) -> dict[str, list[str]]:
    old, new = set(before), set(after)
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
    return any(
        value for group in changes.values() for value in group.values() if isinstance(value, list)
    )


def _change_summary(before: int, after: int, changes: dict[str, Any]) -> str:
    modules = changes["modules"]
    patterns = changes["patterns"]
    module_count = sum(len(modules[name]) for name in modules)
    finding_count = sum(len(value) for value in changes["findings"].values())
    pattern_count = sum(len(patterns[name]) for name in patterns)
    return (
        f"Between snapshots {before} and {after}, AnaxiGraph observed {module_count} tracked "
        f"module changes, {finding_count} finding changes, and {pattern_count} reviewed pattern "
        "changes."
    )


def _legacy_caveats(previous: dict[str, Any]) -> list[str]:
    if previous["contract_version"] != "legacy":
        return []
    return [
        "This older baseline has no repository or goal fingerprint, so identity could not be checked."
    ]


def _validated_strings(value: Any, limit: int, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"The {label} field must be a list with at most {limit} items.")
    return [_short_string(item, 500) for item in value if _short_string(item, 500)]


def _integer(value: Any, label: str, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"The {label} value must be a whole number.")
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and {maximum}" if maximum is not None else ""
        raise ValueError(f"The {label} value must be between {minimum}{upper}.")
    return value


def _short_string(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _normalized_goal(value: str) -> str:
    return " ".join(str(value).lower().split())


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""
