"""Score one catalog card against one target before bounded plan selection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from anaxigraph.pattern_candidate_models import (
    PATTERN_CANDIDATE_CONTRACT_VERSION,
    CandidateSignal,
    PatternCandidate,
    PatternCandidatePolicy,
)
from anaxigraph.pattern_catalog_models import PatternCard
from anaxigraph.pattern_evidence import PatternEvidenceProjection, TargetEvidence
from anaxigraph.pattern_signals import (
    CapabilityCoverage,
    capability_coverage,
    observe_signal,
    semantic_evidence_available,
)

_AFFINITY_WORD = re.compile(r"[a-z0-9]+")
_AFFINITY_IGNORED = frozenset(
    {
        "architecture",
        "class",
        "code",
        "data",
        "feature",
        "function",
        "interface",
        "layer",
        "method",
        "module",
        "object",
        "package",
        "pattern",
        "public",
        "repository",
        "service",
        "shared",
        "stable",
        "state",
    }
)
_AFFINITY_FEATURES = frozenset(
    {
        "documentation.summary",
        "interfaces.public",
        "responsibilities.deterministic",
        "semantic.architecture_role",
        "semantic.extension_points",
        "semantic.public_contracts",
        "semantic.responsibilities",
    }
)


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate: PatternCandidate | None
    reason: str
    observed: CandidateEvidence | None = None


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    problem: tuple[CandidateSignal, ...]
    supporting: tuple[CandidateSignal, ...]
    counter: tuple[CandidateSignal, ...]
    capabilities: tuple[CapabilityCoverage, ...]
    semantic_reason: bool

    @property
    def matched(self) -> tuple[CandidateSignal, ...]:
        return tuple(
            item for item in (*self.problem, *self.supporting) if item.outcome == "matched"
        )

    @property
    def contradictions(self) -> tuple[CandidateSignal, ...]:
        return tuple(item for item in self.counter if item.outcome == "matched")

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.feature
                    for item in (*self.problem, *self.supporting, *self.counter)
                    if item.outcome == "unknown"
                }
            )
        )


def candidate_decision(
    card: PatternCard,
    evidence: TargetEvidence,
    projection: PatternEvidenceProjection,
    catalog_fingerprint: str,
    policy: PatternCandidatePolicy,
) -> CandidateDecision:
    observed = _candidate_evidence(card, evidence, projection)
    reasons = _selection_reasons(
        observed.problem,
        observed.supporting,
        observed.semantic_reason,
    )
    if observed.contradictions and not observed.matched and not observed.semantic_reason:
        return CandidateDecision(None, "counter_evidence", observed)
    if not reasons:
        return CandidateDecision(None, "no_positive_evidence", observed)
    priority = _priority(card, observed, evidence)
    if priority < policy.minimum_priority:
        return CandidateDecision(None, "below_priority", observed)
    return CandidateDecision(
        _selected_candidate(
            card,
            evidence,
            catalog_fingerprint,
            observed,
            reasons,
            priority,
        ),
        "selected",
        observed,
    )


def _candidate_evidence(
    card: PatternCard,
    evidence: TargetEvidence,
    projection: PatternEvidenceProjection,
) -> CandidateEvidence:
    problem = tuple(observe_signal("problem", item, evidence) for item in card.problem_signals)
    supporting = tuple(
        observe_signal("supporting", item, evidence) for item in card.supporting_evidence
    )
    counter = tuple(observe_signal("counter", item, evidence) for item in card.counter_evidence)
    capabilities = tuple(
        capability_coverage(evidence, projection.capability_contracts, requirement)
        for requirement in card.required_capabilities
    )
    semantic_unknown = any(
        item.outcome == "unknown" and item.feature.startswith("semantic.") for item in problem
    )
    return CandidateEvidence(
        problem,
        supporting,
        counter,
        capabilities,
        semantic_unknown and semantic_evidence_available(evidence),
    )


def _selected_candidate(
    card: PatternCard,
    evidence: TargetEvidence,
    catalog_fingerprint: str,
    observed: CandidateEvidence,
    reasons: tuple[str, ...],
    priority: int,
) -> PatternCandidate:
    observations = (*observed.problem, *observed.supporting, *observed.counter)
    return PatternCandidate(
        target=evidence.target,
        pattern_key=card.stable_key,
        pattern_version=card.version,
        snapshot_id=evidence.snapshot_id,
        priority=priority,
        target_input_fingerprint=evidence.input_fingerprint,
        catalog_fingerprint=catalog_fingerprint,
        selection_reasons=reasons,
        matched_signals=observed.matched,
        counter_signals=observed.contradictions,
        missing_evidence=observed.missing,
        capability_gaps=tuple(item.gap for item in observed.capabilities if not item.complete),
        semantic_questions=card.semantic_questions,
        input_fingerprint=_candidate_fingerprint(
            card,
            evidence,
            catalog_fingerprint,
            observations,
            observed.capabilities,
        ),
    )


def _selection_reasons(
    problem: tuple[CandidateSignal, ...],
    supporting: tuple[CandidateSignal, ...],
    semantic_reason: bool,
) -> tuple[str, ...]:
    reasons = []
    problem_matched = any(item.outcome == "matched" for item in problem)
    if problem_matched:
        reasons.append("problem_signal")
    if problem_matched and any(item.outcome == "matched" for item in supporting):
        reasons.append("supporting_evidence")
    if semantic_reason:
        reasons.append("semantic_question")
    return tuple(reasons)


def _priority(
    card: PatternCard,
    observed: CandidateEvidence,
    evidence: TargetEvidence,
) -> int:
    score = _signal_score(card.problem_signals, observed.problem, 28)
    score += _signal_score(card.supporting_evidence, observed.supporting, 14)
    score -= _signal_score(card.counter_evidence, observed.counter, 24)
    if observed.capabilities:
        score += 15 * sum(item.ratio for item in observed.capabilities) / len(observed.capabilities)
    if observed.semantic_reason:
        score += 10
    score += _semantic_affinity(card, evidence)
    return max(0, min(100, round(score)))


def _semantic_affinity(card: PatternCard, evidence: TargetEvidence) -> int:
    pattern_terms = {
        term
        for term in card.stable_key.split("-")
        if len(term) >= 4 and term not in _AFFINITY_IGNORED
    }
    if not pattern_terms:
        return 0
    values = [feature.value for feature in evidence.features if feature.name in _AFFINITY_FEATURES]
    words = set(_AFFINITY_WORD.findall(json.dumps(values, default=str).casefold()))
    return min(12, 6 * len(pattern_terms & words))


def _signal_score(
    signals: tuple[Any, ...], observed: tuple[CandidateSignal, ...], scale: int
) -> float:
    return sum(
        scale * signal.weight * observation.confidence
        for signal, observation in zip(signals, observed, strict=True)
        if observation.outcome == "matched"
    )


def _candidate_fingerprint(
    card: PatternCard,
    evidence: TargetEvidence,
    catalog_fingerprint: str,
    observations: tuple[CandidateSignal, ...],
    coverage: tuple[CapabilityCoverage, ...],
) -> str:
    value = {
        "contract_version": PATTERN_CANDIDATE_CONTRACT_VERSION,
        "catalog_fingerprint": catalog_fingerprint,
        "pattern": [card.stable_key, card.version],
        "target": evidence.target.key,
        "target_input_fingerprint": evidence.input_fingerprint,
        "observations": [item.as_dict() for item in observations],
        "capabilities": [
            [item.fact, item.minimum, item.supported, item.total, item.best_level]
            for item in coverage
        ],
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
