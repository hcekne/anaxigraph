"""Evaluate declarative pattern signals against one pattern-neutral evidence target."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anaxigraph.analyzer_capabilities import CAPABILITY_LEVELS
from anaxigraph.pattern_candidate_models import CandidateSignal
from anaxigraph.pattern_catalog_models import CapabilityRequirement, EvidenceSignal
from anaxigraph.pattern_evidence import PatternFeature, TargetEvidence

PATTERN_FEATURE_ALIASES = {
    "graph.callers": "graph.fan_in",
    "graph.collaborators": "graph.fan_out",
    "graph.external_collaborators": "graph.fan_out",
    "syntax.async_calls": "syntax.async_behavior",
    "syntax.error_handlers": "syntax.error_handling",
    "syntax.mutations": "syntax.mutation",
    "test.coverage": "coverage.line",
    "test.external_dependencies": "syntax.test_relationships",
}
_COMPARISONS = {
    "eq": lambda actual, expected: actual == expected,
    "neq": lambda actual, expected: actual != expected,
    "gt": lambda actual, expected: actual > expected,
    "gte": lambda actual, expected: actual >= expected,
    "lt": lambda actual, expected: actual < expected,
    "lte": lambda actual, expected: actual <= expected,
}


@dataclass(frozen=True, slots=True)
class CapabilityCoverage:
    fact: str
    minimum: str
    supported: int
    total: int
    best_level: str

    @property
    def ratio(self) -> float:
        return self.supported / max(1, self.total)

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.supported == self.total

    @property
    def gap(self) -> str:
        return (
            f"{self.fact}:{self.minimum} "
            f"({self.supported}/{self.total or 1}, best={self.best_level})"
        )


def capability_coverage(
    evidence: TargetEvidence,
    contracts: dict[str, dict[str, Any]],
    requirement: CapabilityRequirement,
) -> CapabilityCoverage:
    aggregate = evidence.feature("analyzer.capability_coverage")
    if aggregate is not None:
        return _aggregate_capability(aggregate, requirement)
    levels = [
        _contract_level(contracts.get(key), requirement.fact)
        for key in evidence.capability_fingerprints
    ]
    supported = sum(_meets(level, requirement.minimum) for level in levels)
    return CapabilityCoverage(
        requirement.fact,
        requirement.minimum,
        supported,
        len(levels),
        _best_level(levels),
    )


def observe_signal(
    role: str,
    signal: EvidenceSignal,
    evidence: TargetEvidence,
) -> CandidateSignal:
    resolved = PATTERN_FEATURE_ALIASES.get(signal.feature, signal.feature)
    feature = evidence.feature(resolved)
    if feature is None:
        return CandidateSignal(
            role=role,
            feature=signal.feature,
            resolved_feature=resolved,
            operator=signal.operator,
            expected=signal.value,
            actual=None,
            outcome="unknown",
            confidence=0,
        )
    outcome = _outcome(signal.operator, feature, signal.value)
    return CandidateSignal(
        role=role,
        feature=signal.feature,
        resolved_feature=resolved,
        operator=signal.operator,
        expected=signal.value,
        actual=_compact(feature.value),
        outcome=outcome,
        confidence=feature.confidence,
        evidence=tuple(item.as_dict() for item in feature.evidence[:10]),
    )


def semantic_evidence_available(evidence: TargetEvidence) -> bool:
    dossier = evidence.feature("semantic.dossier")
    if dossier is not None and dossier.availability != "unavailable" and bool(dossier.value):
        return True
    coverage = evidence.feature("semantic.coverage")
    return bool(
        coverage is not None
        and coverage.availability != "unavailable"
        and float(coverage.value or 0) > 0
    )


def _aggregate_capability(
    feature: PatternFeature,
    requirement: CapabilityRequirement,
) -> CapabilityCoverage:
    detail = (feature.value or {}).get(requirement.fact) or {}
    levels = detail.get("levels") or {}
    total = int(detail.get("total") or sum(int(value) for value in levels.values()))
    supported = sum(
        int(count) for level, count in levels.items() if _meets(str(level), requirement.minimum)
    )
    return CapabilityCoverage(
        requirement.fact,
        requirement.minimum,
        supported,
        total,
        _best_level([str(level) for level, count in levels.items() if int(count) > 0]),
    )


def _contract_level(contract: dict[str, Any] | None, fact: str) -> str:
    if contract is None:
        return "unavailable"
    return next(
        (str(item["level"]) for item in contract.get("facts") or () if item["fact"] == fact),
        "unavailable",
    )


def _meets(actual: str, minimum: str) -> bool:
    return CAPABILITY_LEVELS.index(actual) >= CAPABILITY_LEVELS.index(minimum)


def _best_level(levels: list[str]) -> str:
    return max(levels, key=CAPABILITY_LEVELS.index, default="unavailable")


def _outcome(operator: str, feature: PatternFeature, expected: Any) -> str:
    if operator == "available":
        return _matched(feature.availability != "unavailable")
    if operator == "unavailable":
        return _matched(feature.availability == "unavailable")
    if feature.availability == "unavailable" or feature.value is None:
        return "unknown"
    if operator == "exists":
        return _matched(_exists(feature.value))
    if operator == "contains":
        return _matched(_contains(feature.value, expected))
    if operator.startswith("count_"):
        count = _count(feature.value)
        if count is None:
            return "unknown"
        boundary = _number(expected)
        if boundary is None:
            return "unknown"
        return _matched(count >= boundary if operator == "count_gte" else count <= boundary)
    actual = _number(feature.value)
    boundary = _number(expected)
    if operator in _COMPARISONS and actual is not None and boundary is not None:
        return _matched(_COMPARISONS[operator](actual, boundary))
    if operator in {"eq", "neq"}:
        return _matched(_COMPARISONS[operator](feature.value, expected))
    return "unknown"


def _matched(value: bool) -> str:
    return "matched" if value else "not_matched"


def _exists(value: Any) -> bool:
    if isinstance(value, (str, list, tuple, set, dict)):
        return bool(value)
    return value is not None


def _contains(value: Any, expected: Any) -> bool:
    needle = str(expected).casefold()
    if isinstance(value, dict):
        values = value.get("values") if "values" in value else value.values()
        return any(_contains(item, expected) for item in values)
    if isinstance(value, (list, tuple, set)):
        return any(_contains(item, expected) for item in value)
    return needle in str(value).casefold()


def _count(value: Any) -> int | None:
    if isinstance(value, dict):
        if isinstance(value.get("count"), (int, float)):
            return int(value["count"])
        return len(value)
    if isinstance(value, (str, list, tuple, set)):
        return len(value)
    return int(value) if isinstance(value, (int, float)) else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_compact(item) for item in value[:20]]
    if isinstance(value, str):
        return value[:1_000]
    return value
