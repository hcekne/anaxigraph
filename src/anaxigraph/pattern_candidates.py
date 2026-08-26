"""Select bounded pattern/target pairs before any semantic assessment work is created."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
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

    preferred: list[PatternCandidate] = []
    pattern_options: dict[str, list[PatternCandidate]] = defaultdict(list)
    qualified_by_pattern: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    eligible_pairs = 0
    omitted = 0
    policy = policy or PatternCandidatePolicy()
    catalog_fingerprint = catalog.fingerprint
    for target_evidence in _targets_parent_first(evidence.items):
        retained, qualified, target_pairs, target_skips, per_target_omitted = _target_selection(
            catalog,
            target_evidence,
            evidence,
            catalog_fingerprint,
            policy,
        )
        eligible_pairs += target_pairs
        skipped.update(target_skips)
        omitted += per_target_omitted
        preferred.extend(retained)
        for candidate in qualified:
            qualified_by_pattern[candidate.pattern_key] += 1
            _retain_pattern_option(pattern_options[candidate.pattern_key], candidate, policy)
    pool = _candidate_pool(preferred, pattern_options)
    selection_limit = min(policy.total_limit, len(preferred))
    selected = _bounded_selection(pool, policy, qualified_by_pattern, selection_limit)
    global_omitted = max(0, len(preferred) - len(selected))
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
) -> tuple[list[PatternCandidate], list[PatternCandidate], int, Counter[str], int]:
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
    return retained, candidates, eligible, skipped, omitted


def _retain_pattern_option(
    options: list[PatternCandidate],
    candidate: PatternCandidate,
    policy: PatternCandidatePolicy,
) -> None:
    limit = min(policy.total_limit, policy.per_target_limit + policy.per_pattern_reserve)
    options.append(candidate)
    options.sort(key=lambda item: (-item.priority, *_candidate_order(item)))
    del options[limit:]


def _candidate_pool(
    preferred: list[PatternCandidate],
    pattern_options: dict[str, list[PatternCandidate]],
) -> list[PatternCandidate]:
    by_identity = {(item.target.key, item.pattern_key): item for item in preferred}
    for options in pattern_options.values():
        for item in options:
            by_identity[(item.target.key, item.pattern_key)] = item
    return list(by_identity.values())


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
    qualified_by_pattern: Counter[str],
    limit: int,
) -> list[PatternCandidate]:
    if not candidates or limit <= 0:
        return []
    ranked = sorted(candidates, key=lambda item: (-item.priority, *_candidate_order(item)))
    by_level = _group_by_level(ranked)
    by_pattern = _group_by_pattern(ranked)
    state = _SelectionState(limit, policy.per_target_limit)
    _reserve_levels(by_level, policy.per_level_reserve, state)
    _reserve_patterns(by_pattern, qualified_by_pattern, policy.per_pattern_reserve, state)
    _fill_remaining(ranked, state)
    return state.retained


@dataclass
class _SelectionState:
    limit: int
    per_target_limit: int
    retained: list[PatternCandidate] = field(default_factory=list)
    identities: set[tuple[str, str]] = field(default_factory=set)
    target_counts: Counter[str] = field(default_factory=Counter)
    pattern_counts: Counter[str] = field(default_factory=Counter)

    @property
    def full(self) -> bool:
        return len(self.retained) >= self.limit

    def add(self, candidate: PatternCandidate) -> bool:
        identity = (candidate.target.key, candidate.pattern_key)
        if (
            self.full
            or identity in self.identities
            or self.target_counts[candidate.target.key] >= self.per_target_limit
        ):
            return False
        self.retained.append(candidate)
        self.identities.add(identity)
        self.target_counts[candidate.target.key] += 1
        self.pattern_counts[candidate.pattern_key] += 1
        return True


def _group_by_level(
    ranked: list[PatternCandidate],
) -> dict[str, list[PatternCandidate]]:
    return {
        level: [item for item in ranked if item.target.level == level]
        for level in PATTERN_TARGET_LEVELS
    }


def _group_by_pattern(
    ranked: list[PatternCandidate],
) -> dict[str, list[PatternCandidate]]:
    grouped: dict[str, list[PatternCandidate]] = defaultdict(list)
    for candidate in ranked:
        grouped[candidate.pattern_key].append(candidate)
    return grouped


def _reserve_levels(
    by_level: dict[str, list[PatternCandidate]],
    reserve: int,
    state: _SelectionState,
) -> None:
    for level in PATTERN_TARGET_LEVELS:
        if not reserve:
            break
        added = 0
        for candidate in by_level[level]:
            if state.add(candidate):
                added += 1
            if added >= reserve or state.full:
                break


def _reserve_patterns(
    by_pattern: dict[str, list[PatternCandidate]],
    qualified_by_pattern: Counter[str],
    reserve: int,
    state: _SelectionState,
) -> None:
    pattern_order = sorted(
        by_pattern,
        key=lambda key: (-by_pattern[key][0].priority, qualified_by_pattern[key], key),
    )
    for reserve_index in range(reserve):
        for pattern_key in pattern_order:
            if state.pattern_counts[pattern_key] > reserve_index or state.full:
                continue
            candidate = _best_available(by_pattern[pattern_key], state)
            if candidate is not None:
                state.add(candidate)


def _best_available(
    candidates: list[PatternCandidate], state: _SelectionState
) -> PatternCandidate | None:
    available = [
        item
        for item in candidates
        if (item.target.key, item.pattern_key) not in state.identities
        and state.target_counts[item.target.key] < state.per_target_limit
    ]
    if not available:
        return None
    return min(
        available,
        key=lambda item: (
            -item.priority,
            state.target_counts[item.target.key],
            *_candidate_order(item),
        ),
    )


def _fill_remaining(ranked: list[PatternCandidate], state: _SelectionState) -> None:
    for candidate in ranked:
        if state.full:
            break
        state.add(candidate)


def _candidate_order(item: PatternCandidate) -> tuple[int, str, int, str]:
    return (
        PATTERN_TARGET_LEVELS.index(item.target.level),
        item.target.key,
        -item.priority,
        item.pattern_key,
    )
