"""Versioned pattern-neutral feature projection records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from anaxigraph.ir import IR_SCHEMA_VERSION
from anaxigraph.pattern_targets import PATTERN_TARGET_SCHEMA_VERSION, PatternTarget

PATTERN_EVIDENCE_VERSION = "pattern-evidence-v1"
PATTERN_CONTRACT_VERSIONS = {
    "ir_schema_version": IR_SCHEMA_VERSION,
    "pattern_evidence_version": PATTERN_EVIDENCE_VERSION,
    "pattern_target_schema_version": PATTERN_TARGET_SCHEMA_VERSION,
}
FEATURE_AVAILABILITY = frozenset({"available", "partial", "unavailable"})


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    source: str
    locator: str
    line: int = 0
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PatternFeature:
    name: str
    value: Any
    confidence: float
    evidence: tuple[EvidenceReference, ...]
    availability: str = "available"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("pattern feature name cannot be empty")
        if self.availability not in FEATURE_AVAILABILITY:
            raise ValueError(f"unsupported feature availability: {self.availability}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("pattern feature confidence must be between zero and one")
        if self.availability == "unavailable" and self.confidence != 0:
            raise ValueError("unavailable pattern features must have zero confidence")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "confidence": self.confidence,
            "availability": self.availability,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class TargetEvidence:
    target: PatternTarget
    snapshot_id: int
    input_fingerprint: str
    features: tuple[PatternFeature, ...]
    capability_fingerprints: tuple[str, ...] = ()
    projection_version: str = PATTERN_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        names = [item.name for item in self.features]
        if names != sorted(set(names)):
            raise ValueError("target evidence features must be unique and sorted")
        if tuple(sorted(set(self.capability_fingerprints))) != self.capability_fingerprints:
            raise ValueError("capability fingerprints must be unique and sorted")

    def feature(self, name: str) -> PatternFeature | None:
        return next((item for item in self.features if item.name == name), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.as_dict(),
            "snapshot_id": self.snapshot_id,
            "input_fingerprint": self.input_fingerprint,
            "projection_version": self.projection_version,
            "capability_fingerprints": list(self.capability_fingerprints),
            "features": [item.as_dict() for item in self.features],
        }


@dataclass(frozen=True, slots=True)
class PatternEvidenceProjection:
    repository_id: int
    snapshot_id: int
    fingerprint: str
    capability_contracts: dict[str, dict[str, Any]]
    items: tuple[TargetEvidence, ...]
    projection_version: str = PATTERN_EVIDENCE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "snapshot_id": self.snapshot_id,
            "projection_version": self.projection_version,
            "fingerprint": self.fingerprint,
            "capability_contracts": {
                key: self.capability_contracts[key] for key in sorted(self.capability_contracts)
            },
            "total": len(self.items),
            "counts_by_level": {
                level: sum(item.target.level == level for item in self.items)
                for level in ("symbol", "type", "module", "subsystem", "area", "repository")
            },
            "items": [item.as_dict() for item in self.items],
        }
