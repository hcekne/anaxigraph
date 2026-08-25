"""Bounded filters for current pattern intelligence."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.pattern_evaluation_contract import PATTERN_SCORE_DIMENSIONS
from anaxigraph.pattern_targets import PATTERN_TARGET_LEVELS

PATTERN_QUERY_VERSION = "pattern-query-v1"
PATTERN_QUERY_LIMIT = 20
PATTERN_QUERY_MAX_LIMIT = 100
PATTERN_RECOMMENDATIONS = frozenset(
    {
        "retain",
        "introduce",
        "improve_conformance",
        "replace",
        "avoid",
        "no_action",
        "insufficient_evidence",
    }
)
PATTERN_PRESENCE = frozenset({"present", "partial", "absent", "uncertain"})


@dataclass(frozen=True, slots=True)
class PatternEvaluationQuery:
    target: str = ""
    pattern: str = ""
    level: str = ""
    recommendation: str = ""
    presence: str = ""
    sort_by: str = "opportunity"
    minimum_score: int = 0
    limit: int = PATTERN_QUERY_LIMIT
    offset: int = 0
    include_evidence: bool = False

    def __post_init__(self) -> None:
        if self.level and self.level not in PATTERN_TARGET_LEVELS:
            raise ValueError(f"unsupported pattern target level: {self.level}")
        if self.recommendation and self.recommendation not in PATTERN_RECOMMENDATIONS:
            raise ValueError(f"unsupported pattern recommendation: {self.recommendation}")
        if self.presence and self.presence not in PATTERN_PRESENCE:
            raise ValueError(f"unsupported pattern presence: {self.presence}")
        if self.sort_by not in PATTERN_SCORE_DIMENSIONS:
            raise ValueError(f"unsupported pattern score sort: {self.sort_by}")
        if not 0 <= self.minimum_score <= 100:
            raise ValueError("pattern minimum_score must be between zero and 100")
        if not 1 <= self.limit <= PATTERN_QUERY_MAX_LIMIT:
            raise ValueError(
                f"pattern query limit must be between one and {PATTERN_QUERY_MAX_LIMIT}"
            )
        if self.offset < 0:
            raise ValueError("pattern query offset cannot be negative")
        for field, value in (("target", self.target), ("pattern", self.pattern)):
            if len(value) > 2_000:
                raise ValueError(f"pattern query {field} is too long")

    def filters(self) -> dict[str, str | int | bool]:
        return {
            "target": self.target,
            "pattern": self.pattern,
            "level": self.level,
            "recommendation": self.recommendation,
            "presence": self.presence,
            "sort_by": self.sort_by,
            "minimum_score": self.minimum_score,
            "include_evidence": self.include_evidence,
        }
