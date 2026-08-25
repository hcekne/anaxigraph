"""Stable identities for sparse pattern planning, assessment, and critique."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from anaxigraph.pattern_candidate_models import PATTERN_CANDIDATE_CONTRACT_VERSION
from anaxigraph.pattern_evaluation_contract import (
    PATTERN_REVIEW_CONTRACT_VERSION,
    PATTERN_SCORE_CONTRACT_VERSION,
)
from anaxigraph.pattern_evidence import PATTERN_EVIDENCE_VERSION
from anaxigraph.semantic_freshness import (
    PATTERN_ASSESSMENT_CONTRACT,
    PATTERN_PLAN_CONTRACT,
    PATTERN_REVIEW_CONTRACT,
    semantic_input_hash,
)


def pattern_scope_key(candidate: dict[str, Any]) -> str:
    target_key = str((candidate.get("target") or {}).get("key") or "")
    pattern_key = str(candidate.get("pattern_key") or "")
    if not target_key or not pattern_key:
        raise ValueError("pattern candidate requires target and pattern identities")
    return f"{target_key}|pattern:{pattern_key}"


def pattern_plan_input_hash(
    prompt_version: str,
    *,
    snapshot_id: int,
    catalog_fingerprint: str,
    baseline_documents: list[tuple[Any, ...]],
) -> str:
    return semantic_input_hash(
        PATTERN_PLAN_CONTRACT,
        prompt_version,
        {
            "snapshot_id": snapshot_id,
            "catalog_fingerprint": catalog_fingerprint,
            "candidate_contract": PATTERN_CANDIDATE_CONTRACT_VERSION,
            "evidence_contract": PATTERN_EVIDENCE_VERSION,
            "score_contract": PATTERN_SCORE_CONTRACT_VERSION,
            "review_contract": PATTERN_REVIEW_CONTRACT_VERSION,
            "baseline_documents": baseline_documents,
        },
    )


def pattern_assessment_input_hash(candidate: dict[str, Any], prompt_version: str) -> str:
    return semantic_input_hash(
        PATTERN_ASSESSMENT_CONTRACT,
        prompt_version,
        {
            "candidate_fingerprint": candidate["input_fingerprint"],
            "score_contract": PATTERN_SCORE_CONTRACT_VERSION,
        },
    )


def pattern_review_input_hash(
    candidate: dict[str, Any],
    assessment: dict[str, Any],
    prompt_version: str,
) -> str:
    return semantic_input_hash(
        PATTERN_REVIEW_CONTRACT,
        prompt_version,
        {
            "candidate_fingerprint": candidate["input_fingerprint"],
            "assessment_fingerprint": _digest(assessment),
            "score_contract": PATTERN_SCORE_CONTRACT_VERSION,
            "review_contract": PATTERN_REVIEW_CONTRACT_VERSION,
        },
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
