"""One actor-neutral projection of repository purpose and architectural intent."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from anaxigraph.architecture_charter_contract import (
    ARCHITECTURE_CHARTER_VERSION,
    CAPABILITY_BRIEF_VERSION,
)
from anaxigraph.architecture_charter_corrections import charter_claim
from anaxigraph.snapshot_provenance import dirty_snapshot_caveat, snapshot_provenance

_PROVENANCE_FIELDS = (
    "document_id",
    "provider",
    "model",
    "executor_id",
    "executor_model",
    "prompt_version",
    "created_at",
)


def architecture_charter(
    repository: dict[str, Any],
    overview: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    """Return the current agent-backed Charter or an honest static provisional view."""

    document = semantic.get("architecture_charter") or {}
    value = document.get("value") or {}
    if value.get("contract_version") == ARCHITECTURE_CHARTER_VERSION:
        charter = _saved_charter(repository, overview, document, value)
    else:
        charter = _provisional_charter(repository, overview)
    return _with_declared_context(charter, semantic.get("charter_corrections") or [])


def _saved_charter(
    repository: dict[str, Any],
    overview: dict[str, Any],
    document: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    snapshot_id = _snapshot_id(overview)
    provenance = snapshot_provenance(overview.get("snapshot"))
    state = "current" if document.get("status") == "current" else "stale"
    unknowns = [str(item.get("question") or "") for item in value.get("unknowns") or []]
    conflicts = [str(item.get("claim") or "") for item in value.get("conflicts") or []]
    caveats = _snapshot_caveats(provenance, [item for item in (*unknowns, *conflicts) if item])
    if state == "stale":
        caveats.insert(0, "The indexed evidence changed after this Charter was created.")
    return {
        **value,
        "identity": _identity(repository, snapshot_id, document.get("document_id")),
        "snapshot_id": snapshot_id,
        "snapshot": provenance,
        "state": state,
        "complete": state == "current",
        "readiness": {
            "state": state,
            "message": (
                "The coding agent completed this Charter from current indexed evidence."
                if state == "current"
                else "A saved Charter exists, but changed evidence still needs AI review."
            ),
        },
        "provenance": {key: document.get(key) for key in _PROVENANCE_FIELDS},
        "caveats": caveats,
    }


def _provisional_charter(repository: dict[str, Any], overview: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = _snapshot_id(overview)
    provenance = snapshot_provenance(overview.get("snapshot"))
    files = int(overview.get("files") or 0)
    name = str(repository.get("name") or "This repository")
    purpose = (
        f"Static analysis has mapped {files:,} files in {name}, but the software's externally "
        "visible purpose has not yet been confirmed by AI review."
    )
    evidence = [f"snapshot:{snapshot_id}", f"indexed_files:{files}"]
    unknowns = _provisional_unknowns()
    return {
        **_provisional_content(purpose, evidence, unknowns, overview),
        "identity": _identity(repository, snapshot_id, None),
        "snapshot_id": snapshot_id,
        "snapshot": provenance,
        "state": "provisional",
        "complete": False,
        "readiness": {
            "state": "provisional",
            "message": (
                "This Charter uses static facts only. Run Build understanding so a coding agent "
                "can explain purpose, behavior, flows, contracts, and uncertainty."
            ),
        },
        "provenance": {"source": "static_scan", "provider": None, "document_id": None},
        "caveats": _snapshot_caveats(
            provenance,
            [
                "Area placement describes where files sit; it does not prove what users experience.",
                "Dynamic runtime links may be absent from the extracted dependency graph.",
            ],
        ),
    }


def _snapshot_caveats(provenance: dict[str, Any], caveats: list[str]) -> list[str]:
    """Lead with the checkout warning so an unreproducible Charter says so first."""

    caveat = dirty_snapshot_caveat(provenance)
    return [caveat, *caveats] if caveat else list(caveats)


def _provisional_unknowns() -> list[dict[str, Any]]:
    return [
        _unknown(
            "Who uses this software and what outcome do they need?",
            "Actors and desired outcomes define whether the current design serves the product.",
        ),
        _unknown(
            "Which behaviors and interfaces must remain compatible?",
            "A safe architecture recommendation must preserve behavior callers rely on.",
        ),
        _unknown(
            "Which execution and data flows are most important?",
            "File links alone do not explain runtime behavior or business priority.",
        ),
    ]


def _provisional_content(
    purpose: str,
    evidence: list[str],
    unknowns: list[dict[str, Any]],
    overview: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": ARCHITECTURE_CHARTER_VERSION,
        "purpose": _claim(purpose, evidence, 0.35),
        "actors": [],
        "capabilities": [],
        "responsibilities": _responsibility_items(overview),
        "execution_flows": [],
        "public_contracts": [],
        "invariants": [],
        "extension_points": [],
        "patterns": [],
        "coherence_concerns": [],
        "unknowns": unknowns,
        "conflicts": [],
        "capability_brief": _provisional_brief(purpose, evidence, unknowns),
        "confidence": 0.35,
        "evidence": evidence,
    }


def _provisional_brief(
    purpose: str, evidence: list[str], unknowns: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "contract_version": CAPABILITY_BRIEF_VERSION,
        "purpose": purpose,
        "actors": [],
        "observable_capabilities": [],
        "user_journeys": [],
        "external_interfaces": [],
        "non_functional_requirements": [],
        "compatibility_obligations": [],
        "non_goals": [],
        "unknowns": [item["question"] for item in unknowns],
        "evidence": evidence,
        "confidence": 0.35,
    }


def _responsibility_items(overview: dict[str, Any]) -> list[dict[str, Any]]:
    hierarchy = (overview.get("group_hierarchies") or {}).get("current") or []
    return [
        {
            "key": str(item.get("key") or item.get("name")),
            "name": str(item.get("label") or item.get("name")),
            "statement": str(item.get("description") or _area_statement(item)),
            "related": [str(child.get("key") or child.get("name")) for child in item["children"]],
            "entry_points": [],
            "evidence": [
                f"architecture_area:{item.get('key') or item.get('name')}",
                f"indexed_files:{int(item.get('files') or 0)}",
            ],
            "counter_evidence": [],
            "confidence": 0.45,
        }
        for item in hierarchy
    ]


def _area_statement(item: dict[str, Any]) -> str:
    name = str(item.get("label") or item.get("name") or "This area")
    return f"{name} contains {int(item.get('files') or 0):,} indexed files."


def _unknown(question: str, why: str) -> dict[str, Any]:
    return {"question": question, "why_it_matters": why, "evidence_needed": ["AI code review"]}


def _claim(statement: str, evidence: list[str], confidence: float) -> dict[str, Any]:
    return {
        "statement": statement,
        "evidence": evidence,
        "counter_evidence": [],
        "confidence": confidence,
    }


def _snapshot_id(overview: dict[str, Any]) -> int:
    return int((overview.get("snapshot") or {}).get("id") or 0)


def _identity(repository: dict[str, Any], snapshot_id: int, document_id: Any) -> str:
    suffix = str(document_id) if document_id is not None else "provisional"
    return f"{ARCHITECTURE_CHARTER_VERSION}:{repository.get('id')}:{snapshot_id}:{suffix}"


def _with_declared_context(
    charter: dict[str, Any], corrections: list[dict[str, Any]]
) -> dict[str, Any]:
    result = deepcopy(charter)
    if corrections:
        revision = max(int(item.get("document_id") or 0) for item in corrections)
        result["identity"] = f"{result['identity']}:c{revision}"
    declared = []
    for correction in corrections:
        if not correction.get("active"):
            continue
        target = charter_claim(result, str(correction["section"]), str(correction["key"]))
        overlay = _declared_overlay(correction, target)
        if target:
            _apply_overlay(target, overlay)
        declared.append(overlay)
    result["declared_context"] = declared
    return result


def _declared_overlay(correction: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
    """Describe one active correction, naming refutation as its own overlay mode."""

    inferred = str(target.get("statement") or "") if target else ""
    refuted = str(correction.get("disposition") or "correct") == "refute"
    return {
        "document_id": correction.get("document_id"),
        "section": correction["section"],
        "key": correction["key"],
        "statement": correction["statement"],
        "inferred_statement": inferred or None,
        "mode": "refutation" if refuted else ("correction" if target else "addition"),
        "author": correction["author"],
        "rationale": correction["rationale"],
        "created_at": correction.get("created_at"),
    }


def _apply_overlay(target: dict[str, Any], overlay: dict[str, Any]) -> None:
    """Mark the inferred claim without deleting or rewriting the evidence behind it."""

    if overlay["mode"] == "refutation":
        target["disposition"] = "refuted"
    if overlay["statement"]:
        target["presented_statement"] = overlay["statement"]
    target["declared_overlay"] = overlay
