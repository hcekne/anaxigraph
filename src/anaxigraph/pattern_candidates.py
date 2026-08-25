"""Select bounded pattern/target pairs before any semantic assessment work is created."""

from __future__ import annotations

from collections import Counter
from typing import Any

from anaxigraph.pattern_candidate_models import (
    PATTERN_CANDIDATE_CONTRACT_VERSION,
    PatternCandidate,
    PatternCandidatePlan,
    PatternCandidatePolicy,
)
from anaxigraph.pattern_candidate_selection import CandidateDecision, candidate_decision
from anaxigraph.pattern_catalog_models import PatternCard, PatternCatalog
from anaxigraph.pattern_evidence import PatternEvidenceProjection, TargetEvidence
from anaxigraph.pattern_targets import PATTERN_TARGET_LEVELS


def build_pattern_candidate_plan(
    catalog: PatternCatalog,
    evidence: PatternEvidenceProjection,
    *,
    policy: PatternCandidatePolicy | None = None,
) -> PatternCandidatePlan:
    """Apply cheap deterministic filters and retain only bounded semantic work candidates."""

    selected: list[PatternCandidate] = []
    skipped: Counter[str] = Counter()
    eligible_pairs = 0
    omitted = 0
    policy = policy or PatternCandidatePolicy()
    catalog_fingerprint = catalog.fingerprint
    for target_evidence in _targets_parent_first(evidence.items):
        retained, target_pairs, target_skips, per_target_omitted = _target_selection(
            catalog,
            target_evidence,
            evidence,
            catalog_fingerprint,
            policy,
        )
        eligible_pairs += target_pairs
        skipped.update(target_skips)
        omitted += per_target_omitted
        selected.extend(retained)
    selected, global_omitted = _bounded_selection(selected, policy)
    if global_omitted:
        skipped["total_limit"] += global_omitted
        omitted += global_omitted
    selected.sort(key=_candidate_order)
    return PatternCandidatePlan(
        repository_id=evidence.repository_id,
        snapshot_id=evidence.snapshot_id,
        evidence_fingerprint=evidence.fingerprint,
        catalog_fingerprint=catalog_fingerprint,
        candidates=tuple(selected),
        targets_considered=len(evidence.items),
        eligible_pairs=eligible_pairs,
        skipped_by_reason=tuple(sorted(skipped.items())),
        omitted_candidates=omitted,
    )


def _target_selection(
    catalog: PatternCatalog,
    evidence: TargetEvidence,
    projection: PatternEvidenceProjection,
    catalog_fingerprint: str,
    policy: PatternCandidatePolicy,
) -> tuple[list[PatternCandidate], int, Counter[str], int]:
    candidates = []
    skipped: Counter[str] = Counter()
    eligible = 0
    for card in catalog.cards:
        if evidence.target.level not in card.scope_levels:
            continue
        eligible += 1
        decision = candidate_decision(
            card,
            evidence,
            projection,
            catalog_fingerprint,
            policy,
        )
        if decision.candidate is None:
            skipped[decision.reason] += 1
        else:
            candidates.append(decision.candidate)
    candidates.sort(key=lambda item: (-item.priority, item.pattern_key))
    retained = candidates[: policy.per_target_limit]
    omitted = len(candidates) - len(retained)
    if omitted:
        skipped["per_target_limit"] += omitted
    return retained, eligible, skipped, omitted


def explain_pattern_candidate(
    catalog: PatternCatalog,
    projection: PatternEvidenceProjection,
    *,
    target_key: str,
    pattern_key: str,
    policy: PatternCandidatePolicy | None = None,
) -> dict[str, Any]:
    """Explain one selected or skipped pair without storing the dense decision matrix."""

    card = catalog.card(pattern_key)
    evidence = next((item for item in projection.items if item.target.key == target_key), None)
    if card is None:
        raise ValueError(f"unknown pattern key: {pattern_key}")
    if evidence is None:
        raise ValueError(f"unknown pattern target: {target_key}")
    if evidence.target.level not in card.scope_levels:
        return _explanation(card, evidence, CandidateDecision(None, "wrong_scope"))
    decision = candidate_decision(
        card,
        evidence,
        projection,
        catalog.fingerprint,
        policy or PatternCandidatePolicy(),
    )
    return _explanation(card, evidence, decision)


def _explanation(
    card: PatternCard,
    evidence: TargetEvidence,
    decision: CandidateDecision,
) -> dict[str, Any]:
    observed = decision.observed
    signals = (*observed.problem, *observed.supporting, *observed.counter) if observed else ()
    return {
        "contract_version": PATTERN_CANDIDATE_CONTRACT_VERSION,
        "target": evidence.target.as_dict(),
        "pattern_key": card.stable_key,
        "pattern_version": card.version,
        "eligible_scope": evidence.target.level in card.scope_levels,
        "selected": decision.candidate is not None,
        "reason": decision.reason,
        "candidate": decision.candidate.as_dict() if decision.candidate else None,
        "signals": [item.as_dict() for item in signals],
        "missing_evidence": list(observed.missing if observed else ()),
        "capabilities": [
            {
                "fact": item.fact,
                "minimum": item.minimum,
                "supported": item.supported,
                "total": item.total,
                "best_level": item.best_level,
                "ratio": item.ratio,
            }
            for item in (observed.capabilities if observed else ())
        ],
    }


def _targets_parent_first(items: tuple[TargetEvidence, ...]) -> list[TargetEvidence]:
    return sorted(
        items,
        key=lambda item: (-PATTERN_TARGET_LEVELS.index(item.target.level), item.target.key),
    )


def _bounded_selection(
    candidates: list[PatternCandidate],
    policy: PatternCandidatePolicy,
) -> tuple[list[PatternCandidate], int]:
    if len(candidates) <= policy.total_limit:
        return candidates, 0
    ranked = sorted(candidates, key=lambda item: (-item.priority, *_candidate_order(item)))
    by_level = {
        level: [item for item in ranked if item.target.level == level]
        for level in PATTERN_TARGET_LEVELS
    }
    retained = []
    identities = set()
    for index in range(policy.per_level_reserve):
        for level in PATTERN_TARGET_LEVELS:
            if len(retained) >= policy.total_limit or index >= len(by_level[level]):
                continue
            candidate = by_level[level][index]
            retained.append(candidate)
            identities.add((candidate.target.key, candidate.pattern_key))
    for candidate in ranked:
        identity = (candidate.target.key, candidate.pattern_key)
        if len(retained) >= policy.total_limit:
            break
        if identity not in identities:
            retained.append(candidate)
            identities.add(identity)
    return retained, len(candidates) - len(retained)


def _candidate_order(item: PatternCandidate) -> tuple[int, str, int, str]:
    return (
        PATTERN_TARGET_LEVELS.index(item.target.level),
        item.target.key,
        -item.priority,
        item.pattern_key,
    )
