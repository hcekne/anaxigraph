"""Persistence for architecture rules, metrics, and finding lifecycle."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from anaxigraph.architecture_models import DEFAULT_RULES, Finding
from anaxigraph.clock import utc_now
from anaxigraph.config import RuleConfig


def _persist_rules(
    connection: sqlite3.Connection, repository_id: int, rules: tuple[RuleConfig, ...]
) -> None:
    for rule in rules:
        connection.execute(
            """
            INSERT INTO architecture_rules(
                repository_id, rule_id, rule_type, severity, description, source, enabled, config_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repository_id, rule_id) DO UPDATE SET
                rule_type = excluded.rule_type, severity = excluded.severity,
                description = excluded.description, source = excluded.source,
                enabled = excluded.enabled, config_json = excluded.config_json
            """,
            (
                repository_id,
                rule.rule_id,
                rule.rule_type,
                rule.severity,
                rule.description,
                "configured" if rule not in DEFAULT_RULES else "builtin",
                int(rule.enabled),
                json.dumps(rule.params, sort_keys=True),
            ),
        )


def _record_metrics(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    files: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    fan_in: Counter[int],
    fan_out: Counter[int],
    cycles: list[set[int]],
    findings: list[Finding],
) -> None:
    repository_metrics = {
        "total_loc": sum(int(item["lines_of_code"]) for item in files),
        "artifact_count": len(files),
        "symbol_count": len(symbols),
        "dependency_count": len(relationships),
        "average_degree": (
            (sum(fan_in.values()) + sum(fan_out.values())) / len(files) if files else 0
        ),
        "maximum_degree": max(
            (fan_in[item["artifact_id"]] + fan_out[item["artifact_id"]] for item in files),
            default=0,
        ),
        "cycle_count": len(cycles),
        "average_complexity": (
            sum(float(item["complexity"]) for item in files) / len(files) if files else 0
        ),
        "architecture_violation_count": sum(
            1 for finding in findings if finding.finding_type == "architecture_violation"
        ),
        "dead_code_candidate_count": sum(
            1 for finding in findings if finding.finding_type == "possible_dead_code"
        ),
    }
    for name, value in repository_metrics.items():
        connection.execute(
            """
            INSERT INTO metrics(snapshot_id, entity_type, entity_id, name, value)
            VALUES (?, 'repository', NULL, ?, ?)
            """,
            (snapshot_id, name, float(value)),
        )


def _update_finding_lifecycle(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    findings: list[Finding],
) -> None:
    now = utc_now()
    current_keys = {finding.stable_key for finding in findings}
    for finding in findings:
        existing = connection.execute(
            "SELECT id, status FROM findings WHERE repository_id = ? AND stable_key = ?",
            (repository_id, finding.stable_key),
        ).fetchone()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO findings(
                    repository_id, stable_key, finding_type, severity, confidence, summary,
                    explanation, affected_artifacts_json, evidence_json, recommended_action,
                    source, status, first_snapshot_id, last_snapshot_id,
                    first_detected_at, last_detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)
                """,
                (
                    repository_id,
                    finding.stable_key,
                    finding.finding_type,
                    finding.severity,
                    finding.confidence,
                    finding.summary,
                    finding.explanation,
                    json.dumps(finding.affected_artifacts),
                    json.dumps(finding.evidence),
                    finding.recommended_action,
                    finding.source,
                    snapshot_id,
                    snapshot_id,
                    now,
                    now,
                ),
            )
            finding_id = int(cursor.lastrowid)
        else:
            finding_id = int(existing["id"])
            status = "regressed" if existing["status"] == "resolved" else existing["status"]
            connection.execute(
                """
                UPDATE findings SET finding_type = ?, severity = ?, confidence = ?, summary = ?,
                    explanation = ?, affected_artifacts_json = ?, evidence_json = ?,
                    recommended_action = ?, source = ?, status = ?, last_snapshot_id = ?,
                    last_detected_at = ?, resolved_at = CASE WHEN ? = 'regressed' THEN NULL ELSE resolved_at END
                WHERE id = ?
                """,
                (
                    finding.finding_type,
                    finding.severity,
                    finding.confidence,
                    finding.summary,
                    finding.explanation,
                    json.dumps(finding.affected_artifacts),
                    json.dumps(finding.evidence),
                    finding.recommended_action,
                    finding.source,
                    status,
                    snapshot_id,
                    now,
                    status,
                    finding_id,
                ),
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO finding_occurrences(
                finding_id, snapshot_id, detected_at, evidence_json
            ) VALUES (?, ?, ?, ?)
            """,
            (finding_id, snapshot_id, now, json.dumps(finding.evidence)),
        )

    active_rows = connection.execute(
        """
        SELECT id, stable_key, status FROM findings
        WHERE repository_id = ? AND status NOT IN ('resolved', 'dismissed')
        """,
        (repository_id,),
    ).fetchall()
    for row in active_rows:
        if row["stable_key"] not in current_keys:
            connection.execute(
                "UPDATE findings SET status = 'resolved', resolved_at = ? WHERE id = ?",
                (now, row["id"]),
            )
