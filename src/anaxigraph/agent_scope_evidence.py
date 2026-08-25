"""Select architecture rules and findings relevant to an agent task scope."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from anaxigraph.config import path_matches


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
        config = _json(item.pop("config_json", "{}"))
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
               status, affected_artifacts_json, evidence_json, recommended_action
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
    item["priority_score"] = min(
        100,
        severity_score
        + (18 if direct else 7)
        + min(6, len(relevant) * 2)
        + round(float(item["confidence"] or 0) * 4),
    )
    reasons = [f"{item['severity']} severity"]
    reasons.append(
        "affects a primary task file" if direct else "affects a dependency in the task context"
    )
    if len(affected) > 1:
        reasons.append(f"spans {len(affected)} files")
    item["priority_reasons"] = reasons
    return item


def _finding_value(row: Any) -> tuple[dict[str, Any], set[str]]:
    item = dict(row)
    affected = set(_json(item.pop("affected_artifacts_json", "[]")) or [])
    item["evidence"] = list(_json(item.pop("evidence_json", "[]")) or [])
    return item, affected


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None
