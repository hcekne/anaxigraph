from __future__ import annotations

from copy import deepcopy

import pytest

from anaxigraph.config import load_config
from scripts.check_self_analysis import analysis_contract, evaluate_gate, scan_repository


def _finding(*, evidence: str = "estimated_cyclomatic_complexity=16") -> dict:
    return {
        "stable_key": "symbol-complexity:fixture",
        "finding_type": "symbol_complexity",
        "severity": "warning",
        "confidence": 1.0,
        "summary": "fixture is complex",
        "affected_artifacts": ["pkg/core.py"],
        "evidence": [evidence],
        "source": "deterministic",
        "priority_version": "risk-churn-blast-v1",
    }


def _baseline(contract: dict, findings: list[dict] | None = None) -> dict:
    accepted = []
    for finding in findings or []:
        accepted.append(
            {
                "stable_key": finding["stable_key"],
                "finding_type": finding["finding_type"],
                "severity": finding["severity"],
                "affected_artifacts": finding["affected_artifacts"],
                "evidence": finding["evidence"],
                "rationale": "Fixture debt accepted for comparison.",
                "removal_phase": "fixture",
            }
        )
    return {
        "schema_version": 1,
        "contract": contract,
        "governance": {"minimum_severity": "warning", "sources": ["deterministic"]},
        "accepted_findings": accepted,
    }


def test_unchanged_finding_passes_and_info_is_nonblocking(repository):
    contract = analysis_contract(load_config(repository))
    warning = _finding()
    info = {**_finding(), "stable_key": "info:fixture", "severity": "info"}

    result = evaluate_gate(_baseline(contract, [warning]), contract, [warning, info])

    assert result["passed"] is True
    assert result["governed_findings"] == 1
    assert result["nonblocking_findings"] == 1


@pytest.mark.parametrize(
    ("evidence", "code"),
    [
        ("estimated_cyclomatic_complexity=17", "evidence_regression"),
        ("estimated_cyclomatic_complexity=15", "stale_evidence_baseline"),
        ("detector_detail=changed", "evidence_changed"),
    ],
)
def test_changed_evidence_requires_an_explicit_baseline_update(repository, evidence, code):
    contract = analysis_contract(load_config(repository))
    original = _finding()
    changed = _finding(evidence=evidence)

    result = evaluate_gate(_baseline(contract, [original]), contract, [changed])

    assert result["passed"] is False
    assert [item["code"] for item in result["issues"]] == [code]


def test_new_resolved_and_contract_changes_fail_closed(repository):
    contract = analysis_contract(load_config(repository))
    warning = _finding()

    introduced = evaluate_gate(_baseline(contract), contract, [warning])
    resolved = evaluate_gate(_baseline(contract, [warning]), contract, [])
    changed_contract = deepcopy(contract)
    changed_contract["detector_version"] = "next"
    changed = evaluate_gate(_baseline(contract), changed_contract, [])

    assert introduced["issues"][0]["code"] == "new_finding"
    assert resolved["issues"][0]["code"] == "stale_baseline"
    assert changed["issues"][0]["code"] == "contract_mismatch"


def test_repository_fixture_detects_a_new_governed_regression(repository):
    contract = analysis_contract(load_config(repository))
    _, original = scan_repository(repository)
    baseline = _baseline(contract, _governed(original))
    assert evaluate_gate(baseline, contract, original)["passed"] is True

    branches = "\n".join(f"    if value == {index}: return {index}" for index in range(12))
    (repository / "pkg" / "branchy.py").write_text(
        f"def branchy(value):\n{branches}\n    return -1\n", encoding="utf-8"
    )
    _, changed = scan_repository(repository)
    result = evaluate_gate(baseline, contract, changed)

    assert result["passed"] is False
    assert any(item["code"] == "new_finding" for item in result["issues"])


def _governed(findings: list[dict]) -> list[dict]:
    return [
        item
        for item in findings
        if item["source"] == "deterministic" and item["severity"] != "info"
    ]
