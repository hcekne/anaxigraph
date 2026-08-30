"""Stable semantic-input identities, independent of the model that executes them."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

MODULE_INTRINSIC_CONTRACT = "module-intrinsic-v1"
MODULE_CONTEXT_CONTRACT = "module-context-v1"
GROUP_SYNTHESIS_CONTRACT = "group-synthesis-v1"
REPOSITORY_SYNTHESIS_CONTRACT = "repository-synthesis-v1"
TAXONOMY_PROPOSAL_CONTRACT = "taxonomy-proposal-v1"
TAXONOMY_REVIEW_CONTRACT = "taxonomy-review-v1"
PATTERN_PLAN_CONTRACT = "pattern-plan-v1"
PATTERN_ASSESSMENT_CONTRACT = "pattern-assessment-v1"
PATTERN_REVIEW_CONTRACT = "pattern-independent-review-v1"

# These response-envelope versions used the original flat input signature. Their module
# dossier payload is compatible with the current contract, so unchanged evidence can be
# proven reusable without copying or rewriting the preserved document.
LEGACY_INPUT_SCHEMA_VERSIONS = frozenset({"module-dossier-v4", "repository-understanding-v5"})


def semantic_input_hash(
    contract: str,
    prompt_version: str,
    evidence: Mapping[str, Any],
) -> str:
    """Hash semantic evidence and its stage contract, never its executor."""

    return semantic_digest(
        {
            "input_contract": contract,
            "prompt": prompt_version,
            "evidence": dict(evidence),
        }
    )


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
) -> bool:
    """Prove that a preserved pre-stable-signature record saw identical evidence."""

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
                **dict(variant),
            }
        )
        if hmac.compare_digest(str(record.get("input_hash") or ""), expected):
            return True
    return False
