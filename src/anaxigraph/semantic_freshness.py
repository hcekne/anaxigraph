"""Stable semantic-input identities, independent of the model that executes them."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.semantic_request_support import MAPPING_REQUIREMENTS, MAPPING_SCHEMA
from anaxigraph.understandability import AGENT_REVIEW_POLICY, UNDERSTANDABILITY_POLICY

MODULE_INTRINSIC_CONTRACT = "module-intrinsic-v1"
MODULE_CONTEXT_CONTRACT = "module-context-v1"
GROUP_SYNTHESIS_CONTRACT = "group-synthesis-v1"
REPOSITORY_SYNTHESIS_CONTRACT = "architecture-charter-v1"
TAXONOMY_PROPOSAL_CONTRACT = "taxonomy-proposal-v1"
TAXONOMY_REVIEW_CONTRACT = "taxonomy-review-v1"
TAXONOMY_STABILITY_CONTRACT = "taxonomy-stability-v1"
PATTERN_PLAN_CONTRACT = "pattern-plan-v1"
PATTERN_ASSESSMENT_CONTRACT = "pattern-assessment-v1"
PATTERN_REVIEW_CONTRACT = "pattern-independent-review-v1"
_AGENT_REVIEW_CONTRACTS = frozenset(
    {
        PATTERN_PLAN_CONTRACT,
        PATTERN_ASSESSMENT_CONTRACT,
        PATTERN_REVIEW_CONTRACT,
        "fresh-eyes-proposal-v1",
        "fresh-eyes-adjudication-v1",
        "fresh-eyes-comparison-v1",
        "fresh-eyes-review-v1",
    }
)

# These response envelopes used either the original flat signature or 0.5.x's
# three-field stable signature. Reuse requires identical evidence for that contract;
# preserved documents are never rewritten to pretend they used today's schema.
LEGACY_INPUT_SCHEMA_VERSIONS = frozenset({"module-dossier-v4", "repository-understanding-v5"})


def semantic_input_hash(
    contract: str,
    prompt_version: str,
    evidence: Mapping[str, Any],
) -> str:
    """Hash semantic evidence and its stage contract, never its executor."""

    value = {
        "input_contract": contract,
        "prompt": prompt_version,
        "mapping_contract": semantic_digest([MAPPING_SCHEMA, MAPPING_REQUIREMENTS]),
        "understandability_policy": semantic_digest(UNDERSTANDABILITY_POLICY),
        "evidence": dict(evidence),
    }
    # Review instructions must not invalidate the five-field descriptions they do not use.
    if contract in _AGENT_REVIEW_CONTRACTS or (
        contract in {MODULE_INTRINSIC_CONTRACT, MODULE_CONTEXT_CONTRACT}
        and evidence.get("detailed_reviews") is True
    ):
        value["agent_review_policy"] = semantic_digest(AGENT_REVIEW_POLICY)
    return semantic_digest(value)


def semantic_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def is_expired(created_at: str, max_age_days: int) -> bool:
    if max_age_days <= 0:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created < datetime.now(UTC) - timedelta(days=max_age_days)


def legacy_input_matches(
    record: Mapping[str, Any],
    evidence: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    prompt_version: str,
    input_contract: str | None = None,
) -> bool:
    """Prove that a preserved legacy record saw identical required evidence."""

    if str(record.get("prompt_version") or "") != prompt_version:
        return False
    if str(record.get("schema_version") or "") not in LEGACY_INPUT_SCHEMA_VERSIONS:
        return False
    variants = (evidence,) if isinstance(evidence, Mapping) else evidence
    for variant in variants:
        expected = semantic_digest(
            {
                "schema": record.get("schema_version"),
                "prompt": record.get("prompt_version"),
                "provider": record.get("provider"),
                "model": record.get("model"),
                "mapping_contract": semantic_digest([MAPPING_SCHEMA, MAPPING_REQUIREMENTS]),
                "understandability_policy": semantic_digest(UNDERSTANDABILITY_POLICY),
                **dict(variant),
            }
        )
        if hmac.compare_digest(str(record.get("input_hash") or ""), expected):
            return True
        stable = _legacy_v5_input(record, variant, prompt_version, input_contract)
        if stable is not None and hmac.compare_digest(str(record.get("input_hash") or ""), stable):
            return True
    return False


def _legacy_v5_input(
    record: Mapping[str, Any],
    evidence: Mapping[str, Any],
    prompt: str,
    contract: str | None,
) -> str | None:
    """Read 0.5.x's stable signature without claiming a newer detailed review."""

    if record.get("schema_version") != "repository-understanding-v5":
        return None
    contract = contract or {
        ("module", "intrinsic"): MODULE_INTRINSIC_CONTRACT,
        ("module", "context"): MODULE_CONTEXT_CONTRACT,
        ("group", "synthesis"): GROUP_SYNTHESIS_CONTRACT,
        ("repository", "synthesis"): REPOSITORY_SYNTHESIS_CONTRACT,
    }.get((record.get("scope_type"), record.get("document_kind")))
    if contract is None:
        return None
    original = dict(evidence)
    if contract in {MODULE_INTRINSIC_CONTRACT, MODULE_CONTEXT_CONTRACT}:
        if original.pop("detailed_reviews", False):
            return None
    if contract == MODULE_CONTEXT_CONTRACT:
        original.pop("intrinsic_source", None)
    return semantic_digest({"input_contract": contract, "prompt": prompt, "evidence": original})
