"""Shared continuous architecture-sidekick response for people and coding agents."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from anaxigraph.architecture_charter import architecture_charter
from anaxigraph.graph_contract import _with_response_telemetry
from anaxigraph.pattern_intelligence import PatternIntelligenceService
from anaxigraph.reassessment_advice import reassessment_advice
from anaxigraph.reassessment_evidence import reassessment_evidence
from anaxigraph.trend_service import scoped_change_coupling
from anaxigraph.understanding import SemanticEngine

ARCHITECTURE_REASSESSMENT_VERSION = "architecture-reassessment-v1"
_PATTERN_TARGET_LIMIT = 12


def architecture_reassessment(
    database: Any,
    *,
    repository_id: int,
    config: Any,
    from_snapshot_id: int | None = None,
    target_snapshot_id: int | None = None,
    goal: str = "",
) -> dict[str, Any]:
    """Explain the latest compatible saved change without creating workflow state."""

    started = time.perf_counter()
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    evidence = reassessment_evidence(
        database,
        repository_id,
        baseline_snapshot_id=from_snapshot_id,
        target_snapshot_id=target_snapshot_id,
    )
    target = evidence.get("target_snapshot")
    if target is None:
        return _finish(_not_indexed(repository_id), started)
    semantic = SemanticEngine(database).status(repository_id, config.semantic)
    charter = architecture_charter(repository, database.overview(repository_id), semantic)
    if evidence.get("baseline_snapshot") is None:
        return _finish(
            _without_baseline(repository_id, evidence, semantic, charter, goal),
            started,
        )
    changed_paths = _current_changed_paths(evidence)
    patterns = _patterns(database, repository_id, int(target["id"]), changed_paths)
    coupling = scoped_change_coupling(
        database,
        repository_id,
        int(target["id"]),
        changed_paths[:8],
    )
    advice = reassessment_advice(evidence, patterns=patterns, change_coupling=coupling)
    result = _result(repository_id, evidence, semantic, charter, advice, goal)
    return _finish(result, started)


def _result(
    repository_id: int,
    evidence: dict[str, Any],
    semantic: dict[str, Any],
    charter: dict[str, Any],
    advice: dict[str, Any],
    goal: str,
) -> dict[str, Any]:
    changed = evidence.get("module_changes") or []
    relationships = evidence.get("relationship_changes") or {}
    finding_changes = evidence.get("finding_changes") or []
    has_change = bool(
        changed
        or finding_changes
        or (relationships.get("counts") or {}).get("added")
        or (relationships.get("counts") or {}).get("removed")
    )
    state = _state(has_change, semantic, charter, evidence)
    core = {
        "contract_version": ARCHITECTURE_REASSESSMENT_VERSION,
        "repository_id": repository_id,
        "state": state,
        "goal": goal.strip(),
        "baseline_snapshot": evidence["baseline_snapshot"],
        "target_snapshot": evidence["target_snapshot"],
        "baseline_selection": evidence["baseline_selection"],
        "observed_change": _observed_change(evidence),
        "architectural_effects": advice["effects"],
        "recommendations": _recommendations(advice["effects"], state),
        "coverage": advice["coverage"],
        "semantic_refresh": semantic_refresh_projection(evidence, semantic),
        "architecture_charter": _charter_reference(charter),
        "history_evidence": advice["history_evidence"],
        "evidence_work": evidence.get("work") or {},
        "counts": advice["counts"],
        "safety": _safety(),
    }
    core["plain_language"] = _plain_language(core)
    return {"identity": _identity(core), **core}


def _not_indexed(repository_id: int) -> dict[str, Any]:
    core = {
        "contract_version": ARCHITECTURE_REASSESSMENT_VERSION,
        "repository_id": repository_id,
        "state": "not_indexed",
        "identity": f"{ARCHITECTURE_REASSESSMENT_VERSION}:{repository_id}:not-indexed",
        "baseline_snapshot": None,
        "target_snapshot": None,
        "observed_change": {"modules": [], "relationships": {}, "findings": []},
        "architectural_effects": [],
        "recommendations": [],
        "coverage": {},
        "semantic_refresh": {},
        "architecture_charter": None,
        "history_evidence": {},
        "evidence_work": {},
        "counts": {},
        "safety": _safety(),
    }
    core["plain_language"] = {
        "conclusion": "Scan the repository before asking what changed architecturally.",
        "what_to_do": ["Run the read-only scan, then ask for reassessment again."],
        "limits": [],
    }
    return core


def _without_baseline(
    repository_id: int,
    evidence: dict[str, Any],
    semantic: dict[str, Any],
    charter: dict[str, Any],
    goal: str,
) -> dict[str, Any]:
    core = {
        "contract_version": ARCHITECTURE_REASSESSMENT_VERSION,
        "repository_id": repository_id,
        "state": "no_compatible_baseline",
        "goal": goal.strip(),
        "baseline_snapshot": None,
        "target_snapshot": evidence["target_snapshot"],
        "baseline_selection": evidence["baseline_selection"],
        "observed_change": {"modules": [], "relationships": {}, "findings": []},
        "architectural_effects": [],
        "recommendations": [],
        "coverage": {},
        "semantic_refresh": semantic_refresh_projection(evidence, semantic),
        "architecture_charter": _charter_reference(charter),
        "history_evidence": {},
        "evidence_work": evidence.get("work") or {},
        "counts": {},
        "safety": _safety(),
    }
    core["plain_language"] = {
        "conclusion": "The current map is usable, but no earlier compatible saved map exists for a before/after verdict.",
        "what_to_do": [
            "Keep scanning normal edits; the next changed snapshot becomes comparable automatically."
        ],
        "limits": [
            "AnaxiGraph will not compare facts produced by incompatible analyzer contracts."
        ],
    }
    return {"identity": _identity(core), **core}


def _current_changed_paths(evidence: dict[str, Any]) -> list[str]:
    return [
        str(item["path"])
        for item in evidence.get("module_changes") or []
        if item.get("after") is not None and item.get("path")
    ]


def _patterns(
    database: Any, repository_id: int, snapshot_id: int, paths: list[str]
) -> list[dict[str, Any]]:
    targets = [f"module:{path}" for path in paths[:_PATTERN_TARGET_LIMIT]]
    return PatternIntelligenceService(database).query_targets(
        repository_id,
        snapshot_id,
        targets,
        limit_per_target=10,
    )


def _state(
    has_change: bool,
    semantic: dict[str, Any],
    charter: dict[str, Any],
    evidence: dict[str, Any],
) -> str:
    if not has_change:
        return "no_architectural_change"
    states = (evidence.get("semantic_scopes") or {}).get("states") or []
    pending = any(
        str(item.get("status") or "").startswith("pending")
        or str(item.get("status") or "").endswith("_current")
        and item.get("status") != "current"
        for item in states
    )
    if pending or (semantic.get("enabled") and charter.get("state") != "current"):
        return "semantic_refresh_pending"
    if charter.get("state") == "current":
        return "current"
    return "deterministic_only"


def _observed_change(evidence: dict[str, Any]) -> dict[str, Any]:
    relationships = evidence.get("relationship_changes") or {}
    return {
        "modules": evidence.get("module_changes") or [],
        "relationships": {
            "added": relationships.get("added") or [],
            "removed": relationships.get("removed") or [],
            "counts": relationships.get("counts") or {},
        },
        "findings": evidence.get("finding_changes") or [],
        "affected_context": evidence.get("affected_context") or {},
    }


def _recommendations(effects: list[dict[str, Any]], state: str) -> list[dict[str, Any]]:
    values = [
        {
            "effect_id": item["id"],
            "category": item["category"],
            "classification": item["classification"],
            "subject": item["subject"],
            "recommendation": item["recommendation"],
            "confidence": item["confidence"],
            "reasons_to_leave_alone": item["reasons_to_leave_alone"],
            "smallest_safe_follow_up": item["smallest_safe_follow_up"],
            "verification": item["verification"],
        }
        for item in effects
    ]
    if not values and state == "no_architectural_change":
        values.append(
            {
                "effect_id": None,
                "category": "responsibility",
                "classification": "coherent_no_change",
                "subject": "repository",
                "recommendation": "Leave the architecture alone; the comparison contains no supported structural change.",
                "confidence": {
                    "score": 0.82,
                    "label": "high",
                    "basis": "compatible saved snapshots",
                },
                "reasons_to_leave_alone": [
                    "No file, relationship, or finding delta supports a refactor."
                ],
                "smallest_safe_follow_up": "Run the intended behavior checks; do not create architecture work for its own sake.",
                "verification": "Refresh the map after the next real edit and compare again.",
            }
        )
    return values[:12]


def semantic_refresh_projection(
    evidence: dict[str, Any], semantic: dict[str, Any]
) -> dict[str, Any]:
    """Explain the smallest semantic scope implied by one structural comparison."""

    scopes = evidence.get("semantic_scopes") or {}
    changes = evidence.get("module_changes") or []
    return {
        "enabled": bool(semantic.get("enabled")),
        "snapshot_id": semantic.get("snapshot_id"),
        "state": semantic.get("state"),
        "semantically_ready": bool(semantic.get("semantically_ready")),
        "changed_modules": scopes.get("changed_modules") or [],
        "semantic_reread_modules": _semantic_reread_modules(changes),
        "text_only_modules": _text_only_modules(changes),
        "removed_modules": _removed_modules(changes),
        "affected_modules": scopes.get("affected_modules") or [],
        "affected_groups": scopes.get("affected_groups") or [],
        "scope_states": scopes.get("states") or [],
        "scope_state_counts": scopes.get("state_counts") or {},
        "comparison_caveat": evidence.get("comparison_caveat"),
        "recommended_action": semantic.get("recommended_action") or {},
        "full_repository_rerun_required": _full_refresh_required(semantic),
        "hash_policy": (
            "A file is reread when its path, parsed code-structure fingerprint, or public "
            "interface changes. Text-only changes whose parsed structure is identical reuse "
            "the saved file meaning. Changed relationships can refresh only neighboring context. "
            "A changed prompt, analysis contract, age policy, or explicit full review can "
            "separately invalidate a wider scope."
        ),
    }


def _full_refresh_required(semantic: dict[str, Any]) -> bool:
    eligible = int(semantic.get("eligible_modules") or 0)
    return eligible > 0 and int(semantic.get("pending") or 0) >= eligible


def _semantic_reread_modules(changes: list[dict[str, Any]]) -> list[str]:
    semantic_fields = {"presence", "path", "structural_hash", "public_interfaces_json"}
    return sorted(
        str(item.get("path") or "")
        for item in changes
        if item.get("after") is not None
        and semantic_fields.intersection(item.get("changed_fields") or [])
        and item.get("path")
    )


def _text_only_modules(changes: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(item.get("path") or "")
        for item in changes
        if item.get("after") is not None
        and "raw_hash" in (item.get("changed_fields") or [])
        and "structural_hash" not in (item.get("changed_fields") or [])
        and "public_interfaces_json" not in (item.get("changed_fields") or [])
        and "path" not in (item.get("changed_fields") or [])
        and item.get("path")
    )


def _removed_modules(changes: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(item.get("path") or "")
        for item in changes
        if item.get("after") is None and item.get("path")
    )


def _charter_reference(charter: dict[str, Any]) -> dict[str, Any]:
    purpose = charter.get("purpose") or {}
    return {
        "identity": charter.get("identity"),
        "snapshot_id": charter.get("snapshot_id"),
        "state": charter.get("state"),
        "complete": bool(charter.get("complete")),
        "purpose": purpose.get("statement") if isinstance(purpose, dict) else purpose,
        "confidence": charter.get("confidence"),
        "readiness": charter.get("readiness") or {},
        "caveats": list(charter.get("caveats") or [])[:8],
    }


def _plain_language(value: dict[str, Any]) -> dict[str, Any]:
    counts = value.get("counts") or {}
    modules = (value.get("evidence_work") or {}).get("changed_modules", 0)
    state = str(value.get("state") or "")
    conclusions = {
        "no_architectural_change": "The compatible saved maps show no architectural change; leave the structure alone.",
        "semantic_refresh_pending": f"AnaxiGraph found changes in {modules} file(s); static effects are current while the affected AI descriptions and Charter finish refreshing.",
        "current": f"AnaxiGraph reassessed {modules} changed file(s) and the affected architecture understanding is current.",
        "deterministic_only": f"AnaxiGraph reassessed {modules} changed file(s) from static evidence; AI meaning is unavailable or incomplete.",
    }
    return {
        "conclusion": conclusions.get(state, "AnaxiGraph compared two compatible saved maps."),
        "what_changed": [
            f"{modules} file(s) changed.",
            f"{counts.get('regressions', 0)} possible regression(s) and {counts.get('improvements', 0)} improvement(s) are explained below.",
        ],
        "what_to_do": [
            item["smallest_safe_follow_up"] for item in value.get("recommendations") or []
        ][:5],
        "limits": list((value.get("safety") or {}).get("caveats") or []),
    }


def _safety() -> dict[str, Any]:
    return {
        "target_repository_mutated": False,
        "decision_or_approval_state_created": False,
        "automatic_code_changes": False,
        "caveats": [
            "Static links can omit dynamic runtime wiring.",
            "A semantic suggestion is evidence-backed advice, not approval to merge, split, move, or delete code.",
            "Use focused behavior checks before and after the smallest coherent change.",
        ],
    }


def _identity(value: dict[str, Any]) -> str:
    stable = {
        "repository_id": value.get("repository_id"),
        "state": value.get("state"),
        "goal": value.get("goal"),
        "baseline": (value.get("baseline_snapshot") or {}).get("id"),
        "target": (value.get("target_snapshot") or {}).get("id"),
        "charter": (value.get("architecture_charter") or {}).get("identity"),
        "effects": [item.get("id") for item in value.get("architectural_effects") or []],
    }
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:20]
    return f"{ARCHITECTURE_REASSESSMENT_VERSION}:{digest}"


def _finish(value: dict[str, Any], started: float) -> dict[str, Any]:
    _with_response_telemetry(value, started, action="architecture_reassessment")
    return value
