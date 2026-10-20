"""Independent analysis freshness, always qualified by checkout and saved snapshot."""

from __future__ import annotations

from typing import Any


def analysis_freshness(
    status: dict[str, Any], snapshot: dict[str, Any], path: str
) -> dict[str, Any]:
    patterns = status.get("patterns") or {}
    charter = status.get("architecture_charter") or {}
    taxonomy = status.get("taxonomy") or {}
    eligible = int(status.get("eligible_modules") or 0)
    mapping_ready = bool(
        eligible
        and status.get("current") == eligible
        and charter.get("status") == "current"
        and (not taxonomy.get("enabled") or taxonomy.get("ready"))
    )
    fresh = (status.get("freshness") or {}).get("fresh_eyes_plan")
    identity = {
        "snapshot_id": snapshot["id"],
        "commit_sha": snapshot.get("commit_sha"),
        "checkout_path": path,
    }
    return {
        "identity": identity,
        "structural": {
            **identity,
            "state": "indexed",
            "analyzed_at": snapshot.get("analysis_timestamp"),
        },
        "ai_mapping": {
            **identity,
            "state": _mapping_state(status, eligible, mapping_ready),
            "current": mapping_ready,
            "current_modules": status.get("current", 0),
            "eligible_modules": eligible,
            "charter_source_snapshot_id": charter.get("source_snapshot_id"),
        },
        "patterns": {
            **identity,
            "state": _pattern_state(status, patterns),
            "current": bool(
                patterns.get("planned") and patterns.get("finalized") == patterns.get("selected")
            ),
            "unit": "candidate-target pairs",
            "selected": patterns.get("selected", 0),
            "finalized": patterns.get("finalized", 0),
        },
        "fresh_eyes": {**identity, "state": fresh or "not_started", "current": fresh == "current"},
    }


def _state(enabled: Any, started: Any, current: Any) -> str:
    return (
        "current" if current else "pending" if started else "not_started" if enabled else "disabled"
    )


def _mapping_state(status: dict[str, Any], eligible: int, current: bool) -> str:
    if not eligible and (status.get("freshness") or {}).get("previous_semantic_snapshot_id"):
        return "stale"
    return _state(status.get("enabled"), eligible, current)


def _pattern_state(status: dict[str, Any], patterns: dict[str, Any]) -> str:
    if not patterns.get("planned") and (status.get("freshness") or {}).get(
        "previous_pattern_snapshot_id"
    ):
        return "stale"
    return _state(
        patterns.get("enabled") or patterns.get("planned"),
        patterns.get("planned"),
        patterns.get("planned") and patterns.get("finalized") == patterns.get("selected"),
    )
