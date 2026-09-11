"""Roll pattern-neutral module evidence through architecture parents."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from anaxigraph.analyzer_capabilities import CAPABILITY_FACTS
from anaxigraph.pattern_evidence import (
    PATTERN_EVIDENCE_VERSION,
    EvidenceReference,
    PatternFeature,
    TargetEvidence,
)
from anaxigraph.pattern_targets import PatternTarget
from anaxigraph.persistence.temporal_hashing import digest
from anaxigraph.semantic_evidence_selection import module_role, representative_items, stable_order


def aggregate_evidence(
    target: PatternTarget,
    children: list[TargetEvidence],
    snapshot_id: int,
    contracts: dict[str, dict[str, Any]],
    *,
    witnesses: list[TargetEvidence] | None = None,
    relationships: dict[str, list[dict[str, Any]]] | None = None,
) -> TargetEvidence:
    modules = sum(
        int(_value(item, "modules.count", item.target.level == "module")) for item in children
    )
    features = [
        *_numeric_features(children, target.key),
        _feature("modules.count", modules, "architecture-map", target.key),
        _feature(
            "semantic.coverage",
            _semantic_coverage(children, modules),
            "semantic-dossier",
            target.key,
        ),
        _feature(
            "symbols.count",
            sum(int(_value(item, "symbols.count", 0)) for item in children),
            "architecture-map",
            target.key,
        ),
        _feature(
            "types.count",
            sum(int(_value(item, "types.count", 0)) for item in children),
            "architecture-map",
            target.key,
        ),
        _aggregate_coverage(children, target.key, modules),
        _capability_coverage(children, contracts, target.key, modules),
        *_architecture_features(target, witnesses or [], relationships or {}),
    ]
    capabilities = tuple(
        sorted({value for child in children for value in child.capability_fingerprints})
    )
    ordered = tuple(sorted(features, key=lambda item: item.name))
    return TargetEvidence(
        target=target,
        snapshot_id=snapshot_id,
        input_fingerprint=_aggregate_fingerprint(target, children, capabilities, ordered),
        features=ordered,
        capability_fingerprints=capabilities,
    )


def _architecture_features(target, witnesses, relationships):
    selected = representative_items(
        [{"item": item} for item in witnesses],
        group=lambda row: str(row["item"].target.parent_key),
        rank=lambda row: (
            module_role(row["item"].target.path) != "production",
            -_value(row["item"], "graph.fan_in", 0),
            stable_order(row["item"].target.key),
        ),
        limit=8,
    )
    selected_items = [row["item"] for row in selected]
    return [
        _feature(
            "architecture.witnesses",
            {
                "total_modules": len(witnesses),
                "included": len(selected_items),
                "omitted": len(witnesses) - len(selected_items),
                "items": [_witness(item) for item in selected_items],
                "caveat": "Child claims are witnesses, not proof that every member or the parent follows a pattern.",
            },
            "semantic-dossier-and-analyzer",
            target.key,
        ),
        _boundary_feature(target, witnesses, relationships),
        *_parent_semantics(selected_items),
    ]


def _witness(item: TargetEvidence) -> dict[str, Any]:
    return {
        "path": item.target.path,
        "input_fingerprint": item.input_fingerprint,
        "semantic_confidence": (
            item.feature("semantic.dossier").confidence if item.feature("semantic.dossier") else 0
        ),
        "responsibility_owner": item.target.parent_key,
        "responsibilities": _texts(_value(item, "semantic.responsibilities", [])),
        "public_contracts": _texts(_value(item, "semantic.public_contracts", [])),
        "public_interfaces": _texts(_value(item, "interfaces.public", [])),
        "source": [
            ref.as_dict()
            for feature in item.features
            if feature.name == "semantic.dossier"
            for ref in feature.evidence
        ],
    }


def _parent_semantics(witnesses: list[TargetEvidence]) -> list[PatternFeature]:
    result = []
    for name in (
        "responsibilities",
        "public_contracts",
        "architecture_role",
        "extension_points",
        "invariants",
    ):
        features = [item.feature(f"semantic.{name}") for item in witnesses]
        available = [
            item for item in features if item and item.value and item.availability != "unavailable"
        ]
        if not available:
            continue
        values = list(dict.fromkeys(text for item in available for text in _texts(item.value)))[:24]
        references = tuple(ref for item in available for ref in item.evidence)
        result.append(
            PatternFeature(
                f"semantic.{name}",
                values,
                min(item.confidence for item in available),
                references,
                "partial",
            )
        )
    return result


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else []
    return [str(item)[:500] for item in values[:3]]


def _boundary_feature(target, witnesses, relationships):
    paths = {item.target.path for item in witnesses}
    edges = [
        {
            "source": source,
            **edge,
            "boundary": "internal"
            if source in paths and edge.get("path") in paths
            else "outgoing"
            if source in paths
            else "incoming",
        }
        for source, links in relationships.items()
        for edge in links
        if edge.get("direction") == "uses" and (source in paths or edge.get("path") in paths)
    ]
    selected = representative_items(
        edges,
        group=lambda edge: edge["boundary"],
        rank=lambda edge: (
            edge["boundary"] == "internal",
            stable_order(json.dumps(edge, sort_keys=True)),
        ),
        limit=24,
    )
    return _feature(
        "graph.boundaries",
        {
            "counts": dict(Counter(edge["boundary"] for edge in edges)),
            "relationships": selected,
            "omitted": len(edges) - len(selected),
            "caveat": "These are extracted static links; missing or unresolved edges are not evidence of runtime isolation.",
        },
        "repository-graph",
        target.key,
    )


def _aggregate_fingerprint(
    target: PatternTarget,
    children: list[TargetEvidence],
    capabilities: tuple[str, ...],
    features: tuple[PatternFeature, ...],
) -> str:
    return digest(
        {
            "version": PATTERN_EVIDENCE_VERSION,
            "target": target.key,
            "children": [(child.target.key, child.input_fingerprint) for child in children],
            "capabilities": capabilities,
            "features": [item.as_dict() for item in features],
        }
    )


def _numeric_features(children: list[TargetEvidence], locator: str) -> list[PatternFeature]:
    return [
        _feature("children.count", len(children), "architecture-map", locator),
        *[
            _feature(
                name,
                sum(_value(item, name, 0) for item in children),
                "architecture-map",
                locator,
            )
            for name in (
                "code.complexity",
                "code.lines",
                "graph.fan_in",
                "graph.fan_out",
                "history.change_count",
            )
        ],
    ]


def _capability_coverage(
    children: list[TargetEvidence],
    contracts: dict[str, dict[str, Any]],
    locator: str,
    module_count: int,
) -> PatternFeature:
    levels_by_contract = {
        fingerprint: {item["fact"]: item["level"] for item in contract.get("facts") or []}
        for fingerprint, contract in contracts.items()
    }
    distribution: dict[str, Counter[str]] = {fact: Counter() for fact in CAPABILITY_FACTS}
    for child in children:
        existing = child.feature("analyzer.capability_coverage")
        if existing is not None:
            for fact, detail in existing.value.items():
                distribution[fact].update(detail["levels"])
            continue
        if not child.capability_fingerprints:
            for fact in CAPABILITY_FACTS:
                distribution[fact]["unavailable"] += 1
            continue
        for fingerprint in child.capability_fingerprints:
            for fact in CAPABILITY_FACTS:
                level = levels_by_contract.get(fingerprint, {}).get(fact, "unavailable")
                distribution[fact][level] += 1
    value = {
        fact: {
            "available": sum(count for level, count in counts.items() if level != "unavailable"),
            "total": module_count,
            "levels": dict(sorted(counts.items())),
        }
        for fact, counts in sorted(distribution.items())
    }
    return _feature("analyzer.capability_coverage", value, "analyzer-contract", locator)


def _aggregate_coverage(
    children: list[TargetEvidence],
    locator: str,
    module_count: int,
) -> PatternFeature:
    weighted = []
    measured = 0
    for item in children:
        feature = item.feature("coverage.line")
        child_modules = int(_value(item, "modules.count", item.target.level == "module"))
        if feature is None or feature.availability == "unavailable" or feature.value is None:
            continue
        weighted.append(float(feature.value) * child_modules)
        measured += child_modules
    if not weighted:
        return PatternFeature("coverage.line", None, 0, (), "unavailable")
    availability = "available" if measured == module_count else "partial"
    return PatternFeature(
        "coverage.line",
        sum(weighted) / measured,
        measured / max(1, module_count),
        (EvidenceReference("coverage", locator),),
        availability,
    )


def _semantic_coverage(children: list[TargetEvidence], module_count: int) -> float:
    current = 0
    for item in children:
        existing = item.feature("semantic.coverage")
        child_modules = int(_value(item, "modules.count", item.target.level == "module"))
        if existing is not None:
            current += round(float(existing.value) * child_modules)
            continue
        dossier = item.feature("semantic.dossier")
        if dossier is not None and dossier.availability == "available":
            current += 1
    return current / max(1, module_count)


def _feature(name: str, value: Any, source: str, locator: str) -> PatternFeature:
    return PatternFeature(name, value, 1.0, (EvidenceReference(source, locator),))


def _value(item: TargetEvidence, name: str, default: Any) -> Any:
    feature = item.feature(name)
    return feature.value if feature is not None else default
