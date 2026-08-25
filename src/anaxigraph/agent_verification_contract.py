"""Validate bounded architecture-verification baselines from agent clients."""

from __future__ import annotations

from typing import Any

ARCHITECTURE_BASELINE_VERSION = "architecture-verification-baseline-v2"
ARCHITECTURE_BASELINE_V1 = "architecture-verification-baseline-v1"


def validated_baseline(value: dict[str, Any], *, label: str) -> dict[str, Any]:
    """Unwrap and validate a current or backwards-compatible saved baseline."""

    value = _unwrap(value)
    version = value.get("contract_version")
    if version not in {None, "", ARCHITECTURE_BASELINE_V1, ARCHITECTURE_BASELINE_VERSION}:
        raise ValueError(f"Unsupported {label} verification baseline version: {version}")
    snapshot_id = _integer(value.get("snapshot_id"), f"{label} snapshot_id", minimum=1)
    modules = _validated_modules(value.get("modules"), label)
    finding_keys = _validated_strings(value.get("finding_keys"), 20, f"{label} finding_keys")
    findings = _validated_findings(value.get("findings"), finding_keys, label)
    return {
        "contract_version": str(version or "legacy"),
        "repository_fingerprint": _short_string(value.get("repository_fingerprint"), 64),
        "goal_fingerprint": _short_string(value.get("goal_fingerprint"), 64),
        "snapshot_id": snapshot_id,
        "modules": modules,
        "finding_keys": [item["key"] for item in findings],
        "findings": findings,
        "patterns": _validated_patterns(value.get("patterns"), label),
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
        result.append(_validated_module(item, path, label))
    return result


def _validated_module(item: dict[str, Any], path: str, label: str) -> dict[str, Any]:
    measurements_available = all(
        name in item for name in ("lines_of_code", "complexity", "fan_in", "fan_out")
    )
    semantic_details_available = all(
        name in item for name in ("responsibilities", "public_contracts")
    )
    return {
        "path": path,
        "structural_hash": _short_string(item.get("structural_hash"), 200),
        "lines_of_code": _number(item.get("lines_of_code", 0), f"{label} lines_of_code"),
        "complexity": _number(item.get("complexity", 0), f"{label} complexity"),
        "fan_in": _integer(item.get("fan_in", 0), f"{label} fan_in", minimum=0),
        "fan_out": _integer(item.get("fan_out", 0), f"{label} fan_out", minimum=0),
        "measurements_available": measurements_available,
        "group": _short_string(item.get("group"), 500),
        "responsibilities": _validated_strings(
            item.get("responsibilities", []), 6, f"{label} responsibilities"
        ),
        "public_contracts": _validated_strings(
            item.get("public_contracts", []), 6, f"{label} public_contracts"
        ),
        "semantic_details_available": semantic_details_available,
    }


def _validated_findings(value: Any, finding_keys: list[str], label: str) -> list[dict[str, Any]]:
    if value is None:
        return [_legacy_finding(key) for key in finding_keys]
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError(f"The {label} findings field must contain at most 20 items.")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Every {label} finding must be a JSON object.")
        key = _short_string(item.get("key"), 500)
        if not key or key in seen:
            raise ValueError(f"Every {label} finding needs a unique key.")
        seen.add(key)
        result.append(_validated_finding(item, key, label))
    if finding_keys and set(finding_keys) != seen:
        raise ValueError(f"The {label} finding keys must match the finding records.")
    return result


def _validated_finding(item: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "type": _short_string(item.get("type"), 100) or "architecture_finding",
        "severity": _short_string(item.get("severity"), 20) or "info",
        "paths": _validated_strings(item.get("paths", []), 20, f"{label} paths"),
        "observation": _short_string(item.get("observation"), 1_000)
        or "An architecture check needs attention.",
        "why_it_matters": _short_string(item.get("why_it_matters"), 1_000)
        or "This may make the code harder to change safely.",
        "next_step": _short_string(item.get("next_step"), 1_000)
        or "Inspect the affected code and make the smallest safe correction.",
        "when_no_change_may_be_needed": _validated_strings(
            item.get("when_no_change_may_be_needed", []), 4, f"{label} finding caveats"
        ),
        "how_to_check": _short_string(item.get("how_to_check"), 1_000)
        or "Run focused tests and scan again.",
    }


def _legacy_finding(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "type": "architecture_finding",
        "severity": "info",
        "paths": [],
        "observation": f"Architecture finding {key} is active.",
        "why_it_matters": "The older saved baseline did not retain this finding's explanation.",
        "next_step": "Open the current finding for its evidence and smallest next step.",
        "when_no_change_may_be_needed": [],
        "how_to_check": "Compare against a new version-2 baseline after the next scan.",
    }


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
                    for name in ("suitability", "conformance", "opportunity", "confidence")
                },
            }
        )
    return result


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


def _number(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"The {label} value must be a non-negative number.")
    return value


def _short_string(value: Any, limit: int) -> str:
    return str(value or "")[:limit]
