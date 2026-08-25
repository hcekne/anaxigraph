"""Load the bundled or operator-supplied declarative pattern catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable

from anaxigraph.pattern_catalog_models import (
    PATTERN_CARD_SCHEMA_VERSION,
    PATTERN_CATALOG_FORMAT_VERSION,
    PatternCatalog,
)
from anaxigraph.pattern_catalog_parse import pattern_card_from_dict

PATTERN_CATALOG_LOADER_VERSION = "pattern-catalog-loader-v1"
BUNDLED_PATTERN_CATALOG_VERSION = "2026.08.1"
MAX_BUNDLED_CATALOG_BYTES = 300_000
_CATALOG_DIRECTORY = "catalog"
_CATALOG_GLOB = "patterns-*.json"


@lru_cache(maxsize=1)
def bundled_pattern_catalog() -> PatternCatalog:
    """Return the validated package catalog without imposing a card-count ceiling."""

    root = files("anaxigraph").joinpath(_CATALOG_DIRECTORY)
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    sources = [(item.name, item.read_bytes()) for item in entries if _is_catalog(item.name)]
    catalog = _load_sources(sources, max_bytes=MAX_BUNDLED_CATALOG_BYTES)
    if catalog.catalog_version != BUNDLED_PATTERN_CATALOG_VERSION:
        raise ValueError("bundled pattern catalog version does not match the loader contract")
    return catalog


def load_pattern_catalog(path: str | Path, *, max_bytes: int = 300_000) -> PatternCatalog:
    """Load one catalog source or every catalog source in a directory."""

    target = Path(path).expanduser().resolve()
    if target.is_dir():
        paths = sorted(
            item for item in target.iterdir() if item.is_file() and _is_catalog(item.name)
        )
    elif target.is_file():
        paths = [target]
    else:
        raise ValueError(f"pattern catalog path does not exist: {target}")
    if not paths:
        raise ValueError("pattern catalog directory contains no pattern sources")
    return _load_sources(((item.name, item.read_bytes()) for item in paths), max_bytes=max_bytes)


def _is_catalog(name: str) -> bool:
    return name.startswith("patterns-") and name.endswith(".json")


def _load_sources(
    sources: Iterable[tuple[str, bytes]],
    *,
    max_bytes: int,
) -> PatternCatalog:
    if max_bytes < 1:
        raise ValueError("pattern catalog byte limit must be positive")
    cards = []
    versions: set[str] = set()
    total_bytes = 0
    for name, encoded in sources:
        total_bytes += len(encoded)
        if total_bytes > max_bytes:
            raise ValueError(f"pattern catalog exceeds the {max_bytes}-byte limit")
        try:
            source = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid pattern catalog JSON in {name}: {exc}") from exc
        family, defaults, source_cards, version = _validate_source(source, name)
        versions.add(version)
        cards.extend(
            pattern_card_from_dict(_expanded_card(card, family, defaults)) for card in source_cards
        )
    if len(versions) != 1:
        raise ValueError("all pattern catalog sources must share one catalog version")
    return PatternCatalog(
        catalog_version=versions.pop(),
        cards=tuple(sorted(cards, key=lambda card: card.stable_key)),
        source_bytes=total_bytes,
    )


def _validate_source(
    value: Any,
    name: str,
) -> tuple[str, dict[str, Any], list[Any], str]:
    if not isinstance(value, dict):
        raise ValueError(f"pattern catalog source {name} must be an object")
    if value.get("format_version") != PATTERN_CATALOG_FORMAT_VERSION:
        raise ValueError(f"unsupported pattern catalog format in {name}")
    if value.get("card_schema_version") != PATTERN_CARD_SCHEMA_VERSION:
        raise ValueError(f"unsupported pattern card schema in {name}")
    version = str(value.get("catalog_version") or "").strip()
    family = value.get("family")
    defaults = value.get("defaults")
    source_cards = value.get("cards")
    if not version:
        raise ValueError(f"pattern catalog source {name} requires a catalog version")
    if not isinstance(family, str) or not family:
        raise ValueError(f"pattern catalog source {name} requires a family")
    if not isinstance(defaults, dict):
        raise ValueError(f"pattern catalog source {name} requires defaults")
    if not isinstance(source_cards, list) or not source_cards:
        raise ValueError(f"pattern catalog source {name} requires cards")
    return family, defaults, source_cards, version


def _expanded_card(
    value: Any,
    family: str,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"pattern card in {family} must be an object")
    result = {**defaults, **value, "family": family}
    result["relations"] = {
        **_dict_default(defaults, "relations"),
        **_dict_default(value, "relations"),
    }
    result["scoring"] = {
        **_dict_default(defaults, "scoring"),
        **_dict_default(value, "scoring"),
    }
    return result


def _dict_default(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key) or {}
    if not isinstance(result, dict):
        raise ValueError(f"pattern card {key} must be an object")
    return result
