"""Pattern-neutral syntax evidence shared by analyzers and persistence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalyzerFact:
    fact: str
    subject: str
    value: str
    line: int
    evidence: str
    confidence: float = 1.0
    end_line: int = 0
