"""Bounded explanations for selected and skipped pattern candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from anaxigraph.pattern_candidate_language import (
    candidate_capability_explanation,
    candidate_explanation,
    candidate_signal_explanation,
)
from anaxigraph.pattern_candidate_models import PatternCandidatePolicy
from anaxigraph.pattern_candidate_selection import CandidateDecision, candidate_decision
from anaxigraph.pattern_catalog_models import PatternCard, PatternCatalog
from anaxigraph.pattern_evidence import PatternEvidenceProjection, TargetEvidence
from anaxigraph.pattern_query import PATTERN_QUERY_LIMIT, PATTERN_QUERY_MAX_LIMIT
from anaxigraph.pattern_targets import PATTERN_TARGET_LEVELS

PATTERN_CANDIDATE_QUERY_VERSION = "pattern-candidate-query-v1"
PATTERN_CANDIDATE_SELECTIONS = frozenset({"selected", "skipped", "all"})


@dataclass(frozen=True, slots=True)
class PatternCandidateQuery:
    pattern: str
    target: str = ""
    level: str = ""
    selection: str = "skipped"
    limit: int = PATTERN_QUERY_LIMIT
    offset: int = 0
    include_evidence: bool = False

    def __post_init__(self) -> None:
        if not self.pattern:
            raise ValueError("pattern candidate query requires a pattern key")
        if len(self.pattern) > 2_000 or len(self.target) > 2_000:
            raise ValueError("pattern candidate query identity is too long")
        if self.level and self.level not in PATTERN_TARGET_LEVELS:
            raise ValueError(f"unsupported pattern target level: {self.level}")
        if self.selection not in PATTERN_CANDIDATE_SELECTIONS:
            raise ValueError(f"unsupported pattern candidate selection: {self.selection}")
        if not 1 <= self.limit <= PATTERN_QUERY_MAX_LIMIT:
            raise ValueError(
                f"pattern candidate query limit must be between one and {PATTERN_QUERY_MAX_LIMIT}"
            )
        if self.offset < 0:
            raise ValueError("pattern candidate query offset cannot be negative")

    def filters(self) -> dict[str, str | bool]:
        return {
            "pattern": self.pattern,
            "target": self.target,
            "level": self.level,
            "selection": self.selection,
            "include_evidence": self.include_evidence,
        }


def query_pattern_candidates(
    catalog: PatternCatalog,
    projection: PatternEvidenceProjection,
    request: PatternCandidateQuery,
    *,
    selected_target_keys: set[str],
    plan_ready: bool,
) -> dict[str, Any]:
    card = catalog.card(request.pattern)
    if card is None:
        raise ValueError(f"unknown pattern key: {request.pattern}")
    considered = _considered_targets(projection, card, request)
    items = _candidate_items(
        catalog, projection, card, considered, request, selected_target_keys, plan_ready
    )
    return _candidate_payload(catalog, projection, card, considered, items, request, plan_ready)


def _candidate_items(
    catalog: PatternCatalog,
    projection: PatternEvidenceProjection,
    card: PatternCard,
    considered: list[TargetEvidence],
    request: PatternCandidateQuery,
    selected_target_keys: set[str],
    plan_ready: bool,
) -> list[dict[str, Any]]:
    return [
        _candidate_item(
            card,
            evidence,
            projection,
            catalog_fingerprint=catalog.fingerprint,
            selected=evidence.target.key in selected_target_keys,
            plan_ready=plan_ready,
            include_evidence=request.include_evidence,
        )
        for evidence in considered
    ]


def _candidate_payload(
    catalog: PatternCatalog,
    projection: PatternEvidenceProjection,
    card: PatternCard,
    considered: list[TargetEvidence],
    items: list[dict[str, Any]],
    request: PatternCandidateQuery,
    plan_ready: bool,
) -> dict[str, Any]:
    counts = Counter(item["reason"] for item in items)
    selected_count = sum(bool(item["selected_for_evaluation"]) for item in items)
    filtered = [item for item in items if _selection_matches(item, request.selection)]
    filtered.sort(key=_candidate_order)
    page = filtered[request.offset : request.offset + request.limit]
    next_offset = request.offset + len(page)
    return {
        "contract_version": PATTERN_CANDIDATE_QUERY_VERSION,
        "repository_id": projection.repository_id,
        "snapshot_id": projection.snapshot_id,
        "plan_ready": plan_ready,
        "pattern": _pattern_summary(card, catalog.catalog_version),
        "filters": request.filters(),
        "targets_considered": len(considered),
        "selected_count": selected_count,
        "skipped_count": len(considered) - selected_count,
        "counts_by_reason": dict(sorted(counts.items())),
        "total": len(filtered),
        "returned": len(page),
        "offset": request.offset,
        "next_offset": next_offset if next_offset < len(filtered) else None,
        "omitted": max(0, len(filtered) - len(page)),
        "items": page,
    }


def empty_pattern_candidates(repository_id: int, request: PatternCandidateQuery) -> dict[str, Any]:
    return {
        "contract_version": PATTERN_CANDIDATE_QUERY_VERSION,
        "repository_id": repository_id,
        "snapshot_id": None,
        "plan_ready": False,
        "pattern": {"key": request.pattern},
        "filters": request.filters(),
        "targets_considered": 0,
        "selected_count": 0,
        "skipped_count": 0,
        "counts_by_reason": {},
        "total": 0,
        "returned": 0,
        "offset": request.offset,
        "next_offset": None,
        "omitted": 0,
        "items": [],
    }


def _considered_targets(
    projection: PatternEvidenceProjection,
    card: PatternCard,
    request: PatternCandidateQuery,
) -> list[TargetEvidence]:
    return [
        evidence
        for evidence in projection.items
        if evidence.target.level in card.scope_levels
        and (not request.level or evidence.target.level == request.level)
        and _target_matches(evidence, request.target)
    ]


def _target_matches(evidence: TargetEvidence, target: str) -> bool:
    if not target:
        return True
    value = evidence.target
    return target in {value.key, value.path, value.qualified_name}


def _candidate_item(
    card: PatternCard,
    evidence: TargetEvidence,
    projection: PatternEvidenceProjection,
    *,
    catalog_fingerprint: str,
    selected: bool,
    plan_ready: bool,
    include_evidence: bool,
) -> dict[str, Any]:
    decision = candidate_decision(
        card,
        evidence,
        projection,
        catalog_fingerprint,
        PatternCandidatePolicy(),
    )
    reason = _final_reason(decision, selected, plan_ready)
    candidate = decision.candidate
    observed = decision.observed
    item = {
        "target": evidence.target.as_dict(),
        "selected_for_evaluation": selected,
        "reason": reason,
        "priority": int(candidate.priority if candidate else 0),
        "selection_reasons": list(candidate.selection_reasons if candidate else ()),
        "missing_evidence": list(observed.missing if observed else ()),
        "capability_gaps": [
            item.gap for item in (observed.capabilities if observed else ()) if not item.complete
        ],
        "matched_signal_count": len(observed.matched if observed else ()),
        "counter_signal_count": len(observed.contradictions if observed else ()),
    }
    observations = (*observed.matched, *observed.contradictions) if observed else ()
    item["plain_language"] = candidate_explanation(
        item, card.name, [value.as_dict() for value in observations]
    )
    if include_evidence:
        item["details"] = _candidate_details(card, decision)
    return item


def _final_reason(decision: CandidateDecision, selected: bool, plan_ready: bool) -> str:
    if selected:
        return "selected"
    if decision.candidate is None:
        return decision.reason
    return "sparse_plan_bound" if plan_ready else "plan_not_ready"


def _candidate_details(card: PatternCard, decision: CandidateDecision) -> dict[str, Any]:
    observed = decision.observed
    signals = (*observed.problem, *observed.supporting, *observed.counter) if observed else ()
    return {
        "signals": [_signal_detail(signal) for signal in signals[:100]],
        "capabilities": [
            _capability_detail(item) for item in (observed.capabilities if observed else ())[:100]
        ],
        "semantic_questions": list(card.semantic_questions[:100]),
    }


def _signal_detail(signal: Any) -> dict[str, Any]:
    value = {
        "role": signal.role,
        "feature": signal.feature,
        "resolved_feature": signal.resolved_feature,
        "operator": signal.operator,
        "expected": signal.expected,
        "actual": signal.actual,
        "outcome": signal.outcome,
        "confidence": signal.confidence,
        "evidence": list(signal.evidence[:20]),
    }
    value["plain_language"] = candidate_signal_explanation(value)
    return value


def _capability_detail(item: Any) -> dict[str, Any]:
    value = {
        "fact": item.fact,
        "minimum": item.minimum,
        "best_level": item.best_level,
        "ratio": item.ratio,
        "complete": item.complete,
    }
    value["plain_language"] = candidate_capability_explanation(value)
    return value


def _selection_matches(item: dict[str, Any], selection: str) -> bool:
    if selection == "all":
        return True
    return bool(item["selected_for_evaluation"]) == (selection == "selected")


def _candidate_order(item: dict[str, Any]) -> tuple[int, int, int, str]:
    target = item["target"]
    return (
        0 if item["selected_for_evaluation"] else 1,
        -int(item["priority"]),
        PATTERN_TARGET_LEVELS.index(str(target["level"])),
        str(target["key"]),
    )


def _pattern_summary(card: PatternCard, catalog_version: str) -> dict[str, Any]:
    return {
        "key": card.stable_key,
        "name": card.name,
        "family": card.family,
        "kind": card.kind,
        "version": card.version,
        "catalog_version": catalog_version,
        "scope_levels": list(card.scope_levels),
    }
