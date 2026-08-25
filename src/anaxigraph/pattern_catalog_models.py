"""Versioned, provider-neutral contracts for declarative coding-pattern cards."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from anaxigraph.analyzer_capabilities import (
    CAPABILITY_FACTS,
    CAPABILITY_LEVELS,
)
from anaxigraph.pattern_targets import PATTERN_TARGET_LEVELS

PATTERN_CARD_SCHEMA_VERSION = "pattern-card-v1"
PATTERN_CATALOG_FORMAT_VERSION = "pattern-catalog-source-v1"
PATTERN_KINDS = frozenset({"constructive", "failure_mode"})
PATTERN_SIGNAL_OPERATORS = frozenset(
    {
        "available",
        "contains",
        "count_gte",
        "count_lte",
        "eq",
        "exists",
        "gt",
        "gte",
        "lt",
        "lte",
        "neq",
        "unavailable",
    }
)
_KEY = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_FAMILY = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_FEATURE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VALUELESS_OPERATORS = frozenset({"available", "exists", "unavailable"})


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    fact: str
    minimum: str

    def __post_init__(self) -> None:
        if self.fact not in CAPABILITY_FACTS:
            raise ValueError(f"unknown pattern capability fact: {self.fact}")
        if self.minimum not in CAPABILITY_LEVELS[1:]:
            raise ValueError(f"unsupported pattern capability level: {self.minimum}")

    @classmethod
    def from_dict(cls, value: Any) -> CapabilityRequirement:
        mapping = _mapping(value, "required capability")
        return cls(str(mapping.get("fact") or ""), str(mapping.get("minimum") or ""))


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    feature: str
    operator: str
    value: Any = None
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not _FEATURE.fullmatch(self.feature):
            raise ValueError(f"invalid pattern evidence feature: {self.feature}")
        if self.operator not in PATTERN_SIGNAL_OPERATORS:
            raise ValueError(f"unsupported pattern signal operator: {self.operator}")
        if self.operator not in _VALUELESS_OPERATORS and self.value is None:
            raise ValueError(f"pattern signal {self.operator} requires a value")
        if self.operator in _VALUELESS_OPERATORS and self.value is not None:
            raise ValueError(f"pattern signal {self.operator} cannot define a value")
        if not 0 < self.weight <= 5:
            raise ValueError("pattern signal weight must be greater than zero and at most five")

    @classmethod
    def from_dict(cls, value: Any) -> EvidenceSignal:
        mapping = _mapping(value, "evidence signal")
        return cls(
            feature=str(mapping.get("feature") or ""),
            operator=str(mapping.get("operator") or ""),
            value=mapping.get("value"),
            weight=float(mapping.get("weight", 1)),
        )


@dataclass(frozen=True, slots=True)
class PatternRelations:
    related: tuple[str, ...]
    complementary: tuple[str, ...]
    alternatives: tuple[str, ...]
    conflicts: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any) -> PatternRelations:
        mapping = _mapping(value, "pattern relations")
        return cls(
            related=_keys(mapping.get("related", ()), "related patterns"),
            complementary=_keys(mapping.get("complementary", ()), "complementary patterns"),
            alternatives=_keys(mapping.get("alternatives", ()), "alternative patterns"),
            conflicts=_keys(mapping.get("conflicts", ()), "conflicting patterns"),
        )

    def values(self) -> tuple[str, ...]:
        return self.related + self.complementary + self.alternatives + self.conflicts


@dataclass(frozen=True, slots=True)
class PatternScoringGuidance:
    applicability: str
    suitability: str
    conformance: str
    opportunity: str

    @classmethod
    def from_dict(cls, value: Any) -> PatternScoringGuidance:
        mapping = _mapping(value, "pattern scoring guidance")
        return cls(
            applicability=_text(mapping.get("applicability"), "applicability guidance"),
            suitability=_text(mapping.get("suitability"), "suitability guidance"),
            conformance=_text(mapping.get("conformance"), "conformance guidance"),
            opportunity=_text(mapping.get("opportunity"), "opportunity guidance"),
        )


@dataclass(frozen=True, slots=True)
class PatternCard:
    stable_key: str
    version: int
    name: str
    family: str
    kind: str
    intent: str
    scope_levels: tuple[str, ...]
    problem_signals: tuple[EvidenceSignal, ...]
    required_capabilities: tuple[CapabilityRequirement, ...]
    supporting_evidence: tuple[EvidenceSignal, ...]
    counter_evidence: tuple[EvidenceSignal, ...]
    semantic_questions: tuple[str, ...]
    relations: PatternRelations
    scoring: PatternScoringGuidance
    benefits: tuple[str, ...]
    liabilities: tuple[str, ...]
    migration_cautions: tuple[str, ...]
    verification_invariants: tuple[str, ...]
    references: tuple[str, ...]
    schema_version: str = PATTERN_CARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _KEY.fullmatch(self.stable_key):
            raise ValueError(f"invalid pattern stable key: {self.stable_key}")
        if self.version < 1:
            raise ValueError("pattern card version must be positive")
        if not _FAMILY.fullmatch(self.family):
            raise ValueError(f"invalid pattern family: {self.family}")
        if self.kind not in PATTERN_KINDS:
            raise ValueError(f"unsupported pattern kind: {self.kind}")
        if self.schema_version != PATTERN_CARD_SCHEMA_VERSION:
            raise ValueError(f"unsupported pattern card schema: {self.schema_version}")
        if not self.scope_levels:
            raise ValueError("pattern card requires at least one scope level")
        expected_levels = tuple(
            level for level in PATTERN_TARGET_LEVELS if level in self.scope_levels
        )
        if expected_levels != self.scope_levels:
            raise ValueError("pattern scope levels must be unique and in canonical order")
        if not self.problem_signals or not self.supporting_evidence or not self.counter_evidence:
            raise ValueError("pattern cards require problem, supporting, and counter evidence")
        if not self.required_capabilities:
            raise ValueError("pattern cards require explicit analyzer capabilities")
        if self.stable_key in self.relations.values():
            raise ValueError("pattern card cannot relate to itself")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PatternCatalog:
    catalog_version: str
    cards: tuple[PatternCard, ...]
    source_bytes: int
    format_version: str = PATTERN_CATALOG_FORMAT_VERSION
    card_schema_version: str = PATTERN_CARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.catalog_version.strip():
            raise ValueError("pattern catalog version cannot be empty")
        if self.format_version != PATTERN_CATALOG_FORMAT_VERSION:
            raise ValueError(f"unsupported pattern catalog format: {self.format_version}")
        if self.card_schema_version != PATTERN_CARD_SCHEMA_VERSION:
            raise ValueError(f"unsupported catalog card schema: {self.card_schema_version}")
        keys = [card.stable_key for card in self.cards]
        names = [card.name.casefold() for card in self.cards]
        if keys != sorted(set(keys)):
            raise ValueError("pattern catalog keys must be unique and sorted")
        if len(names) != len(set(names)):
            raise ValueError("pattern catalog names must be unique")
        known = set(keys)
        for card in self.cards:
            unknown = set(card.relations.values()) - known
            if unknown:
                raise ValueError(
                    f"pattern {card.stable_key} references unknown patterns: {sorted(unknown)}"
                )

    @property
    def fingerprint(self) -> str:
        payload = [card.as_dict() for card in self.cards]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def card(self, stable_key: str) -> PatternCard | None:
        return next((card for card in self.cards if card.stable_key == stable_key), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "card_schema_version": self.card_schema_version,
            "catalog_version": self.catalog_version,
            "fingerprint": self.fingerprint,
            "source_bytes": self.source_bytes,
            "total": len(self.cards),
            "cards": [card.as_dict() for card in self.cards],
        }


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{label} cannot be empty")
    return result


def _texts(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    values = tuple(_text(item, label) for item in value)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")
    return values


def _keys(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    keys = tuple(str(item) for item in value)
    if any(not _KEY.fullmatch(item) for item in keys) or len(keys) != len(set(keys)):
        raise ValueError(f"{label} must contain unique stable pattern keys")
    return keys


def _scope_levels(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("pattern scope levels must be a list")
    return tuple(str(item) for item in value)


def _signals(value: Any, label: str) -> tuple[EvidenceSignal, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return tuple(EvidenceSignal.from_dict(item) for item in value)


def _capabilities(value: Any) -> tuple[CapabilityRequirement, ...]:
    if not isinstance(value, list):
        raise ValueError("required capabilities must be a list")
    result = tuple(CapabilityRequirement.from_dict(item) for item in value)
    facts = [item.fact for item in result]
    if facts != sorted(set(facts)):
        raise ValueError("required capabilities must be unique and sorted by fact")
    return result
