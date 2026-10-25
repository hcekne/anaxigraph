"""Pure change comparison and attribution of externally executed checks."""

from __future__ import annotations

from typing import Any

from anaxigraph.contracts import Graph

from .guidance import structural_findings


def attribute_checks(
    receipts: list[dict[str, Any]] | None, snapshot_id: str
) -> list[dict[str, Any]]:
    if receipts is not None and (not isinstance(receipts, list) or len(receipts) > 50):
        raise ValueError("receipts must be a list of at most 50 supplied check results")
    checks = []
    for receipt in receipts or []:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("command"), str):
            raise ValueError("Each check needs a command, snapshot_id and integer exit_code")
        if not receipt["command"].strip():
            raise ValueError("Check command must be nonempty")
        if type(receipt.get("exit_code")) is not int:
            raise ValueError("Each check needs an integer exit_code")
        matched = receipt.get("snapshot_id") == snapshot_id
        checks.append(
            {
                "command": receipt["command"][:1000],
                "origin": "agent-or-CI-reported",
                "status": "stale"
                if not matched
                else "passed"
                if receipt["exit_code"] == 0
                else "failed",
                "exit_code": receipt["exit_code"],
                "snapshot_id": receipt.get("snapshot_id"),
            }
        )
    return checks


def findings_delta(graph: Graph, previous: Graph | None) -> list[dict[str, Any]]:
    old = {(f["kind"], f["entity"]): f for f in structural_findings(previous)} if previous else {}
    findings = []
    for finding in structural_findings(graph):
        prior = old.get((finding["kind"], finding["entity"]))
        finding["change"] = (
            "introduced"
            if prior is None
            else (
                "worsened"
                if finding["measured"] > prior["measured"]
                else "improved"
                if finding["measured"] < prior["measured"]
                else "unchanged"
            )
        )
        if prior:
            finding["previous_measured"] = prior["measured"]
        findings.append(finding)
    return findings


def change_review(
    graph: Graph, previous: Graph | None, receipts: list[dict[str, Any]] | None
) -> dict[str, Any]:
    before = previous.snapshot.files if previous else {}
    after = graph.snapshot.files
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    checks = attribute_checks(receipts, graph.snapshot.id)
    findings = findings_delta(graph, previous)
    return {
        "base_snapshot_id": previous.snapshot.id if previous else None,
        "candidate_snapshot_id": graph.snapshot.id,
        "comparison": "previous scan" if previous else "no saved baseline",
        "changed_paths": changed[:100],
        "changed_total": len(changed),
        "findings": findings[:50],
        "checks": checks,
        "behavioral_status": "unchecked"
        if not checks
        else "failed"
        if any(c["status"] == "failed" for c in checks)
        else "reported-passed"
        if all(c["status"] == "passed" for c in checks)
        else "unresolved",
        "uncertainty": "Supplied checks are attributed reports. AnaxiGraph did not run target code; static facts do not prove behavior.",
    }
