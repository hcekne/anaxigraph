"""Select architecture rules and findings relevant to an agent task scope."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.config import path_matches
from anaxigraph.finding_language import (
    finding_caveats,
    plain_language_contract,
)
from anaxigraph.persistence.row_decoding import _decode_json_value


def _applicable_rules(
    connection: sqlite3.Connection,
    repository_id: int,
    files: dict[int, dict[str, Any]],
    artifact_ids: set[int],
) -> list[dict[str, Any]]:
    paths = [files[item]["path"] for item in artifact_ids]
    result: list[dict[str, Any]] = []
    for row in connection.execute(
        """
        SELECT rule_id, rule_type, severity, description, source, config_json
        FROM architecture_rules WHERE repository_id = ? AND enabled = 1
        ORDER BY rule_id
        """,
        (repository_id,),
    ):
        item = dict(row)
        config = _decode_json_value(item.pop("config_json", "{}"))
        patterns = config.get("paths") if isinstance(config, dict) else None
        if not patterns or any(
            path_matches(path, pattern)
            for path in paths
            for pattern in ([patterns] if isinstance(patterns, str) else patterns)
        ):
            compact = {
                key: value
                for key, value in (config or {}).items()
                if value not in (None, "", [], {}, ())
            }
            result.append(
                {
                    "rule_id": item["rule_id"],
                    "type": item["rule_type"],
                    "severity": item["severity"],
                    **({"description": item["description"]} if item["description"] else {}),
                    "source": item["source"],
                    **({"parameters": compact} if compact else {}),
                }
            )
    return result


def _applicable_findings(
    connection: sqlite3.Connection,
    repository_id: int,
    files: dict[int, dict[str, Any]],
    artifact_ids: set[int],
    primary_ids: set[int],
) -> list[dict[str, Any]]:
    paths = {files[item]["path"] for item in artifact_ids}
    primary_paths = {files[item]["path"] for item in primary_ids}
    result = []
    for row in connection.execute(
        """
        SELECT id, stable_key, finding_type, severity, confidence, summary, explanation,
               status, affected_artifacts_json, evidence_json, recommended_action, source
        FROM findings WHERE repository_id = ? AND status NOT IN ('resolved', 'dismissed')
        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'error' THEN 1
                 WHEN 'warning' THEN 2 ELSE 3 END, last_detected_at DESC
        LIMIT 500
        """,
        (repository_id,),
    ):
        item, affected = _finding_value(row)
        relevant = affected & paths
        if relevant:
            result.append(_prioritized_finding(item, affected, relevant, primary_paths))
    return sorted(
        result,
        key=lambda item: (-int(item["priority_score"]), int(item["id"])),
    )[:12]


def _prioritized_finding(
    item: dict[str, Any],
    affected: set[str],
    relevant: set[str],
    primary_paths: set[str],
) -> dict[str, Any]:
    direct = affected & primary_paths
    severity_score = {
        "critical": 72,
        "error": 62,
        "warning": 42,
        "info": 20,
    }.get(str(item["severity"]), 20)
    item["affected_artifacts"] = sorted(affected)
    score = min(
        100,
        severity_score
        + (18 if direct else 7)
        + min(6, len(relevant) * 2)
        + round(float(item["confidence"] or 0) * 4),
    )
    item["priority_score"] = score
    reasons = [_severity_reason(str(item["severity"]))]
    reasons.append(
        "This applies directly to a likely implementation file."
        if direct
        else "This applies to a dependency connected to the task."
    )
    if len(affected) > 1:
        reasons.append(f"The finding covers {len(affected)} files.")
    item["priority_reasons"] = reasons
    item["priority_label"] = _priority_label(score)
    item["plain_language"] = plain_language_contract(
        item,
        priority_score=score,
        priority_label=item["priority_label"],
        priority_reasons=reasons,
        false_positive_conditions=finding_caveats(str(item["finding_type"])),
    )
    return item


def _severity_reason(severity: str) -> str:
    return {
        "critical": "The project's own rule says to check this before making more changes.",
        "error": "The project's own rule says this is probably an architecture problem.",
        "warning": "The project's own rule says this is worth a closer look.",
        "info": "The project's own rule records this as useful background information.",
    }.get(severity, "A repository rule asked AnaxiGraph to keep this visible.")


def _priority_label(score: int) -> str:
    if score >= 80:
        return "Urgent"
    if score >= 60:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def _finding_value(row: Any) -> tuple[dict[str, Any], set[str]]:
    item = dict(row)
    affected = set(_decode_json_value(item.pop("affected_artifacts_json", "[]")) or [])
    item["evidence"] = list(_decode_json_value(item.pop("evidence_json", "[]")) or [])
    return item, affected
