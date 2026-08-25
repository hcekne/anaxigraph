"""Persistence for architecture rules, metrics, and finding lifecycle."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any

from anaxigraph.architecture_models import DEFAULT_RULES, Finding
from anaxigraph.clock import utc_now
from anaxigraph.config import RuleConfig

FINDING_OBSERVATION_VERSION = "finding-observations-v1"


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


def _record_evaluation(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    files: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    fan_in: Counter[int],
    fan_out: Counter[int],
    cycles: list[set[int]],
    findings: list[Finding],
    manage_lifecycle: bool,
) -> None:
    _record_metrics(
        connection,
        snapshot_id=snapshot_id,
        files=files,
        relationships=relationships,
        symbols=symbols,
        fan_in=fan_in,
        fan_out=fan_out,
        cycles=cycles,
        findings=findings,
    )
    _mark_finding_observations(connection, snapshot_id)
    recorder = (
        _update_finding_lifecycle if manage_lifecycle else _record_historical_finding_occurrences
    )
    recorder(
        connection,
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        findings=findings,
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
            finding_id = _refresh_current_finding(
                connection, existing, finding, snapshot_id=snapshot_id, detected_at=now
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


def _refresh_current_finding(
    connection: sqlite3.Connection,
    existing: sqlite3.Row,
    finding: Finding,
    *,
    snapshot_id: int,
    detected_at: str,
) -> int:
    finding_id = int(existing["id"])
    status = _reactivated_status(
        connection,
        finding_id=finding_id,
        snapshot_id=snapshot_id,
        current_status=str(existing["status"]),
    )
    connection.execute(
        """
        UPDATE findings SET finding_type = ?, severity = ?, confidence = ?, summary = ?,
            explanation = ?, affected_artifacts_json = ?, evidence_json = ?,
            recommended_action = ?, source = ?, status = ?, last_snapshot_id = ?,
            last_detected_at = ?, resolved_at = CASE
                WHEN ? IN ('new', 'regressed') THEN NULL ELSE resolved_at END
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
            detected_at,
            status,
            finding_id,
        ),
    )
    return finding_id


def _record_historical_finding_occurrences(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    findings: list[Finding],
) -> None:
    """Record what an old frame contained without changing the live finding queue."""

    detected_at = _snapshot_time(connection, snapshot_id)
    for finding in findings:
        existing = connection.execute(
            "SELECT id FROM findings WHERE repository_id = ? AND stable_key = ?",
            (repository_id, finding.stable_key),
        ).fetchone()
        if existing is None:
            finding_id = _insert_historical_finding(
                connection,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                detected_at=detected_at,
                finding=finding,
            )
        else:
            finding_id = int(existing["id"])
        connection.execute(
            """
            INSERT OR REPLACE INTO finding_occurrences(
                finding_id, snapshot_id, detected_at, evidence_json
            ) VALUES (?, ?, ?, ?)
            """,
            (finding_id, snapshot_id, detected_at, json.dumps(finding.evidence)),
        )


def _insert_historical_finding(
    connection: sqlite3.Connection,
    *,
    repository_id: int,
    snapshot_id: int,
    detected_at: str,
    finding: Finding,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO findings(
            repository_id, stable_key, finding_type, severity, confidence, summary,
            explanation, affected_artifacts_json, evidence_json, recommended_action,
            source, status, first_snapshot_id, last_snapshot_id,
            first_detected_at, last_detected_at, resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'resolved', ?, ?, ?, ?, ?)
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
            detected_at,
            detected_at,
            detected_at,
        ),
    )
    return int(cursor.lastrowid)


def _mark_finding_observations(connection: sqlite3.Connection, snapshot_id: int) -> None:
    row = connection.execute(
        "SELECT metadata_json FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    if row is None:
        return
    metadata = json.loads(row["metadata_json"] or "{}")
    metadata["finding_observation_version"] = FINDING_OBSERVATION_VERSION
    connection.execute(
        "UPDATE snapshots SET metadata_json = ? WHERE id = ?",
        (json.dumps(metadata, sort_keys=True), snapshot_id),
    )


def _snapshot_time(connection: sqlite3.Connection, snapshot_id: int) -> str:
    row = connection.execute(
        """
        SELECT COALESCE(commit_timestamp, analysis_timestamp) AS observed_at
        FROM snapshots WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    return str(row["observed_at"]) if row and row["observed_at"] else utc_now()


def _reactivated_status(
    connection: sqlite3.Connection,
    *,
    finding_id: int,
    snapshot_id: int,
    current_status: str,
) -> str:
    if current_status != "resolved":
        return current_status
    prior_live = connection.execute(
        """
        SELECT 1 FROM finding_occurrences occurrence
        JOIN snapshots snapshot ON snapshot.id = occurrence.snapshot_id
        WHERE occurrence.finding_id = ? AND snapshot.snapshot_kind = 'working_tree'
        LIMIT 1
        """,
        (finding_id,),
    ).fetchone()
    if prior_live or _has_retained_resolution(connection, finding_id, snapshot_id):
        return "regressed"
    return "new"


def _has_retained_resolution(
    connection: sqlite3.Connection, finding_id: int, snapshot_id: int
) -> bool:
    rows = connection.execute(
        """
        WITH RECURSIVE lineage(id, base_snapshot_id, sequence, metadata_json, depth) AS (
            SELECT id, base_snapshot_id, sequence, metadata_json, 0
            FROM snapshots WHERE id = ?
            UNION ALL
            SELECT parent.id, parent.base_snapshot_id, parent.sequence,
                   parent.metadata_json, lineage.depth + 1
            FROM snapshots parent JOIN lineage ON parent.id = lineage.base_snapshot_id
            WHERE lineage.depth < 2500
        )
        SELECT lineage.id, lineage.metadata_json,
               EXISTS(
                   SELECT 1 FROM finding_occurrences occurrence
                   WHERE occurrence.finding_id = ? AND occurrence.snapshot_id = lineage.id
               ) AS observed
        FROM lineage ORDER BY lineage.sequence, lineage.id
        """,
        (snapshot_id, finding_id),
    ).fetchall()
    seen = False
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        if metadata.get("finding_observation_version") != FINDING_OBSERVATION_VERSION:
            continue
        if row["observed"]:
            seen = True
        elif seen:
            return True
    return False
