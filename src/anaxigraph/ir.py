"""Versioned, provider-neutral identities shared by every analyzer."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from anaxigraph.languages import artifact_type, detect_language
from anaxigraph.models import (
    IR_SCHEMA_VERSION,
    PARSE_STATUSES,
    REFERENCE_FORMS,
    REFERENCE_KINDS,
    VISIBILITIES,
    Dependency,
    ModuleIdentity,
    ResolverContext,
    Symbol,
)

__all__ = [
    "IR_SCHEMA_VERSION",
    "Dependency",
    "ModuleIdentity",
    "PARSE_STATUSES",
    "REFERENCE_FORMS",
    "REFERENCE_KINDS",
    "ResolverContext",
    "Symbol",
    "VISIBILITIES",
    "analyze_with_contract",
    "analysis_from_stored",
    "analysis_metadata",
    "artifact_type",
    "canonical_python_module",
    "detect_language",
    "ensure_analysis_conforms",
    "module_identity",
    "python_module_aliases",
    "resolver_context",
    "symbol_visibility",
]


def module_identity(path: str, language: str) -> ModuleIdentity:
    normalized = path.replace("\\", "/").removeprefix("./")
    if language == "python":
        canonical = canonical_python_module(normalized)
        aliases = tuple(sorted(python_module_aliases(normalized)))
    else:
        pure = PurePosixPath(normalized)
        canonical = ".".join(pure.with_suffix("").parts)
        aliases = (canonical,) if canonical else ()
    package_name = canonical.split(".", 1)[0] if canonical else ""
    return ModuleIdentity(normalized, language, canonical, package_name, aliases)


def resolver_context(
    identity: ModuleIdentity,
    *,
    import_aliases: dict[str, str] | None = None,
    configured_aliases: dict[str, str] | None = None,
    candidate_roots: tuple[str, ...] = (),
) -> ResolverContext:
    return ResolverContext(
        importer_path=identity.path,
        module_name=identity.canonical_name,
        package_name=identity.package_name,
        import_aliases=tuple(sorted((import_aliases or {}).items())),
        configured_aliases=tuple(sorted((configured_aliases or {}).items())),
        candidate_roots=tuple(sorted(set(candidate_roots))),
    )


def canonical_python_module(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def python_module_aliases(path: str) -> set[str]:
    canonical = canonical_python_module(path)
    parts = canonical.split(".")
    aliases = {canonical}
    if len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    if "src" in parts:
        aliases.add(".".join(parts[parts.index("src") + 1 :]))
    for marker in ("app", "lib", "server"):
        if marker in parts:
            aliases.add(".".join(parts[parts.index(marker) :]))
    return {alias for alias in aliases if alias}


def symbol_visibility(name: str) -> str:
    if name.startswith("__") and not name.endswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


def ensure_analysis_conforms(analyzer: Any, path: str, analysis: Any) -> None:
    from anaxigraph.ir_conformance import ensure_analysis_conforms as ensure

    ensure(analyzer, path, analysis)


def analyze_with_contract(analyzer: Any, path: str, content: str) -> Any:
    analysis = analyzer.analyze(path, content)
    ensure_analysis_conforms(analyzer, path, analysis)
    return analysis


def analysis_metadata(
    analysis: Any,
    *,
    analysis_version: int,
    configured_aliases: dict[str, str],
) -> dict[str, Any]:
    from anaxigraph.ir_serialization import analysis_metadata as serialize

    return serialize(
        analysis,
        analysis_version=analysis_version,
        configured_aliases=configured_aliases,
    )


def analysis_from_stored(value: dict[str, Any]) -> Any:
    from anaxigraph.ir_serialization import analysis_from_stored as deserialize

    return deserialize(value)
