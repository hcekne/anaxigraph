"""Versioned, language-neutral declarations of analyzer evidence depth."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

CAPABILITY_SCHEMA_VERSION = "analyzer-capabilities-v1"
CAPABILITY_LEVELS = ("unavailable", "heuristic", "lexical", "structural", "deep")
ANALYSIS_LEVELS = ("inventory", "heuristic", "lexical", "structural", "deep")
CAPABILITY_FACTS = frozenset(
    {
        "annotations",
        "async_behavior",
        "calls",
        "complexity",
        "concurrency",
        "constructors",
        "control_flow",
        "data_flow",
        "decorators",
        "entry_points",
        "error_handling",
        "exports",
        "generics",
        "imports",
        "inheritance",
        "module_documentation",
        "module_identity",
        "mutation",
        "registrations",
        "side_effects",
        "signatures",
        "source_spans",
        "symbol_documentation",
        "symbol_kind",
        "symbol_visibility",
        "symbols",
        "test_relationships",
        "types",
    }
)


@dataclass(frozen=True, slots=True)
class CapabilitySupport:
    fact: str
    level: str

    def __post_init__(self) -> None:
        if self.fact not in CAPABILITY_FACTS:
            raise ValueError(f"unknown analyzer capability fact: {self.fact}")
        if self.level not in CAPABILITY_LEVELS[1:]:
            raise ValueError(f"unsupported analyzer capability level: {self.level}")


@dataclass(frozen=True, slots=True)
class AnalyzerCapabilities:
    analyzer: str
    analyzer_version: str
    analysis_level: str
    facts: tuple[CapabilitySupport, ...]
    limitations: tuple[str, ...] = ()
    schema_version: str = CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.analyzer or not self.analyzer_version:
            raise ValueError("analyzer capabilities require analyzer identity and version")
        if self.analysis_level not in ANALYSIS_LEVELS:
            raise ValueError(f"unsupported analyzer analysis level: {self.analysis_level}")
        if self.schema_version != CAPABILITY_SCHEMA_VERSION:
            raise ValueError(f"unsupported analyzer capability schema: {self.schema_version}")
        names = [item.fact for item in self.facts]
        if names != sorted(set(names)):
            raise ValueError("analyzer capability facts must be unique and sorted")

    def support_level(self, fact: str) -> str:
        return next((item.level for item in self.facts if item.fact == fact), "unavailable")

    def supports(self, fact: str, minimum: str = "heuristic") -> bool:
        if minimum not in CAPABILITY_LEVELS:
            raise ValueError(f"unsupported minimum capability level: {minimum}")
        return CAPABILITY_LEVELS.index(self.support_level(fact)) >= CAPABILITY_LEVELS.index(minimum)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "analyzer": self.analyzer,
            "analyzer_version": self.analyzer_version,
            "analysis_level": self.analysis_level,
            "facts": [asdict(item) for item in self.facts],
            "limitations": list(self.limitations),
            "fingerprint": self.fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        value = {
            "schema_version": self.schema_version,
            "analyzer": self.analyzer,
            "analyzer_version": self.analyzer_version,
            "analysis_level": self.analysis_level,
            "facts": [asdict(item) for item in self.facts],
            "limitations": self.limitations,
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def capabilities_from_dict(value: Any) -> AnalyzerCapabilities | None:
    """Restore and verify a persisted capability declaration."""

    if not isinstance(value, dict) or not value.get("analyzer"):
        return None
    declaration = AnalyzerCapabilities(
        analyzer=str(value["analyzer"]),
        analyzer_version=str(value["analyzer_version"]),
        analysis_level=str(value["analysis_level"]),
        facts=tuple(
            CapabilitySupport(str(item["fact"]), str(item["level"]))
            for item in value.get("facts") or ()
        ),
        limitations=tuple(str(item) for item in value.get("limitations") or ()),
        schema_version=str(value.get("schema_version") or CAPABILITY_SCHEMA_VERSION),
    )
    recorded = str(value.get("fingerprint") or "")
    if recorded and recorded != declaration.fingerprint:
        raise ValueError("persisted analyzer capability fingerprint does not match its declaration")
    return declaration


def declare_capabilities(
    analyzer: str,
    analyzer_version: str,
    analysis_level: str,
    *,
    deep: tuple[str, ...] = (),
    structural: tuple[str, ...] = (),
    lexical: tuple[str, ...] = (),
    heuristic: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
) -> AnalyzerCapabilities:
    levels = {
        fact: level
        for level, facts in (
            ("deep", deep),
            ("structural", structural),
            ("lexical", lexical),
            ("heuristic", heuristic),
        )
        for fact in facts
    }
    count = sum(len(items) for items in (deep, structural, lexical, heuristic))
    if len(levels) != count:
        raise ValueError("analyzer capability facts cannot be declared at multiple levels")
    return AnalyzerCapabilities(
        analyzer=analyzer,
        analyzer_version=analyzer_version,
        analysis_level=analysis_level,
        facts=tuple(CapabilitySupport(fact, levels[fact]) for fact in sorted(levels)),
        limitations=limitations,
    )
