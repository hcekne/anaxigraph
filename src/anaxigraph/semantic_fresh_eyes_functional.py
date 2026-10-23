"""Implementation-free functional projections and revision-qualified scope packets."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from anaxigraph.semantic_model_contract import SemanticAnalysisError

FUNCTIONAL_PROTOCOL = "fresh-eyes-recipe-v2"
FUNCTIONAL_BRIEF = "functional-brief-v2"
PLAN_PREFIX = "functional-v2|"
_TEXT_FIELDS = ("purpose",)
_LIST_FIELDS = (
    "actors",
    "observable_capabilities",
    "user_journeys",
    "external_interfaces",
    "non_functional_requirements",
    "compatibility_obligations",
    "non_goals",
    "unknowns",
)
_SOURCE_IDENTITY = re.compile(
    r"(?:^|[\s'\"`(])(?:(?:\.\.?/|src/|tests?/|packages?/|/(?:home|workspace|tmp|repo)/)"
    r"[^\s'\"`),;]*|(?:[\w@.+-]+/)*[\w.-]+\.(?:py|js|jsx|ts|tsx|rs|go|java|sqlite|db))"
    r"(?:$|[\s'\"`),:;])",
    re.IGNORECASE,
)
_SCOPE_FIELDS = (
    "id",
    "parent_id",
    "level",
    "purpose",
    "inputs",
    "outputs",
    "constraints",
    "dependencies",
    "origin",
    "confidence",
    "unknowns",
    "capability_ids",
)


def is_functional_plan(plan: dict[str, Any]) -> bool:
    return str(plan.get("interface_hash") or "").startswith(PLAN_PREFIX)


def functional_controls(token: str) -> str:
    return token.removeprefix(PLAN_PREFIX)


def functional_plan_options(plan: dict[str, Any]) -> tuple[int, int]:
    parts = functional_controls(str(plan.get("interface_hash") or "3:1")).split(":", 2)
    return max(3, min(5, int(parts[0]))), max(1, int(parts[1]) if len(parts) > 1 else 1)


def semantic_input_hash(contract: str, prompt_version: str, evidence: Any) -> str:
    """Functional evidence identity is independent of legacy file-description policies."""
    return semantic_digest(
        {"input_contract": contract, "prompt": prompt_version, "evidence": dict(evidence)}
    )


def semantic_digest(value: Any) -> str:
    """Hash functional evidence independently of portable-record format versions."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n"
    return hashlib.sha256(encoded.encode()).hexdigest()


def capability_projection(brief: dict[str, Any]) -> dict[str, Any]:
    """Allowlist observable behavior; never copy source evidence or arbitrary extra fields."""
    result = {name: str(brief.get(name) or "") for name in _TEXT_FIELDS}
    result.update({name: _strings(brief.get(name)) for name in _LIST_FIELDS})
    assert_functional(result)
    result["evidence"] = [
        f"capability:{semantic_digest(text)[:16]}" for text in result["observable_capabilities"]
    ] or ["purpose:product"]
    statements = result["observable_capabilities"] or [result["purpose"]]
    result["required_capabilities"] = [
        {"id": identifier, "statement": statement}
        for identifier, statement in zip(result["evidence"], statements)
    ]
    return result


def assert_functional(value: Any) -> None:
    if _SOURCE_IDENTITY.search(json.dumps(value, ensure_ascii=False)):
        raise SemanticAnalysisError(
            "Functional brief contains an internal source identity; refresh its behavioral "
            "description before running implementation-blind Fresh Eyes"
        )


def validate_hierarchy(value: dict[str, Any]) -> None:
    scopes = value["scopes"]
    by_id = {scope["id"]: scope for scope in scopes}
    if len(by_id) != len(scopes) or any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", key) for key in by_id
    ):
        raise SemanticAnalysisError("Functional scopes need unique simple letter/number identities")
    roots = [scope for scope in scopes if scope["level"] == "product"]
    if len(roots) != 1 or roots[0]["parent_id"]:
        raise SemanticAnalysisError("Functional hierarchy needs one parentless product scope")
    for scope in scopes:
        _validate_parent(scope, by_id)
        if any(key not in by_id for key in scope["dependencies"]):
            raise SemanticAnalysisError("Functional dependency refers to an unknown scope")
    levels = {scope["level"] for scope in scopes}
    if not {"product", "capability", "subsystem"}.issubset(levels):
        raise SemanticAnalysisError("Explore product, capability and functional subsystem levels")
    assert_functional(value)


def _validate_parent(scope: dict[str, Any], by_id: dict[str, Any]) -> None:
    if scope["level"] == "product":
        return
    parent = by_id.get(scope["parent_id"])
    required = "product" if scope["level"] == "capability" else "capability"
    if parent is None or parent["level"] != required:
        raise SemanticAnalysisError(f"A {scope['level']} scope needs a {required} parent")


def functional_scope_packet(brief: dict[str, Any], scope_id: str) -> dict[str, Any]:
    """Hash relevant functionality only; unrelated implementation edits cannot invalidate it."""
    by_id = {scope["id"]: scope for scope in brief["scopes"]}
    scope = by_id[scope_id]
    ancestors = []
    parent = scope["parent_id"]
    while parent:
        item = by_id[parent]
        ancestors.append({key: item[key] for key in _SCOPE_FIELDS if key != "capability_ids"})
        parent = item["parent_id"]
    packet = {
        "scope": {key: scope[key] for key in _SCOPE_FIELDS},
        "ancestors": ancestors,
        "functional_dependencies": [by_id[key] for key in scope["dependencies"]],
        "required_capabilities": [
            item for item in brief["required_capabilities"] if item["id"] in scope["capability_ids"]
        ],
    }
    packet["revision"] = semantic_digest(packet)
    return packet


def scope_key(scope_id: str, stage: str, slot: str = "") -> str:
    base = f"functional:{scope_id}:{stage}"
    return f"{base}:{slot}" if slot else base


def functional_boundary() -> dict[str, Any]:
    return {
        "mode": "implementation_blind",
        "projection": "purpose_capability_functional_subsystem",
        "withheld": [
            "raw_source",
            "source_paths",
            "current_module_names",
            "current_topology",
            "current_frameworks",
            "pattern_judgments",
            "implementation_evidence",
        ],
        "execution": "fresh_context_without_repository_tools_or_mounts",
        "unverified_external_execution": True,
    }


def _strings(value: Any) -> list[str]:
    return sorted({item for item in value or [] if isinstance(item, str) and item.strip()})
