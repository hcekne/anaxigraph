from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

from anaxigraph.pattern_catalog import (
    BUNDLED_PATTERN_CATALOG_VERSION,
    MAX_BUNDLED_CATALOG_BYTES,
    PATTERN_CATALOG_LOADER_VERSION,
    bundled_pattern_catalog,
    load_pattern_catalog,
)
from anaxigraph.pattern_catalog_models import (
    PATTERN_CARD_SCHEMA_VERSION,
    PATTERN_CATALOG_FORMAT_VERSION,
    PATTERN_KINDS,
    PatternCatalog,
)
from anaxigraph.pattern_targets import PATTERN_TARGET_LEVELS

EXPECTED_FAMILIES = {
    "composition_workflow",
    "data_state",
    "function_construction",
    "integration_concurrency",
    "module_boundary",
    "object_interface",
    "reliability_testing",
    "subsystem_architecture",
}
EXPECTED_CARD_FIELDS = {
    "benefits",
    "counter_evidence",
    "family",
    "intent",
    "kind",
    "liabilities",
    "migration_cautions",
    "name",
    "problem_signals",
    "references",
    "relations",
    "required_capabilities",
    "schema_version",
    "scope_levels",
    "scoring",
    "semantic_questions",
    "stable_key",
    "supporting_evidence",
    "verification_invariants",
    "version",
}


def _card(index: int = 0) -> dict[str, object]:
    return {
        "stable_key": f"test-pattern-{index}",
        "name": f"Test Pattern {index}",
        "kind": "constructive",
        "intent": "Exercise extension of the declarative catalog.",
        "problem_signals": [{"feature": "syntax.calls", "operator": "count_gte", "value": 1}],
        "supporting_evidence": [{"feature": "semantic.responsibilities", "operator": "exists"}],
        "counter_evidence": [{"feature": "code.logical_lines", "operator": "lte", "value": 2}],
        "semantic_questions": ["Would this pattern improve the target?"],
        "benefits": ["Demonstrates data-only catalog extension."],
        "liabilities": ["Test-only pattern with no production meaning."],
        "verification_invariants": ["The loader accepts the expanded card."],
    }


def _source(cards: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "format_version": PATTERN_CATALOG_FORMAT_VERSION,
        "card_schema_version": PATTERN_CARD_SCHEMA_VERSION,
        "catalog_version": "test.1",
        "family": "test_family",
        "defaults": {
            "schema_version": PATTERN_CARD_SCHEMA_VERSION,
            "version": 1,
            "scope_levels": ["symbol"],
            "required_capabilities": [{"fact": "calls", "minimum": "structural"}],
            "relations": {
                "related": [],
                "complementary": [],
                "alternatives": [],
                "conflicts": [],
            },
            "scoring": {
                "applicability": "Use relevant problem evidence.",
                "suitability": "Use target-specific fit evidence.",
                "conformance": "Use implementation evidence.",
                "opportunity": "Use value and migration evidence.",
            },
            "migration_cautions": ["Preserve behavior."],
            "references": ["Test reference"],
        },
        "cards": cards or [_card()],
    }


def _write_source(root: Path, source: dict[str, object], name: str = "patterns-test.json") -> Path:
    path = root / name
    path.write_text(json.dumps(source), encoding="utf-8")
    return path


def _replace_at_path(value, path, replacement):
    if not path:
        return replacement
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    return value


def test_bundled_catalog_is_complete_compact_and_multilevel():
    catalog = bundled_pattern_catalog()
    families = Counter(card.family for card in catalog.cards)
    levels = {level for card in catalog.cards for level in card.scope_levels}

    assert catalog.catalog_version == BUNDLED_PATTERN_CATALOG_VERSION
    assert len(catalog.cards) == 128
    assert catalog.source_bytes < MAX_BUNDLED_CATALOG_BYTES
    assert len(catalog.fingerprint) == 64
    assert set(families) == EXPECTED_FAMILIES
    assert set(families.values()) == {16}
    assert levels == set(PATTERN_TARGET_LEVELS)
    assert {card.kind for card in catalog.cards} == PATTERN_KINDS
    assert catalog.as_dict()["total"] == 128


def test_every_bundled_card_has_the_versioned_pattern_contract():
    catalog = bundled_pattern_catalog()

    for card in catalog.cards:
        value = card.as_dict()
        assert set(value) == EXPECTED_CARD_FIELDS
        assert card.schema_version == PATTERN_CARD_SCHEMA_VERSION
        assert card.problem_signals
        assert card.supporting_evidence
        assert card.counter_evidence
        assert card.required_capabilities
        assert card.semantic_questions
        assert card.verification_invariants
        assert set(card.relations.values()) <= {item.stable_key for item in catalog.cards}

    provider = catalog.card("provider-abstraction")
    assert provider is not None
    assert {"type", "module"} <= set(provider.scope_levels)


def test_loader_schema_and_catalog_versions_are_independent():
    assert (
        len(
            {
                PATTERN_CARD_SCHEMA_VERSION,
                PATTERN_CATALOG_FORMAT_VERSION,
                PATTERN_CATALOG_LOADER_VERSION,
                BUNDLED_PATTERN_CATALOG_VERSION,
            }
        )
        == 4
    )


def test_package_exposes_all_catalog_sources():
    root = files("anaxigraph").joinpath("catalog")
    names = {item.name for item in root.iterdir() if item.name.startswith("patterns-")}

    assert names == {
        "patterns-composition-workflow.json",
        "patterns-data-state.json",
        "patterns-function-construction.json",
        "patterns-integration-concurrency.json",
        "patterns-module-boundary.json",
        "patterns-object-interface.json",
        "patterns-reliability-testing.json",
        "patterns-subsystem-architecture.json",
    }


def test_operator_catalog_has_no_card_count_ceiling(tmp_path):
    cards = [_card(index) for index in range(140)]
    path = _write_source(tmp_path, _source(cards))

    catalog = load_pattern_catalog(path)

    assert len(catalog.cards) == 140
    assert catalog.card("test-pattern-139") is not None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate", "keys must be unique"),
        ("unknown_relation", "references unknown patterns"),
        ("unknown_capability", "unknown pattern capability fact"),
        ("unknown_operator", "unsupported pattern signal operator"),
    ],
)
def test_loader_rejects_invalid_cards(tmp_path, mutation, message):
    source = _source()
    if mutation == "duplicate":
        source["cards"] = [_card(), _card()]
    elif mutation == "unknown_relation":
        source["cards"][0]["relations"] = {"related": ["missing-pattern"]}
    elif mutation == "unknown_capability":
        source["defaults"]["required_capabilities"] = [
            {"fact": "imaginary_fact", "minimum": "structural"}
        ]
    else:
        source["cards"][0]["problem_signals"][0]["operator"] = "approximately"
    path = _write_source(tmp_path, source)

    with pytest.raises(ValueError, match=message):
        load_pattern_catalog(path)


def test_directory_sources_must_share_a_catalog_version(tmp_path):
    _write_source(tmp_path, _source(), "patterns-one.json")
    second = copy.deepcopy(_source([_card(1)]))
    second["catalog_version"] = "test.2"
    _write_source(tmp_path, second, "patterns-two.json")

    with pytest.raises(ValueError, match="must share one catalog version"):
        load_pattern_catalog(tmp_path)


def test_loader_bounds_source_bytes_without_bounding_card_count(tmp_path):
    path = _write_source(tmp_path, _source())

    with pytest.raises(ValueError, match="exceeds the 1-byte limit"):
        load_pattern_catalog(path, max_bytes=1)

    with pytest.raises(ValueError, match="must be positive"):
        load_pattern_catalog(path, max_bytes=0)


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (
            ("defaults", "required_capabilities", 0, "minimum"),
            "imaginary",
            "unsupported pattern capability level",
        ),
        (
            ("cards", 0, "problem_signals", 0, "feature"),
            "Invalid Feature",
            "invalid pattern evidence feature",
        ),
        (("cards", 0, "problem_signals", 0, "value"), None, "requires a value"),
        (
            ("cards", 0, "supporting_evidence", 0, "value"),
            True,
            "cannot define a value",
        ),
        (("cards", 0, "problem_signals", 0, "weight"), 6, "weight must be greater"),
        (("cards", 0, "stable_key"), "Invalid key", "invalid pattern stable key"),
        (("defaults", "version"), 0, "version must be positive"),
        (("family",), "invalid-family", "invalid pattern family"),
        (("cards", 0, "kind"), "advice", "unsupported pattern kind"),
        (("defaults", "schema_version"), "pattern-card-v2", "unsupported pattern card schema"),
        (("defaults", "scope_levels"), ["module", "symbol"], "canonical order"),
        (
            ("cards", 0, "counter_evidence"),
            [],
            "require problem, supporting, and counter evidence",
        ),
        (
            ("defaults", "required_capabilities"),
            [],
            "require explicit analyzer capabilities",
        ),
        (
            ("cards", 0, "relations"),
            {"related": ["test-pattern-0"]},
            "cannot relate to itself",
        ),
        (
            ("defaults", "required_capabilities"),
            [
                {"fact": "types", "minimum": "structural"},
                {"fact": "calls", "minimum": "structural"},
            ],
            "unique and sorted by fact",
        ),
    ],
)
def test_card_contract_rejects_ambiguous_or_incomplete_data(tmp_path, path, replacement, message):
    source = _replace_at_path(_source(), path, replacement)

    with pytest.raises(ValueError, match=message):
        load_pattern_catalog(_write_source(tmp_path, source))


def test_card_contract_requires_unique_names(tmp_path):
    source = _source([_card(), _card(1)])
    source["cards"][1]["name"] = source["cards"][0]["name"]

    with pytest.raises(ValueError, match="names must be unique"):
        load_pattern_catalog(_write_source(tmp_path, source))


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        ((), [], "must be an object"),
        (("format_version",), "pattern-catalog-source-v2", "unsupported pattern catalog format"),
        (("card_schema_version",), "pattern-card-v2", "unsupported pattern card schema"),
        (("catalog_version",), "", "requires a catalog version"),
        (("family",), "", "requires a family"),
        (("defaults",), [], "requires defaults"),
        (("cards",), [], "requires cards"),
        (("cards",), ["invalid"], "pattern card in test_family must be an object"),
        (("defaults", "relations"), "invalid", "pattern card relations must be an object"),
    ],
)
def test_source_contract_rejects_malformed_documents(tmp_path, path, replacement, message):
    value = _replace_at_path(_source(), path, replacement)
    path = tmp_path / "patterns-test.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_pattern_catalog(path)


def test_loader_rejects_missing_empty_and_invalid_json_paths(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        load_pattern_catalog(tmp_path / "missing")
    with pytest.raises(ValueError, match="contains no pattern sources"):
        load_pattern_catalog(tmp_path)

    invalid = tmp_path / "patterns-invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid pattern catalog JSON"):
        load_pattern_catalog(invalid)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"catalog_version": ""}, "version cannot be empty"),
        ({"format_version": "pattern-catalog-source-v2"}, "unsupported pattern catalog format"),
        ({"card_schema_version": "pattern-card-v2"}, "unsupported catalog card schema"),
    ],
)
def test_catalog_contract_rejects_incompatible_identity(changes, message):
    catalog = bundled_pattern_catalog()

    with pytest.raises(ValueError, match=message):
        replace(catalog, **changes)


def test_catalog_contract_requires_sorted_cards():
    catalog = bundled_pattern_catalog()

    with pytest.raises(ValueError, match="keys must be unique and sorted"):
        PatternCatalog("test.1", tuple(reversed(catalog.cards)), catalog.source_bytes)
