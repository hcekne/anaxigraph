"""Conservative dead-code candidates with explicit static and dynamic-wiring gates."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.architecture_models import Finding
from anaxigraph.relationships import (
    AMBIGUOUS_INTERNAL,
    relationship_metadata,
    relationship_quality,
    resolution_status,
)


def dead_code_findings(
    connection: sqlite3.Connection,
    *,
    rule: Any,
    repository_id: int,
    files: list[dict[str, Any]],
    fan_in: Counter[int],
    relationship_evidence: list[dict[str, Any]],
    path_matcher: Callable[[str, str], bool],
) -> list[Finding]:
    if not files:
        return []
    context = _dead_code_context(connection, repository_id, rule, relationship_evidence)
    if context is None:
        return []
    candidates = [_file_candidate(item, rule, fan_in, context, path_matcher) for item in files]
    return [item for item in candidates if item is not None]


def _dead_code_context(
    connection: sqlite3.Connection,
    repository_id: int,
    rule: Any,
    relationships: list[dict[str, Any]],
) -> dict[str, Any] | None:
    quality = relationship_quality(relationships)
    if quality["dynamic"]:
        return None
    resolution_rate = quality["resolution_rate"]
    minimum = float(rule.params.get("minimum_resolution_rate", 0.95))
    if resolution_rate is None or resolution_rate < minimum:
        return None
    now = datetime.now(UTC)
    return {
        "resolution_rate": float(resolution_rate),
        "possible_incoming": _ambiguous_candidate_paths(relationships),
        "last_changes": _last_changes(connection, repository_id),
        "now": now,
        "cutoff": now - timedelta(days=int(rule.params.get("minimum_age_days", 90))),
    }


def _file_candidate(
    item: dict[str, Any],
    rule: Any,
    fan_in: Counter[int],
    context: dict[str, Any],
    path_matcher: Callable[[str, str], bool],
) -> Finding | None:
    path = str(item["path"])
    dynamic = _dynamic_wiring_evidence(item)
    last_change = _changed_at(context["last_changes"].get(path))
    if not _eligible(
        item,
        rule,
        path,
        fan_in,
        context["possible_incoming"],
        dynamic,
        last_change,
        context["cutoff"],
        path_matcher,
    ):
        return None
    return _candidate(
        rule,
        item,
        days=(context["now"] - last_change).days,
        resolution_rate=context["resolution_rate"],
        dynamic=dynamic,
    )


def _eligible(
    item: dict[str, Any],
    rule: Any,
    path: str,
    fan_in: Counter[int],
    possible_incoming: set[str],
    dynamic: dict[str, Any],
    last_change: datetime | None,
    cutoff: datetime,
    path_matcher: Callable[[str, str], bool],
) -> bool:
    return bool(
        item["artifact_type"] == "source"
        and not fan_in[int(item["artifact_id"])]
        and path not in possible_incoming
        and _in_rule_scope(path, rule, path_matcher)
        and not _configured_entrypoint(path, rule, path_matcher)
        and not _looks_like_entrypoint(path)
        and dynamic["capable"]
        and not dynamic["detected"]
        and last_change is not None
        and last_change <= cutoff
    )


def _dynamic_wiring_evidence(item: dict[str, Any]) -> dict[str, Any]:
    try:
        metadata = json.loads(item.get("metadata_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    ir = metadata.get("ir") if isinstance(metadata.get("ir"), dict) else {}
    levels = _capability_levels(ir.get("analyzer_capabilities"))
    facts = [item for item in ir.get("evidence_facts") or [] if isinstance(item, dict)]
    detected = [item for item in facts if item.get("fact") in {"entry_points", "registrations"}]
    parse_status = str(ir.get("parse_status") or item.get("analysis_status") or "")
    capable = _can_assess_dynamic_wiring(levels, parse_status)
    return {
        "capable": capable,
        "detected": detected,
        "levels": levels,
        "parse_status": parse_status or "unknown",
    }


def _candidate(
    rule: Any,
    item: dict[str, Any],
    *,
    days: int,
    resolution_rate: float,
    dynamic: dict[str, Any],
) -> Finding:
    path = str(item["path"])
    evidence = (
        "incoming_static_relationships=0",
        f"days_since_change={days}",
        f"internal_resolution_rate={resolution_rate:.4f}",
        f"entry_point_capability={dynamic['levels']['entry_points']}",
        f"registration_capability={dynamic['levels']['registrations']}",
        "detected_entry_points=0",
        "detected_registrations=0",
        f"parse_status={dynamic['parse_status']}",
    )
    confidence = round(min(0.82, 0.45 + 0.25 * resolution_rate + 0.1), 2)
    return Finding(
        stable_key=_stable_key(rule.rule_id, path),
        finding_type="possible_dead_code",
        severity=rule.severity,
        confidence=confidence,
        summary=f"{path} may no longer be used",
        explanation=(
            "Unused code makes a project harder to search and maintain. This file may still be "
            "loaded by configuration, a framework, or code that builds its name at runtime, so "
            "the finding is not permission to delete it."
        ),
        affected_artifacts=(path,),
        evidence=evidence,
        recommended_action=(
            "Before deleting it, search routes, events, templates, configuration, and runtime "
            "registrations for the file name. Remove it only after tests and a normal application "
            "start still work."
        ),
    )


def _ambiguous_candidate_paths(rows: list[dict[str, Any]]) -> set[str]:
    result = set()
    for row in rows:
        if resolution_status(row) == AMBIGUOUS_INTERNAL:
            result.update(relationship_metadata(row).get("candidate_paths") or ())
    return result


def _last_changes(connection: sqlite3.Connection, repository_id: int) -> dict[str, str]:
    return {
        str(row["path"]): str(row["last_change"])
        for row in connection.execute(
            """
            SELECT path, MAX(committed_at) AS last_change FROM git_changes
            WHERE repository_id = ? GROUP BY path
            """,
            (repository_id,),
        )
        if row["last_change"]
    }


def _changed_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _configured_entrypoint(path: str, rule: Any, path_matcher: Callable[[str, str], bool]) -> bool:
    patterns = rule.params.get("entry_points")
    if isinstance(patterns, str):
        patterns = [patterns]
    return bool(patterns and any(path_matcher(path, str(pattern)) for pattern in patterns))


def _in_rule_scope(path: str, rule: Any, path_matcher: Callable[[str, str], bool]) -> bool:
    patterns = rule.params.get("paths")
    if isinstance(patterns, str):
        patterns = [patterns]
    return not patterns or any(path_matcher(path, str(pattern)) for pattern in patterns)


def _capability_levels(value: Any) -> dict[str, str]:
    facts = value.get("facts") if isinstance(value, dict) else []
    available = {
        str(item.get("fact")): str(item.get("level"))
        for item in facts or []
        if isinstance(item, dict)
    }
    return {fact: available.get(fact, "unavailable") for fact in ("entry_points", "registrations")}


def _can_assess_dynamic_wiring(levels: dict[str, str], parse_status: str) -> bool:
    return bool(
        levels["entry_points"] != "unavailable"
        and levels["registrations"] != "unavailable"
        and parse_status not in {"fallback", "parse_error", "unavailable"}
    )


def _looks_like_entrypoint(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in {
        "__init__.py",
        "__main__.py",
        "main.py",
        "app.py",
        "index.js",
        "index.ts",
        "index.tsx",
        "main.js",
        "main.ts",
        "main.tsx",
        "conftest.py",
    }


def _stable_key(rule_id: str, path: str) -> str:
    import hashlib

    digest = hashlib.sha256(path.encode()).hexdigest()[:20]
    return f"{rule_id}:{digest}"
