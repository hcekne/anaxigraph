#!/usr/bin/env python3
"""Scan AnaxiGraph with itself and reject deterministic architecture regressions."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from anaxigraph.analyzers import builtin_registry
from anaxigraph.architecture_models import DEFAULT_RULES, DETECTOR_VERSION
from anaxigraph.clock import utc_now
from anaxigraph.config import AnaxiGraphConfig, RuleConfig, load_config
from anaxigraph.history_discovery import repository_metadata
from anaxigraph.models import IR_SCHEMA_VERSION
from anaxigraph.persistence.finding_read import PRIORITY_VERSION
from anaxigraph.scanner import ANALYSIS_VERSION, RepositoryScanner
from anaxigraph.storage import AnaxiIndex

DEFAULT_BASELINE = Path("quality/self-analysis-baseline.json")
GATE_VERSION = "deterministic-self-analysis-v1"
SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}
REGRESSION_DIRECTIONS = {
    "module_complexity": {"lines_of_code": "higher"},
    "long_function": {"logical_lines": "higher"},
    "symbol_complexity": {"estimated_cyclomatic_complexity": "higher"},
    "high_fan_out": {"outgoing_dependencies": "higher"},
    "high_fan_in": {"incoming_dependencies": "higher"},
    "weak_test_coverage": {"line_coverage": "lower"},
}


@dataclass(frozen=True, slots=True)
class GateIssue:
    code: str
    message: str
    stable_key: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def analysis_contract(config: AnaxiGraphConfig) -> dict[str, Any]:
    analyzers = builtin_registry().analyzers
    rules = [_rule_contract(rule) for rule in _effective_rules(config)]
    encoded = json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()
    return {
        "gate_version": GATE_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "ir_schema_version": IR_SCHEMA_VERSION,
        "detector_version": DETECTOR_VERSION,
        "priority_version": PRIORITY_VERSION,
        "analyzers": {item.name: str(item.version) for item in sorted(analyzers, key=_name)},
        "rules_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _name(value: Any) -> str:
    return str(value.name)


def _effective_rules(config: AnaxiGraphConfig) -> tuple[RuleConfig, ...]:
    configured = {rule.rule_id: rule for rule in config.architecture.rules}
    defaults = tuple(configured.get(rule.rule_id, rule) for rule in DEFAULT_RULES)
    default_ids = {rule.rule_id for rule in DEFAULT_RULES}
    additions = tuple(rule for rule in config.architecture.rules if rule.rule_id not in default_ids)
    return defaults + additions


def _rule_contract(rule: RuleConfig) -> dict[str, Any]:
    return {
        "id": rule.rule_id,
        "type": rule.rule_type,
        "severity": rule.severity,
        "enabled": rule.enabled,
        "params": rule.params,
    }


def load_baseline(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("self-analysis baseline schema_version must be 1")
    if not isinstance(value.get("contract"), dict):
        raise ValueError("self-analysis baseline requires a contract object")
    if not isinstance(value.get("governance"), dict):
        raise ValueError("self-analysis baseline requires a governance object")
    _validate_entries(value.get("accepted_findings"))
    return value


def _validate_entries(entries: Any) -> None:
    if not isinstance(entries, list):
        raise ValueError("self-analysis accepted_findings must be a list")
    seen: set[str] = set()
    for entry in entries:
        key = str(entry.get("stable_key") or "") if isinstance(entry, dict) else ""
        if not key or key in seen:
            raise ValueError("self-analysis entries require unique stable_key values")
        if not entry.get("rationale") or not entry.get("removal_phase"):
            raise ValueError(f"self-analysis entry {key} requires rationale and removal_phase")
        if not isinstance(entry.get("evidence"), list):
            raise ValueError(f"self-analysis entry {key} requires evidence")
        seen.add(key)


def evaluate_gate(
    baseline: dict[str, Any],
    contract: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    governed = _governed_findings(findings, baseline["governance"])
    accepted = {item["stable_key"]: item for item in baseline["accepted_findings"]}
    current = {item["stable_key"]: item for item in governed}
    issues: list[GateIssue] = []
    if baseline["contract"] != contract:
        issues.append(
            GateIssue(
                "contract_mismatch",
                "analyzer, detector, rule, or priority contract changed; update the baseline explicitly",
            )
        )
    for key, finding in current.items():
        entry = accepted.get(key)
        if entry is None:
            issues.append(GateIssue("new_finding", _finding_label(finding), key))
            continue
        issues.extend(_finding_changes(entry, finding))
    for key in sorted(accepted.keys() - current.keys()):
        issues.append(
            GateIssue(
                "stale_baseline",
                "accepted finding is no longer present; remove it to preserve the improvement",
                key,
            )
        )
    return {
        "passed": not issues,
        "governed_findings": len(governed),
        "accepted_findings": len(accepted),
        "nonblocking_findings": len(findings) - len(governed),
        "issues": [item.as_dict() for item in issues],
        "current": [_compact_finding(item) for item in governed],
    }


def _governed_findings(
    findings: list[dict[str, Any]], governance: dict[str, Any]
) -> list[dict[str, Any]]:
    minimum = str(governance.get("minimum_severity", "warning"))
    if minimum not in SEVERITY_RANK:
        raise ValueError(f"unsupported self-analysis minimum severity: {minimum}")
    sources = {str(item) for item in governance.get("sources", ["deterministic"])}
    result = [
        item
        for item in findings
        if str(item.get("source")) in sources
        and SEVERITY_RANK.get(str(item.get("severity")), -1) >= SEVERITY_RANK[minimum]
    ]
    return sorted(result, key=lambda item: str(item["stable_key"]))


def _finding_changes(entry: dict[str, Any], finding: dict[str, Any]) -> list[GateIssue]:
    key = str(finding["stable_key"])
    issues: list[GateIssue] = []
    for field in ("finding_type", "severity", "affected_artifacts"):
        if entry.get(field) != finding.get(field):
            issues.append(
                GateIssue("finding_contract_changed", f"{field} changed from the baseline", key)
            )
    expected = [str(item) for item in entry.get("evidence", [])]
    actual = [str(item) for item in finding.get("evidence", [])]
    if expected != actual:
        issues.append(GateIssue(_evidence_change(entry, expected, actual), "evidence changed", key))
    return issues


def _evidence_change(entry: dict[str, Any], expected: list[str], actual: list[str]) -> str:
    old_values = _numeric_evidence(expected)
    new_values = _numeric_evidence(actual)
    directions = REGRESSION_DIRECTIONS.get(str(entry.get("finding_type")), {})
    if old_values.keys() != new_values.keys() or not old_values:
        return "evidence_changed"
    comparisons = [
        _metric_change(old_values[key], new_values[key], directions.get(key)) for key in old_values
    ]
    if "regressed" in comparisons:
        return "evidence_regression"
    if "improved" in comparisons:
        return "stale_evidence_baseline"
    return "evidence_changed"


def _numeric_evidence(evidence: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in evidence:
        key, separator, raw = item.partition("=")
        if not separator:
            return {}
        try:
            result[key] = float(raw)
        except ValueError:
            return {}
    return result


def _metric_change(old: float, new: float, direction: str | None) -> str:
    if old == new:
        return "same"
    if direction == "higher":
        return "regressed" if new > old else "improved"
    if direction == "lower":
        return "regressed" if new < old else "improved"
    return "changed"


def _finding_label(finding: dict[str, Any]) -> str:
    return f"new {finding.get('severity')} {finding.get('finding_type')}: {finding.get('summary')}"


def _compact_finding(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "stable_key",
        "finding_type",
        "severity",
        "confidence",
        "summary",
        "affected_artifacts",
        "evidence",
        "priority_score",
        "priority_version",
        "source",
    )
    return {key: item[key] for key in keys if key in item}


def scan_repository(
    root: Path, config_path: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with tempfile.TemporaryDirectory(prefix="anaxigraph-self-analysis-") as temporary:
        database = AnaxiIndex(Path(temporary) / "anaxi-index.db")
        stats = RepositoryScanner(database).scan(
            root, config_path=config_path, run_type="self_analysis"
        )
        findings = database.findings(stats.repository_id, limit=10_000)
        current = [item for item in findings if item["last_snapshot_id"] == stats.snapshot_id]
        return stats.as_dict(), [_compact_finding(item) for item in current]


def build_report(
    root: Path, baseline_path: Path, config_path: Path | None = None
) -> dict[str, Any]:
    baseline = load_baseline(baseline_path)
    config = load_config(root, config_path)
    contract = analysis_contract(config)
    scan, findings = scan_repository(root, config_path)
    result = evaluate_gate(baseline, contract, findings)
    git = repository_metadata(root, None)
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "repository": {
            "path": str(root),
            "revision": git.commit_sha,
            "branch": git.branch,
            "dirty": git.dirty,
        },
        "contract": contract,
        "scan": scan,
        "result": result,
        "all_findings": sorted(findings, key=lambda item: str(item["stable_key"])),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "anaxigraph-self-analysis.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    baseline = args.baseline if args.baseline.is_absolute() else root / args.baseline
    config = args.config.expanduser().resolve() if args.config else None
    report = build_report(root, baseline, config)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = report["result"]
    label = "PASS" if result["passed"] else "FAIL"
    print(
        f"Self-analysis {label}: {result['governed_findings']} governed, "
        f"{result['nonblocking_findings']} non-blocking, {len(result['issues'])} issue(s)."
    )
    for issue in result["issues"]:
        target = f" {issue['stable_key']}" if issue["stable_key"] else ""
        print(f"{issue['code']}:{target} — {issue['message']}")
    print(f"Full report: {output}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
