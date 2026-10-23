"""Complete catalogue planning and optional local signal diagnostics."""

from __future__ import annotations

from typing import Any

from anaxigraph.pattern_candidate_models import (
    PATTERN_CANDIDATE_CONTRACT_VERSION,
    PatternCandidatePlan,
    PatternCandidatePolicy,
)
from anaxigraph.pattern_candidate_selection import CandidateDecision, candidate_decision
from anaxigraph.pattern_catalog_models import PatternCard, PatternCatalog
from anaxigraph.pattern_catalogue_plan import build_catalogue_assessment_plan
from anaxigraph.pattern_evidence import PatternEvidenceProjection, TargetEvidence


def build_pattern_candidate_plan(
    catalog: PatternCatalog,
    evidence: PatternEvidenceProjection,
    *,
    policy: PatternCandidatePolicy | None = None,
) -> PatternCandidatePlan:
    """Consider every loaded card; legacy placement limits cannot omit an assessment."""
    return build_catalogue_assessment_plan(catalog, evidence)


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
