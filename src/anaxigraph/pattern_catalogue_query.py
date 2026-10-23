"""Page the complete catalogue without hiding cards that have no assessment yet."""

from __future__ import annotations

from dataclasses import dataclass

from anaxigraph.pattern_evaluation_contract import PATTERN_SCORE_DIMENSIONS

CATALOGUE_STATES = ("missing", "considered", "rated", "reviewed", "unresolved")


@dataclass(frozen=True, slots=True)
class PatternCatalogueQuery:
    pattern: str = ""
    family: str = ""
    state: str = ""
    sort_by: str = "pattern"
    limit: int = 25
    offset: int = 0
    include_manifest: bool = False

    def __post_init__(self):
        if self.state and self.state not in CATALOGUE_STATES:
            raise ValueError("unsupported catalogue assessment state")
        if self.sort_by not in ("pattern", *PATTERN_SCORE_DIMENSIONS):
            raise ValueError("unsupported catalogue score sort")
        if not 1 <= self.limit <= 100 or self.offset < 0:
            raise ValueError("catalogue page requires limit 1–100 and nonnegative offset")
        if any(len(value) > 2000 for value in (self.pattern, self.family)):
            raise ValueError("catalogue filter is too long")

    def filters(self) -> dict:
        return {
            "pattern": self.pattern,
            "family": self.family,
            "state": self.state,
            "sort_by": self.sort_by,
            "include_manifest": self.include_manifest,
        }
