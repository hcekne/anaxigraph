"""Exhaustive catalogue consideration with bounded, evidence-led placement hints."""

from __future__ import annotations

from dataclasses import replace

from anaxigraph.pattern_candidate_models import PatternCandidatePlan
from anaxigraph.pattern_candidate_selection import (
    _candidate_evidence,
    _priority,
    _selected_candidate,
)
from anaxigraph.pattern_catalog_models import PatternCatalog
from anaxigraph.pattern_catalogue_contract import CATALOGUE_SELECTION_VERSION
from anaxigraph.pattern_evidence import PatternEvidenceProjection, TargetEvidence
from anaxigraph.pattern_targets import repository_target


def catalogue_root(projection: PatternEvidenceProjection) -> TargetEvidence:
    """Keep review scope distinct from the local scope where a pattern could be placed."""
    root = next((item for item in projection.items if item.target.level == "repository"), None)
    if root is not None:
        return root
    return TargetEvidence(
        target=repository_target("Repository architecture"),
        snapshot_id=projection.snapshot_id,
        input_fingerprint=projection.fingerprint,
        features=(),
        capability_fingerprints=tuple(sorted(projection.capability_contracts)),
    )


def build_catalogue_assessment_plan(
    catalog: PatternCatalog, projection: PatternEvidenceProjection
) -> PatternCandidatePlan:
    """One assessment per card; signal strength orders work but never removes a card."""
    root = replace(catalogue_root(projection), input_fingerprint=projection.fingerprint)
    fingerprint = catalog.fingerprint
    candidates = []
    for card in catalog.cards:
        observed = _candidate_evidence(card, root, projection)
        candidate = _selected_candidate(
            card,
            root,
            fingerprint,
            observed,
            ("catalogue_coverage",),
            _priority(card, observed, root),
        )
        candidates.append(candidate)
    return PatternCandidatePlan(
        repository_id=projection.repository_id,
        snapshot_id=projection.snapshot_id,
        evidence_fingerprint=projection.fingerprint,
        catalog_fingerprint=fingerprint,
        candidates=tuple(sorted(candidates, key=lambda item: (-item.priority, item.pattern_key))),
        targets_considered=len(projection.items),
        eligible_pairs=len(catalog.cards),
        skipped_by_reason=(),
        selection_version=CATALOGUE_SELECTION_VERSION,
        expected_pattern_ids=tuple(card.stable_key for card in catalog.cards),
    )


def placement_evidence(
    card, projection: PatternEvidenceProjection, *, limit: int = 8
) -> list[dict]:
    """Supply diverse local leads without creating a pattern-by-function work matrix."""
    choices = []
    for item in projection.items:
        if item.target.level not in card.scope_levels:
            continue
        observed = _candidate_evidence(card, item, projection)
        choices.append((_priority(card, observed, item), item, observed))
    choices.sort(key=lambda row: (-row[0], row[1].target.key))
    return [
        {
            "target": item.target.as_dict(),
            "priority": priority,
            "matched_signals": [signal.as_dict() for signal in observed.matched],
            "counter_signals": [signal.as_dict() for signal in observed.contradictions],
            "missing_evidence": list(observed.missing),
        }
        for priority, item, observed in choices[:limit]
    ]
