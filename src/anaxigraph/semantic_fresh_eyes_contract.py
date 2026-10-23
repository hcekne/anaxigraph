"""Strict contracts for the fixed, implementation-blind architecture review recipe."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from anaxigraph.semantic_freshness import semantic_digest as semantic_digest
from anaxigraph.semantic_freshness import semantic_input_hash as semantic_input_hash
from anaxigraph.semantic_model_contract import (
    SemanticAnalysisError,
    SemanticResult,
)

FRESH_EYES_REVIEW_VERSION = "fresh-eyes-review-v1"
FRESH_EYES_PROPOSAL_VERSION = "fresh-eyes-proposal-v1"
FRESH_EYES_ADJUDICATION_VERSION = "fresh-eyes-adjudication-v1"
FRESH_EYES_COMPARISON_VERSION = "fresh-eyes-comparison-v1"
FRESH_EYES_PROTOCOL_VERSION = "fresh-eyes-recipe-v1"
FRESH_EYES_SCOPE = "fresh_eyes"
FRESH_EYES_PLAN_KEY = "plan"

ANY_EXECUTOR = "any"
FRESH_EYES_EXECUTORS = ("codex", "claude", ANY_EXECUTOR)
PROPOSAL_SCOPE_PREFIX = "proposal:"


def fresh_eyes_plan_options(plan: dict[str, Any]) -> tuple[int, int]:
    """Read proposal count and explicit rerun generation from one plan row."""

    proposal_text, generation_text, _executors = _plan_token_parts(plan)
    functional = str(plan.get("interface_hash") or "").startswith("functional-v2|")
    try:
        proposal_count = int(proposal_text)
        generation = int(generation_text) if generation_text else 1
    except ValueError:
        return (3 if functional else 2), 1
    return max(3 if functional else 1, min(5 if functional else 3, proposal_count)), max(
        1, generation
    )


def fresh_eyes_plan_executors(plan: dict[str, Any]) -> tuple[str, ...]:
    """Read the per-slot executor assignment; a two-part token records no assignment."""

    _proposals, _generation, executor_text = _plan_token_parts(plan)
    named = [item.strip().lower() for item in executor_text.split(",")]
    return tuple(item for item in named if item in FRESH_EYES_EXECUTORS)


def fresh_eyes_required_executor(executors: Sequence[str], scope_key: str) -> str | None:
    """Name the executor family pinned to one proposal slot, or None when any may take it."""

    key = str(scope_key)
    if ":proposal:" in key:
        key = "proposal:" + key.rsplit(":proposal:", 1)[1]
    if not key.startswith(PROPOSAL_SCOPE_PREFIX):
        return None
    slot = key[len(PROPOSAL_SCOPE_PREFIX) :]
    index = ord(slot) - ord("a") if len(slot) == 1 else -1
    if index < 0 or index >= len(executors) or executors[index] == ANY_EXECUTOR:
        return None
    return str(executors[index])


def fresh_eyes_plan_token(
    proposal_count: int,
    generation: int,
    executors: Sequence[str] = (),
    *,
    goal: str = "",
    functional: bool = True,
) -> str:
    """Encode small plan controls without adding model identity to semantic freshness.

    The executor assignment names who should take each proposal slot, not which model produced
    a result, so it stays out of every stage manifest and leaves stage input hashes unchanged.
    """

    families = proposal_executor_families(executors, proposal_count)
    token = f"{proposal_count}:{generation}"
    if goal:
        token = f"{token}:{','.join(families)}:{json.dumps(goal, ensure_ascii=True)}"
    elif families:
        token = f"{token}:{','.join(families)}"
    return f"functional-v2|{token}" if functional else token


def fresh_eyes_plan_goal(plan: dict[str, Any]) -> str:
    parts = str(plan.get("interface_hash") or "").removeprefix("functional-v2|").split(":", 3)
    return str(json.loads(parts[3])) if len(parts) == 4 else ""


def review_goal_manifest(goal: str) -> dict[str, str]:
    return {"text": goal, "fingerprint": semantic_digest(goal), "boundary": "repository_aware_only"}


def fresh_eyes_manifest_goal(manifests: list[dict[str, Any]]) -> str:
    return next(
        (
            item["manifest"]["review_goal"]["text"]
            for item in manifests
            if item["manifest"].get("review_goal")
        ),
        "",
    )


def proposal_executor_families(executors: Sequence[str], proposal_count: int) -> tuple[str, ...]:
    """Validate one executor family per proposal slot before any job is queued."""

    families = tuple(str(item).strip().lower() for item in executors if str(item).strip())
    if not families:
        return ()
    unknown = [item for item in families if item not in FRESH_EYES_EXECUTORS]
    if unknown:
        raise ValueError(
            "Fresh-eyes proposal executors must each be one of "
            f"{', '.join(FRESH_EYES_EXECUTORS)}; received {', '.join(unknown)}"
        )
    if len(families) != proposal_count:
        raise ValueError(
            "Fresh-eyes review needs one proposal executor per slot: "
            f"{proposal_count} proposals requested, {len(families)} executors named"
        )
    return families


def parse_proposal_executors(value: Any) -> tuple[str, ...]:
    """Read ``codex,claude`` from a CLI or MCP string, or a REST list, as executor families."""

    named = value.split(",") if isinstance(value, str) else list(value or ())
    return tuple(str(item).strip().lower() for item in named if str(item).strip())


def _plan_token_parts(plan: dict[str, Any]) -> tuple[str, str, str]:
    parts = str(plan.get("interface_hash") or "3").removeprefix("functional-v2|").split(":")
    padded = (*parts, "", "")
    return padded[0], padded[1], padded[2]


def attributed_verification(recommendation: dict[str, Any]) -> str:
    """Report a behavior check only when a tool ran it and said which revision it ran on.

    A plan without a result, or a result with no revision, stays unchecked: a structural
    improvement and a model's agreement are not observations of behavior.
    """

    result = ((recommendation or {}).get("transformation") or {}).get("result") or {}
    status = str(result.get("status") or "unverified")
    if status in {"passed", "failed"} and str(result.get("revision") or "").strip():
        return status
    return "unchecked"


def _reject_legacy_request(request: dict[str, Any]) -> None:
    if str(request.get("analysis_kind") or "") in {
        "fresh_proposal",
        "fresh_adjudication",
        "fresh_comparison",
        "fresh_review",
    }:
        raise SemanticAnalysisError(
            "Fresh Eyes executor work requires functional review v2; saved legacy results are read-only"
        )


def fresh_eyes_schema(request: dict[str, Any]) -> dict[str, Any] | None:
    from anaxigraph.semantic_fresh_eyes_v2_contract import schema_for

    schema = schema_for(request)
    if schema is None:
        _reject_legacy_request(request)
    return schema


def fresh_eyes_contract_name(request: dict[str, Any]) -> str | None:
    from anaxigraph.semantic_fresh_eyes_v2_contract import contract_name

    name = contract_name(request)
    if name is None:
        _reject_legacy_request(request)
    return name


def validated_fresh_eyes_response(
    value: Any,
    request: dict[str, Any],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> SemanticResult | None:
    from anaxigraph.semantic_fresh_eyes_v2_contract import validate_functional

    result = validate_functional(
        value, request, input_tokens=input_tokens, output_tokens=output_tokens
    )
    if result is None:
        _reject_legacy_request(request)
    return result
