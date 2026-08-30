"""Build bounded, evidence-backed guidance for splitting large source files."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from anaxigraph.agent_decision_handoff_language import _bounded_strings
from anaxigraph.agent_decomposition_mapping import (
    destination_paths,
    ordered_slices,
    responsibility_slices,
)

DECOMPOSITION_VERSION = "large-file-decomposition-v1"


def decomposition_advice(
    primary_files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    tests: list[str],
    findings: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Explain whether current evidence supports splitting a selected large file."""

    size_findings = {
        path: finding
        for finding in findings
        if finding.get("finding_type") == "module_complexity"
        for path in finding.get("affected_artifacts") or ()
    }
    symbols_by_path = _symbols_by_path(symbols)
    items = []
    for module in primary_files[:8]:
        path = str(module.get("path") or "")
        finding = size_findings.get(path)
        window = _review_window(module, path, rules or [])
        if finding is None and window is None:
            continue
        maximum, review_at = window or (None, None)
        items.append(
            _decomposition_item(
                module,
                symbols_by_path.get(path, []),
                tests,
                finding,
                patterns,
                maximum,
                review_at,
            )
        )
    return {
        "contract_version": DECOMPOSITION_VERSION,
        "candidate_count": sum(item["status"] == "candidate" for item in items),
        "keep_together_count": sum(item["status"] == "keep_together" for item in items),
        "insufficient_evidence_count": sum(
            item["status"] == "insufficient_evidence" for item in items
        ),
        "items": items[:5],
        "policy": (
            "File size starts an inspection; it never creates a split by itself. A candidate also "
            "needs a current AI description, evidence against the proposal, and named code parts "
            "that support at least two separate jobs."
        ),
    }


def compact_decomposition(value: Any) -> dict[str, Any]:
    """Retain the decision and extraction outline under a tight agent wire budget."""

    packet = value if isinstance(value, dict) else {}
    result = {
        key: packet.get(key, 0)
        for key in (
            "contract_version",
            "candidate_count",
            "keep_together_count",
            "insufficient_evidence_count",
        )
    }
    result["items"] = [_compact_item(item) for item in (packet.get("items") or [])[:2]]
    return result


def _decomposition_item(
    module: dict[str, Any],
    symbols: list[dict[str, Any]],
    tests: list[str],
    finding: dict[str, Any] | None,
    patterns: list[dict[str, Any]],
    maximum: int | None,
    review_at: int | None,
) -> dict[str, Any]:
    path = str(module.get("path") or "")
    semantic = module.get("semantic") if isinstance(module.get("semantic"), dict) else {}
    assessment = (
        semantic.get("consolidation_assessment")
        if isinstance(semantic.get("consolidation_assessment"), dict)
        else {}
    )
    responsibilities = _bounded_strings(semantic.get("responsibilities"), 5, 1_000)
    contracts = _bounded_strings(semantic.get("public_contracts"), 8, 1_000)
    evidence = _bounded_strings(assessment.get("evidence"), 5, 1_000)
    counter = _bounded_strings(assessment.get("counter_evidence"), 5, 1_000)
    status, reason, slices, unassigned = _decision(
        path,
        semantic,
        assessment,
        responsibilities,
        contracts,
        symbols,
    )
    item = {
        "path": path,
        "status": status,
        "reason": reason,
        "trigger": _trigger(module, finding, assessment, maximum, review_at),
        "responsibilities": responsibilities,
        "public_contracts_to_preserve": contracts,
        "callers_to_protect": _bounded_strings(module.get("incoming_paths"), 12, 1_000),
        "dependencies_to_check": _bounded_strings(module.get("outgoing_paths"), 12, 1_000),
        "focused_tests": [str(value)[:1_000] for value in tests[:12]],
        "supporting_evidence": evidence,
        "evidence_against_split": counter,
        "reviewed_patterns": _pattern_keys(path, patterns),
        "slices": slices,
        "unassigned_symbols": unassigned,
    }
    item["plain_language"] = _explanation(item)
    return item


def _decision(
    path: str,
    semantic: dict[str, Any],
    assessment: dict[str, Any],
    responsibilities: list[str],
    contracts: list[str],
    symbols: list[dict[str, Any]],
) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    preliminary = _preliminary_decision(semantic, assessment, responsibilities)
    if preliminary is not None:
        return preliminary
    slices, unassigned, coverage = responsibility_slices(
        responsibilities,
        contracts,
        symbols,
        destination_paths(semantic, assessment, path),
    )
    if len(slices) < 2 or coverage < 0.6:
        return (
            "insufficient_evidence",
            "The saved responsibilities cannot be tied reliably to enough named code parts.",
            [],
            unassigned,
        )
    return (
        "candidate",
        "Current AI and source evidence support testing this bounded split plan.",
        ordered_slices(path, slices),
        unassigned,
    )


def _preliminary_decision(
    semantic: dict[str, Any],
    assessment: dict[str, Any],
    responsibilities: list[str],
) -> tuple[str, str, list[dict[str, Any]], list[str]] | None:
    if semantic.get("status") != "current":
        return (
            "insufficient_evidence",
            "The selected file does not have an up-to-date AI description.",
            [],
            [],
        )
    recommendation = str(assessment.get("recommendation") or "insufficient_evidence")
    if (recommendation == "keep" and responsibilities) or len(responsibilities) == 1:
        return (
            "keep_together",
            "The current AI description says the code belongs to one connected job.",
            [],
            [],
        )
    if not responsibilities:
        return (
            "insufficient_evidence",
            "The current AI description does not name the file's separate jobs.",
            [],
            [],
        )
    evidence = _bounded_strings(assessment.get("evidence"), 5, 1_000)
    counter = _bounded_strings(assessment.get("counter_evidence"), 5, 1_000)
    score = int(assessment.get("score") or 0)
    if recommendation != "split" or score < 65 or not evidence or not counter:
        return (
            "insufficient_evidence",
            "The AI split suggestion lacks enough supporting and opposing evidence.",
            [],
            [],
        )
    return None


def _trigger(
    module: dict[str, Any],
    finding: dict[str, Any] | None,
    assessment: dict[str, Any],
    maximum: int | None,
    review_at: int | None,
) -> dict[str, Any]:
    language = finding.get("plain_language") if isinstance(finding, dict) else {}
    observation = language.get("what") if isinstance(language, dict) else ""
    lines = int(module.get("lines_of_code") or 0)
    observation = str(observation or (finding or {}).get("summary") or "")[:1_000]
    if not observation and maximum is not None:
        observation = (
            f"This file has {lines} lines of code and is approaching the configured "
            f"{maximum}-line maximum."
        )
    return {
        "lines_of_code": lines,
        "size_rule_active": finding is not None,
        "configured_maximum_lines": maximum,
        "review_starts_at_lines": review_at,
        "ai_recommendation": str(assessment.get("recommendation") or "insufficient_evidence"),
        "observation": observation,
    }


def _module_size_limit(path: str, rules: list[dict[str, Any]]) -> int | None:
    maxima = []
    for rule in rules:
        if rule.get("type") != "max_module_loc":
            continue
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict) or not _rule_matches(path, parameters.get("paths")):
            continue
        try:
            maximum = int(parameters.get("max") or 0)
        except (TypeError, ValueError):
            continue
        if maximum > 0:
            maxima.append(maximum)
    return min(maxima) if maxima else None


def _rule_matches(path: str, patterns: Any) -> bool:
    if not patterns:
        return True
    values = [patterns] if isinstance(patterns, str) else patterns
    return any(fnmatchcase(path, str(pattern)) for pattern in values)


def _review_threshold(maximum: int | None) -> int | None:
    return (maximum * 4 + 4) // 5 if maximum is not None else None


def _review_window(
    module: dict[str, Any], path: str, rules: list[dict[str, Any]]
) -> tuple[int, int] | None:
    maximum = _module_size_limit(path, rules)
    review_at = _review_threshold(maximum)
    if maximum is None or review_at is None:
        return None
    return (maximum, review_at) if int(module.get("lines_of_code") or 0) >= review_at else None


def _explanation(item: dict[str, Any]) -> dict[str, Any]:
    status = item["status"]
    path = item["path"]
    if status == "candidate":
        conclusion = (
            f"Test a {len(item['slices'])}-part split of {path}; do not move everything at once."
        )
        action = [
            (
                f"Step {part['extraction_order']}: keep or move {part['job']} with "
                f"{', '.join(symbol['name'] for symbol in part['symbols'][:6])}."
            )
            for part in item["slices"]
        ]
    elif status == "keep_together":
        conclusion = f"Keep {path} together for now; size alone is not evidence for a useful split."
        action = [
            "Keep the current responsibility together and watch whether a second job appears."
        ]
    else:
        conclusion = (
            f"Do not split {path} from this result; the map cannot support a safe boundary yet."
        )
        action = [
            "Refresh the file's AI description or inspect the unassigned names before proposing files."
        ]
    checks = [f"Run the focused test: {test}." for test in item["focused_tests"][:6]]
    if item["callers_to_protect"]:
        checks.append(f"Check callers: {', '.join(item['callers_to_protect'][:6])}.")
    return {
        "version": DECOMPOSITION_VERSION,
        "conclusion": conclusion,
        "what_anaxigraph_saw": [item["reason"], *item["supporting_evidence"]],
        "what_to_do": action,
        "reasons_not_to_split": [
            *item["evidence_against_split"],
            "A split is harmful when it creates extra files without separating jobs that change for different reasons.",
        ],
        "how_to_check": checks
        or ["Run focused tests after each extraction and ask AnaxiGraph to compare a new scan."],
    }


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    language = item.get("plain_language") if isinstance(item.get("plain_language"), dict) else {}
    return {
        "path": item.get("path"),
        "status": item.get("status"),
        "plain_language": {
            "conclusion": language.get("conclusion"),
            "what_to_do": language.get("what_to_do") or [],
        },
        "slices": [
            {
                "job": part.get("job"),
                "symbol_names": [symbol.get("name") for symbol in part.get("symbols") or []],
                "destination": part.get("destination"),
                "extraction_order": part.get("extraction_order"),
            }
            for part in (item.get("slices") or [])[:5]
        ],
    }


def _symbols_by_path(symbols: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        result.setdefault(str(symbol.get("path") or ""), []).append(symbol)
    for values in result.values():
        values.sort(
            key=lambda item: (int(item.get("start_line") or 0), str(item.get("name") or ""))
        )
    return result


def _pattern_keys(path: str, patterns: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("key")) for item in patterns if item.get("target") == path][:8]
