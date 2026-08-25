"""Classify bounded structural effects between two agent-scope baselines."""

from __future__ import annotations

from typing import Any

_MAX_EFFECTS = 20
_CLASSIFICATIONS = ("introduced", "worsened", "improved", "resolved", "pre_existing")
_SEVERITY = {"info": 0, "warning": 1, "error": 2, "critical": 3}
_FINDING_CATEGORIES = {
    "architecture_drift": "architecture_boundary",
    "architecture_violation": "architecture_boundary",
    "dependency_cycle": "dependency_cycle",
    "high_fan_in": "incoming_coupling",
    "high_fan_out": "outgoing_coupling",
    "long_function": "function_size",
    "module_complexity": "file_size",
    "possible_dead_code": "possible_unused_code",
    "symbol_complexity": "function_complexity",
    "weak_test_coverage": "test_protection",
}
_METRICS = {
    "lines_of_code": (
        "file_size",
        "code lines",
        "A growing file can become hard to change when it starts owning jobs that do not belong together.",
        "Name the file's jobs and split it only when separate jobs can change for separate reasons.",
        "The added lines may still belong to one clear responsibility.",
    ),
    "complexity": (
        "file_complexity",
        "branch points",
        "More branches create more outcomes that readers and tests must keep straight.",
        "Check whether one group of branches answers a separate question that belongs in a helper.",
        "The branches may all be necessary parts of one clear decision.",
    ),
    "fan_in": (
        "incoming_coupling",
        "direct incoming code links",
        "More callers make a file's public behavior harder to change safely.",
        "Keep the caller-facing contract small and inspect the newly connected callers.",
        "A stable shared interface can intentionally have many callers.",
    ),
    "fan_out": (
        "outgoing_coupling",
        "direct outgoing code links",
        "Using more files can make one module coordinate too many separate jobs.",
        "Group the outgoing links by job and keep only the coordination that belongs here.",
        "A coordinator may intentionally connect several focused components.",
    ),
}


def structural_effects(
    before_modules: list[dict[str, Any]],
    after_modules: list[dict[str, Any]],
    before_findings: list[dict[str, Any]],
    after_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return small, readable change classifications without storing another history model."""

    result: dict[str, Any] = {name: [] for name in _CLASSIFICATIONS}
    _add_finding_effects(result, before_findings, after_findings)
    _add_metric_effects(result, before_modules, after_modules)
    return _bounded(result)


def _add_finding_effects(
    result: dict[str, Any],
    before_findings: list[dict[str, Any]],
    after_findings: list[dict[str, Any]],
) -> None:
    old_findings = {item["key"]: item for item in before_findings}
    new_findings = {item["key"]: item for item in after_findings}
    for key in sorted(new_findings.keys() - old_findings.keys()):
        result["introduced"].append(_finding_effect("introduced", new_findings[key]))
    for key in sorted(old_findings.keys() - new_findings.keys()):
        result["resolved"].append(_finding_effect("resolved", old_findings[key]))
    for key in sorted(old_findings.keys() & new_findings.keys()):
        before, after = old_findings[key], new_findings[key]
        classification = _severity_change(before["severity"], after["severity"])
        result[classification].append(
            _finding_effect(classification, after, previous_severity=before["severity"])
        )


def _add_metric_effects(
    result: dict[str, Any],
    before_modules: list[dict[str, Any]],
    after_modules: list[dict[str, Any]],
) -> None:
    represented = {
        (item["category"], path)
        for name in ("introduced", "worsened", "improved", "resolved")
        for item in result[name]
        for path in item.get("paths") or ()
    }
    old_modules = {item["path"]: item for item in before_modules}
    new_modules = {item["path"]: item for item in after_modules}
    for path in sorted(old_modules.keys() & new_modules.keys()):
        before, after = old_modules[path], new_modules[path]
        if not before["measurements_available"] or not after["measurements_available"]:
            continue
        for field, details in _METRICS.items():
            category = details[0]
            if (category, path) in represented or not _material_change(
                field, before[field], after[field]
            ):
                continue
            classification = "worsened" if after[field] > before[field] else "improved"
            result[classification].append(
                _metric_effect(classification, path, field, before[field], after[field], details)
            )


def compact_structural_effects(value: Any, limit: int = 8) -> dict[str, Any]:
    """Keep the most useful effect guidance when the wider scope packet is compacted."""

    source = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {name: [] for name in _CLASSIFICATIONS}
    remaining = max(0, limit)
    omitted = int(source.get("omitted_count") or 0)
    for name in _CLASSIFICATIONS:
        items = source.get(name) if isinstance(source.get(name), list) else []
        selected = items[:remaining]
        result[name] = [_compact_effect(item) for item in selected if isinstance(item, dict)]
        omitted += max(0, len(items) - len(selected))
        remaining -= len(selected)
    result["omitted_count"] = omitted
    return result


def _severity_change(before: str, after: str) -> str:
    change = _SEVERITY.get(after, 0) - _SEVERITY.get(before, 0)
    if change > 0:
        return "worsened"
    if change < 0:
        return "improved"
    return "pre_existing"


def _material_change(field: str, before: int | float, after: int | float) -> bool:
    change = abs(after - before)
    if field != "lines_of_code":
        return change > 0
    threshold = max(1, (int(before) + 9) // 10)
    return change >= threshold


def _finding_effect(
    classification: str,
    finding: dict[str, Any],
    *,
    previous_severity: str | None = None,
) -> dict[str, Any]:
    finding_type = str(finding.get("type") or "architecture_finding")
    severity = str(finding.get("severity") or "info")
    paths = list(finding.get("paths") or ())
    observation = str(finding.get("observation") or "An architecture check needs attention.")
    if previous_severity and previous_severity != severity:
        observation = (
            f"{observation.rstrip('.')} Its project severity changed from "
            f"{previous_severity} to {severity}."
        )
    return {
        "classification": classification,
        "category": _FINDING_CATEGORIES.get(finding_type, finding_type),
        "finding_key": finding["key"],
        "path": paths[0] if paths else "",
        "paths": paths,
        "observation": observation,
        "why_it_matters": finding["why_it_matters"],
        "smallest_next_step": finding["next_step"],
        "when_no_change_may_be_needed": list(finding["when_no_change_may_be_needed"]),
        "how_to_check": finding["how_to_check"],
        "severity": severity,
        **({"previous_severity": previous_severity} if previous_severity else {}),
    }


def _metric_effect(
    classification: str,
    path: str,
    field: str,
    before: int | float,
    after: int | float,
    details: tuple[str, str, str, str, str],
) -> dict[str, Any]:
    category, unit, why, action, caveat = details
    direction = "grew" if after > before else "fell"
    return {
        "classification": classification,
        "category": category,
        "path": path,
        "paths": [path],
        "observation": f"{path} {direction} from {before:g} to {after:g} {unit}.",
        "why_it_matters": why,
        "smallest_next_step": action,
        "when_no_change_may_be_needed": [caveat],
        "how_to_check": (
            "Run focused tests, update the AnaxiGraph map, and compare this measurement again."
        ),
        "measurement": field,
        "before": before,
        "after": after,
        "change": after - before,
    }


def _compact_effect(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "classification",
        "category",
        "finding_key",
        "path",
        "observation",
        "why_it_matters",
        "smallest_next_step",
        "when_no_change_may_be_needed",
        "how_to_check",
        "severity",
        "previous_severity",
        "measurement",
        "before",
        "after",
        "change",
    )
    return {key: item[key] for key in keys if key in item}


def _bounded(result: dict[str, Any]) -> dict[str, Any]:
    remaining = _MAX_EFFECTS
    omitted = 0
    for name in _CLASSIFICATIONS:
        values = sorted(
            result[name],
            key=lambda item: (str(item.get("path") or ""), str(item.get("category") or "")),
        )
        result[name] = values[:remaining]
        omitted += max(0, len(values) - remaining)
        remaining = max(0, remaining - len(result[name]))
    result["omitted_count"] = omitted
    return result
