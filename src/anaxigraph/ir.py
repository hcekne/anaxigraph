"""Versioned, provider-neutral identities shared by every analyzer."""

from __future__ import annotations

from typing import Any

from anaxigraph.ir_identity import (
    canonical_python_module,
    module_identity_fields,
    python_module_aliases,
)
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
    return ModuleIdentity(**module_identity_fields(path, language))


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
