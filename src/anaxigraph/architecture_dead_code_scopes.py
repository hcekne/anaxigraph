"""Scoped static dead-code coverage and explicit reasons a check is unassessed."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import PurePosixPath

from anaxigraph.architecture_models import Finding
from anaxigraph.relationships import relationship_quality

_REASONS = {
    "dynamic_wiring_unavailable": "the analyzer cannot assess runtime registration",
    "change_age_unavailable": "no last-change date is available",
    "dynamic_links_in_scope": "this scope contains unresolved runtime links",
    "insufficient_scope_resolution": "too few internal references in this scope were resolved",
}


def scope_key(file):
    """A declared ownership scope takes precedence over the module's directory."""
    return str(file.get("declared_group") or PurePosixPath(file["path"]).parent)


def scope_quality(files, relationships):
    scopes = {
        file["artifact_id"]: scope_key(file)
        for file in files
        if file.get("artifact_type") in {"source", "test"}
    }
    rows = defaultdict(list)
    for edge in relationships:
        scope = scopes.get(edge["source_artifact_id"])
        if scope is not None and (
            edge.get("target_artifact_id") is None or edge["target_artifact_id"] in scopes
        ):
            rows[scope].append(edge)
    return {scope: relationship_quality(rows[scope]) for scope in set(scopes.values())}


def unassessed_findings(rule, reasons):
    """Diagnostics are coverage gaps, never unused-code or deletion recommendations."""
    result = []
    for scope, counts in sorted(reasons.items()):
        count = sum(counts.values())
        digest = hashlib.sha256(scope.encode()).hexdigest()[:20]
        result.append(
            Finding(
                stable_key=f"{rule.rule_id}:unassessed:{digest}",
                finding_type="dead_code_unassessed",
                severity="info",
                confidence=1.0,
                summary=f"Unused-code check is incomplete for {count} files in {scope}",
                explanation="; ".join(
                    f"{value} files: {_REASONS[key]}" for key, value in sorted(counts.items())
                ),
                affected_artifacts=(),
                evidence=(
                    f"assessment_scope={scope}",
                    f"unassessed_files={count}",
                    *(f"{key}={value}" for key, value in sorted(counts.items())),
                ),
                recommended_action=(
                    "Inspect the missing evidence and runtime loaders before deciding that code is unused. "
                    "Other scopes are checked independently. No candidate does not mean no unused code."
                ),
            )
        )
    return result


def assessment_report(findings, enabled):
    unassessed = sum(
        int(value.split("=", 1)[1])
        for finding in findings
        if finding.finding_type == "dead_code_unassessed"
        for value in finding.evidence
        if value.startswith("unassessed_files=")
    )
    return {
        "version": "scoped-unused-code-v1",
        "state": "off" if not enabled else "partial" if unassessed else "complete",
        "candidate_count": sum(item.finding_type == "possible_dead_code" for item in findings),
        "unassessed_file_count": unassessed,
        "scope_gap_count": sum(item.finding_type == "dead_code_unassessed" for item in findings),
        "caveat": "Static candidates require runtime verification; diagnostics explain unassessed scopes.",
    }
