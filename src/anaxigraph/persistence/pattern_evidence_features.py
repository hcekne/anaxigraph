"""Feature builders for module and symbol pattern-evidence targets."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from anaxigraph.pattern_evidence import (
    PATTERN_EVIDENCE_VERSION,
    EvidenceReference,
    PatternFeature,
    TargetEvidence,
)
from anaxigraph.pattern_targets import PatternTarget, symbol_target, target_level_for_symbol
from anaxigraph.persistence.pattern_evidence_inputs import capability as read_capability
from anaxigraph.persistence.pattern_evidence_inputs import (
    capability_confidence,
    parse_status,
)


def module_evidence(
    target: PatternTarget,
    module: dict[str, Any],
    raw: dict[str, Any],
    symbols: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    semantic: dict[str, Any] | None,
    snapshot_id: int,
) -> TargetEvidence:
    locator = target.key
    type_count = sum(
        target_level_for_symbol(str(item["symbol_type"])) == "type" for item in symbols
    )
    capability = read_capability(raw)
    features = [
        *_module_code_features(raw, capability, locator),
        *_module_repository_features(module, symbols, type_count, locator),
        *_fact_features(facts, locator),
        *_semantic_features(semantic, locator),
    ]
    capability_fingerprints = (str(capability["fingerprint"]),) if capability else ()
    ordered = tuple(sorted(features, key=lambda item: item.name))
    fingerprint = _digest(
        {
            "version": PATTERN_EVIDENCE_VERSION,
            "target": target.key,
            "raw_hash": raw["raw_hash"],
            "structural_hash": raw["structural_hash"],
            "capabilities": capability_fingerprints,
            "features": [item.as_dict() for item in ordered],
        }
    )
    return TargetEvidence(
        target=target,
        snapshot_id=snapshot_id,
        input_fingerprint=fingerprint,
        features=ordered,
        capability_fingerprints=capability_fingerprints,
    )


def _module_code_features(
    raw: dict[str, Any],
    capability: dict[str, Any] | None,
    locator: str,
) -> list[PatternFeature]:
    return [
        _feature("analyzer.parse_status", parse_status(raw), "analyzer-ir", locator),
        _feature("code.comment_lines", int(raw["comment_lines"]), "analyzer-ir", locator),
        _feature(
            "code.complexity",
            float(raw["complexity"]),
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "complexity"),
        ),
        _feature("code.lines", int(raw["lines_of_code"]), "analyzer-ir", locator),
        _feature("documentation.summary", str(raw["summary"]), "analyzer-ir", locator),
        _feature(
            "interfaces.public",
            json.loads(raw["public_interfaces_json"] or "[]"),
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "exports"),
        ),
        _feature(
            "responsibilities.deterministic",
            json.loads(raw["responsibilities_json"] or "[]"),
            "analyzer-ir",
            locator,
        ),
        _feature(
            "side_effects.deterministic",
            json.loads(raw["side_effects_json"] or "[]"),
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "side_effects"),
        ),
    ]


def _module_repository_features(
    module: dict[str, Any],
    symbols: list[dict[str, Any]],
    type_count: int,
    locator: str,
) -> list[PatternFeature]:
    return [
        _feature("graph.fan_in", int(module["fan_in"]), "repository-graph", locator),
        _feature("graph.fan_out", int(module["fan_out"]), "repository-graph", locator),
        _feature("history.additions", int(module.get("additions") or 0), "git-history", locator),
        _feature("history.change_count", int(module["change_count"]), "git-history", locator),
        _feature("history.deletions", int(module.get("deletions") or 0), "git-history", locator),
        _feature("symbols.count", len(symbols), "analyzer-ir", locator),
        _feature("symbols.function_count", len(symbols) - type_count, "analyzer-ir", locator),
        _feature("types.count", type_count, "analyzer-ir", locator),
        _coverage_feature(module.get("line_coverage"), locator),
    ]


def symbol_evidence(
    symbols: list[dict[str, Any]],
    modules: dict[int, PatternTarget],
    raw: dict[int, dict[str, Any]],
    facts: dict[int, list[dict[str, Any]]],
    snapshot_id: int,
) -> list[TargetEvidence]:
    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in symbols:
        level = target_level_for_symbol(str(item["symbol_type"]))
        grouped[(int(item["artifact_id"]), level, str(item["qualified_name"]))].append(item)
    type_keys: dict[tuple[int, str], str] = {}
    for (artifact_id, level, qualified), rows in grouped.items():
        if level == "type":
            target = _symbol_target(rows, qualified, modules[artifact_id].key)
            type_keys[(artifact_id, qualified)] = target.key

    result = []
    for (artifact_id, _level, qualified), rows in sorted(grouped.items()):
        parent_name = qualified.rpartition(".")[0]
        parent = type_keys.get((artifact_id, parent_name), modules[artifact_id].key)
        target = _symbol_target(rows, qualified, parent)
        capability = read_capability(raw[artifact_id])
        capability_fingerprints = (str(capability["fingerprint"]),) if capability else ()
        matching = [item for item in facts[artifact_id] if item["subject"] == qualified]
        features = _symbol_features(rows, capability, target.key) + _fact_features(
            matching, target.key
        )
        ordered = tuple(sorted(features, key=lambda item: item.name))
        fingerprint = _digest(
            {
                "version": PATTERN_EVIDENCE_VERSION,
                "target": target.key,
                "raw_hash": raw[artifact_id]["raw_hash"],
                "features": [item.as_dict() for item in ordered],
                "capabilities": capability_fingerprints,
            }
        )
        result.append(
            TargetEvidence(
                target=target,
                snapshot_id=snapshot_id,
                input_fingerprint=fingerprint,
                features=ordered,
                capability_fingerprints=capability_fingerprints,
            )
        )
    return result


def _symbol_target(
    rows: list[dict[str, Any]],
    qualified: str,
    parent_key: str,
) -> PatternTarget:
    return symbol_target(
        str(rows[0]["path"]),
        qualified,
        str(rows[0]["symbol_type"]),
        parent_key=parent_key,
        label=str(rows[0]["name"]),
    )


def _symbol_features(
    rows: list[dict[str, Any]],
    capability: dict[str, Any] | None,
    locator: str,
) -> list[PatternFeature]:
    documentation_confidence = capability_confidence(capability, "symbol_documentation")
    summaries = sorted({str(item["summary"]) for item in rows if item["summary"]})
    references = tuple(
        EvidenceReference("analyzer-ir", locator, int(item["start_line"]), str(item["signature"]))
        for item in rows[:20]
    )
    return [
        _feature(
            "code.complexity",
            sum(float(item["complexity"]) for item in rows),
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "complexity"),
        ),
        _feature(
            "code.logical_lines",
            sum(int(item["logical_lines"]) for item in rows),
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "source_spans"),
        ),
        PatternFeature(
            "documentation.summary",
            summaries,
            documentation_confidence,
            references,
            "available" if documentation_confidence else "unavailable",
        ),
        *_symbol_contract_features(rows, capability, locator),
    ]


def _symbol_contract_features(
    rows: list[dict[str, Any]],
    capability: dict[str, Any] | None,
    locator: str,
) -> list[PatternFeature]:
    signatures = sorted({str(item["signature"]) for item in rows if item["signature"]})
    return [
        _feature(
            "interface.signatures",
            signatures,
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "signatures"),
        ),
        _feature(
            "interface.visibility",
            sorted({str(item["visibility"]) for item in rows}),
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "symbol_visibility"),
        ),
        _feature("symbol.definition_count", len(rows), "analyzer-ir", locator),
        _feature(
            "symbol.kinds",
            sorted({str(item["symbol_type"]) for item in rows}),
            "analyzer-ir",
            locator,
            confidence=capability_confidence(capability, "symbol_kind"),
        ),
    ]


def _fact_features(facts: list[dict[str, Any]], locator: str) -> list[PatternFeature]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in facts:
        grouped[str(item["fact"])].append(item)
    result = []
    for fact, values in grouped.items():
        distinct = sorted({str(item["value"]) for item in values})
        references = tuple(
            EvidenceReference(
                "analyzer-ir",
                locator,
                int(item.get("line") or 0),
                str(item.get("evidence") or ""),
            )
            for item in values[:20]
        )
        result.append(
            PatternFeature(
                f"syntax.{fact}",
                {
                    "count": len(values),
                    "values": distinct[:50],
                    "omitted_values": max(0, len(distinct) - 50),
                },
                min(float(item.get("confidence") or 0) for item in values),
                references,
            )
        )
    return result


def _semantic_features(value: dict[str, Any] | None, locator: str) -> list[PatternFeature]:
    if value is None:
        return [PatternFeature("semantic.dossier", None, 0, (), "unavailable")]
    confidence = float(value.get("_confidence") or 0)
    source = EvidenceReference(
        "semantic-dossier", locator, detail=str(value.get("_document_id") or "")
    )
    keys = (
        "architecture_role",
        "collaborators",
        "domain_concepts",
        "extension_points",
        "inputs",
        "invariants",
        "outputs",
        "public_contracts",
        "responsibilities",
        "risks",
        "side_effects",
        "testing_guidance",
    )
    return [
        PatternFeature("semantic.dossier", True, confidence, (source,)),
        *[PatternFeature(f"semantic.{key}", value.get(key), confidence, (source,)) for key in keys],
    ]


def _coverage_feature(value: Any, locator: str) -> PatternFeature:
    if value is None:
        return PatternFeature("coverage.line", None, 0, (), "unavailable")
    return _feature("coverage.line", float(value), "coverage", locator)


def _feature(
    name: str,
    value: Any,
    source: str,
    locator: str,
    *,
    confidence: float = 1.0,
) -> PatternFeature:
    return PatternFeature(
        name,
        value,
        confidence,
        (EvidenceReference(source, locator),) if confidence > 0 else (),
        "available" if confidence > 0 else "unavailable",
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
