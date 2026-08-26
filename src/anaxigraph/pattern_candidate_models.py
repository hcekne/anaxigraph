"""Stable records for sparse deterministic pattern-candidate selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from anaxigraph.pattern_targets import PATTERN_TARGET_LEVELS, PatternTarget

PATTERN_CANDIDATE_CONTRACT_VERSION = "pattern-candidate-v1"
PATTERN_CANDIDATE_SELECTION_VERSION = "pattern-candidate-selection-v2"
PATTERN_SIGNAL_OUTCOMES = frozenset({"matched", "not_matched", "unknown"})
PATTERN_SIGNAL_ROLES = frozenset({"problem", "supporting", "counter"})


@dataclass(frozen=True, slots=True)
class PatternCandidatePolicy:
    per_target_limit: int = 4
    total_limit: int = 200
    minimum_priority: int = 25
    per_level_reserve: int = 4
    per_pattern_reserve: int = 2

    def __post_init__(self) -> None:
        if not 1 <= self.per_target_limit <= 100:
            raise ValueError("pattern candidate per-target limit must be between one and 100")
        if not 1 <= self.total_limit <= 100_000:
            raise ValueError("pattern candidate total limit must be between one and 100,000")
        if not 0 <= self.minimum_priority <= 100:
            raise ValueError("pattern candidate minimum priority must be between zero and 100")
        if not 0 <= self.per_level_reserve <= 100:
            raise ValueError("pattern candidate per-level reserve must be between zero and 100")
        if not 0 <= self.per_pattern_reserve <= 100:
            raise ValueError("pattern candidate per-pattern reserve must be between zero and 100")


@dataclass(frozen=True, slots=True)
class CandidateSignal:
    role: str
    feature: str
    resolved_feature: str
    operator: str
    expected: Any
    actual: Any
    outcome: str
    confidence: float
    evidence: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.role not in PATTERN_SIGNAL_ROLES:
            raise ValueError(f"unsupported candidate signal role: {self.role}")
        if self.outcome not in PATTERN_SIGNAL_OUTCOMES:
            raise ValueError(f"unsupported candidate signal outcome: {self.outcome}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("candidate signal confidence must be between zero and one")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    target: PatternTarget
    pattern_key: str
    pattern_version: int
    snapshot_id: int
    priority: int
    target_input_fingerprint: str
    catalog_fingerprint: str
    selection_reasons: tuple[str, ...]
    matched_signals: tuple[CandidateSignal, ...]
    counter_signals: tuple[CandidateSignal, ...]
    missing_evidence: tuple[str, ...]
    capability_gaps: tuple[str, ...]
    semantic_questions: tuple[str, ...]
    input_fingerprint: str
    contract_version: str = PATTERN_CANDIDATE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.pattern_key or self.pattern_version < 1:
            raise ValueError("pattern candidate requires a versioned pattern identity")
        if not 0 <= self.priority <= 100:
            raise ValueError("pattern candidate priority must be between zero and 100")
        if not self.selection_reasons:
            raise ValueError("pattern candidate requires at least one selection reason")
        if self.contract_version != PATTERN_CANDIDATE_CONTRACT_VERSION:
            raise ValueError(f"unsupported pattern candidate contract: {self.contract_version}")
        for value in (
            self.target_input_fingerprint,
            self.catalog_fingerprint,
            self.input_fingerprint,
        ):
            if len(value) != 64:
                raise ValueError("pattern candidate fingerprints must be SHA-256 values")

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "target": self.target.as_dict(),
            "pattern_key": self.pattern_key,
            "pattern_version": self.pattern_version,
            "snapshot_id": self.snapshot_id,
            "priority": self.priority,
            "target_input_fingerprint": self.target_input_fingerprint,
            "catalog_fingerprint": self.catalog_fingerprint,
            "input_fingerprint": self.input_fingerprint,
            "selection_reasons": list(self.selection_reasons),
            "matched_signals": [item.as_dict() for item in self.matched_signals],
            "counter_signals": [item.as_dict() for item in self.counter_signals],
            "missing_evidence": list(self.missing_evidence),
            "capability_gaps": list(self.capability_gaps),
            "semantic_questions": list(self.semantic_questions),
        }


@dataclass(frozen=True, slots=True)
class PatternCandidatePlan:
    repository_id: int
    snapshot_id: int
    evidence_fingerprint: str
    catalog_fingerprint: str
    candidates: tuple[PatternCandidate, ...]
    targets_considered: int
    eligible_pairs: int
    skipped_by_reason: tuple[tuple[str, int], ...]
    omitted_candidates: int = 0
    contract_version: str = PATTERN_CANDIDATE_CONTRACT_VERSION

    @property
    def fingerprint(self) -> str:
        value = {
            "contract_version": self.contract_version,
            "selection_version": PATTERN_CANDIDATE_SELECTION_VERSION,
            "repository_id": self.repository_id,
            "snapshot_id": self.snapshot_id,
            "evidence_fingerprint": self.evidence_fingerprint,
            "catalog_fingerprint": self.catalog_fingerprint,
            "candidates": [item.input_fingerprint for item in self.candidates],
            "skipped_by_reason": self.skipped_by_reason,
            "omitted_candidates": self.omitted_candidates,
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "selection_version": PATTERN_CANDIDATE_SELECTION_VERSION,
            "repository_id": self.repository_id,
            "snapshot_id": self.snapshot_id,
            "evidence_fingerprint": self.evidence_fingerprint,
            "catalog_fingerprint": self.catalog_fingerprint,
            "fingerprint": self.fingerprint,
            "targets_considered": self.targets_considered,
            "eligible_pairs": self.eligible_pairs,
            "selected": len(self.candidates),
            "omitted_candidates": self.omitted_candidates,
            "skipped_by_reason": dict(self.skipped_by_reason),
            "counts_by_level": {
                level: sum(item.target.level == level for item in self.candidates)
                for level in PATTERN_TARGET_LEVELS
            },
            "candidates": [item.as_dict() for item in self.candidates],
        }
