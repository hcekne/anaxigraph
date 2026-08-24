"""Stable, repository-scoped identities for multi-level pattern analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import quote

PATTERN_TARGET_SCHEMA_VERSION = "pattern-target-v1"
PATTERN_TARGET_LEVELS = ("symbol", "type", "module", "subsystem", "area", "repository")
TYPE_SYMBOL_KINDS = frozenset(
    {
        "class",
        "database_model",
        "enum",
        "interface",
        "protocol",
        "record",
        "struct",
        "trait",
        "type_alias",
    }
)


@dataclass(frozen=True, slots=True)
class PatternTarget:
    """A deterministic identity; database row ids and source lines are deliberately excluded."""

    key: str
    level: str
    label: str
    parent_key: str | None = None
    path: str = ""
    identity: str = ""
    qualified_name: str = ""
    symbol_kind: str = ""
    source: str = "deterministic"
    schema_version: str = PATTERN_TARGET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.level not in PATTERN_TARGET_LEVELS:
            raise ValueError(f"unsupported pattern target level: {self.level}")
        if not self.label:
            raise ValueError("pattern target label cannot be empty")
        expected = target_key(
            self.level,
            path=self.path,
            identity=self.identity,
        )
        if self.key != expected:
            raise ValueError(f"pattern target key must be {expected}")
        if self.level != "repository" and not self.parent_key:
            raise ValueError(f"{self.level} pattern target requires a parent")
        if self.level == "repository" and self.parent_key is not None:
            raise ValueError("repository pattern target cannot have a parent")

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


def target_key(level: str, *, path: str = "", identity: str = "") -> str:
    """Build a portable key whose identity is stable across scans with unchanged structure."""

    if level not in PATTERN_TARGET_LEVELS:
        raise ValueError(f"unsupported pattern target level: {level}")
    if level == "repository":
        return "repository:root"
    if level == "module":
        normalized = _normalize_path(path)
        if not normalized:
            raise ValueError("module target requires a path")
        return f"module:{_encode(normalized, safe='/._-')}"
    if level in {"symbol", "type"}:
        normalized = _normalize_path(path)
        if not normalized or not identity:
            raise ValueError(f"{level} target requires path and qualified identity")
        return f"{level}:{_encode(normalized, safe='/._-')}#{_encode(identity, safe='._-$')}"
    if not identity:
        raise ValueError(f"{level} target requires an architecture identity")
    return f"{level}:{_encode(identity, safe='._-')}"


def repository_target(label: str) -> PatternTarget:
    return PatternTarget(key="repository:root", level="repository", label=label)


def area_target(identity: str, label: str, *, source: str) -> PatternTarget:
    return PatternTarget(
        key=target_key("area", identity=identity),
        level="area",
        label=label,
        parent_key="repository:root",
        identity=identity,
        source=source,
    )


def subsystem_target(
    identity: str,
    label: str,
    *,
    area_key: str,
    source: str,
) -> PatternTarget:
    return PatternTarget(
        key=target_key("subsystem", identity=identity),
        level="subsystem",
        label=label,
        parent_key=area_key,
        identity=identity,
        source=source,
    )


def module_target(path: str, *, subsystem_key: str) -> PatternTarget:
    normalized = _normalize_path(path)
    return PatternTarget(
        key=target_key("module", path=normalized),
        level="module",
        label=normalized.rsplit("/", 1)[-1],
        parent_key=subsystem_key,
        path=normalized,
    )


def symbol_target(
    path: str,
    qualified_name: str,
    symbol_kind: str,
    *,
    parent_key: str,
    label: str,
    identity: str | None = None,
) -> PatternTarget:
    level = target_level_for_symbol(symbol_kind)
    normalized = _normalize_path(path)
    stable_identity = identity or qualified_name
    return PatternTarget(
        key=target_key(level, path=normalized, identity=stable_identity),
        level=level,
        label=label,
        parent_key=parent_key,
        path=normalized,
        identity=stable_identity,
        qualified_name=qualified_name,
        symbol_kind=symbol_kind,
    )


def target_level_for_symbol(symbol_kind: str) -> str:
    return "type" if symbol_kind in TYPE_SYMBOL_KINDS else "symbol"


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").strip("/")


def _encode(value: str, *, safe: str) -> str:
    return quote(value, safe=safe)
