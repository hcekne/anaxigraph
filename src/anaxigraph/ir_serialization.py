"""Compatibility bridge between versioned analyzer IR and current snapshot rows."""

from __future__ import annotations

import dataclasses
import json
from pathlib import PurePosixPath
from typing import Any

from anaxigraph.models import (
    IR_SCHEMA_VERSION,
    Dependency,
    FileAnalysis,
    ModuleIdentity,
    ResolverContext,
    Symbol,
)

_DEPENDENCY_DEFAULTS = {
    "relationship_type": "imports",
    "line": 0,
    "evidence": "",
    "confidence": 1.0,
    "names": [],
    "column": 0,
    "end_line": 0,
    "end_column": 0,
}


def analysis_metadata(
    analysis: FileAnalysis,
    *,
    analysis_version: int,
    configured_aliases: dict[str, str],
) -> dict[str, Any]:
    metadata = dict(analysis.metadata)
    context = analysis.resolver_context
    if context is not None:
        context = dataclasses.replace(
            context,
            configured_aliases=tuple(sorted(configured_aliases.items())),
        )
    metadata.update(
        {
            "analysis_version": analysis_version,
            "dependencies": [dataclasses.asdict(value) for value in analysis.dependencies],
            "ir": {
                "schema_version": analysis.ir_version,
                "analyzer_version": analysis.analyzer_version,
                "module_identity": (
                    dataclasses.asdict(analysis.module_identity)
                    if analysis.module_identity is not None
                    else None
                ),
                "resolver_context": dataclasses.asdict(context) if context is not None else None,
                "parse_status": analysis.parse_status,
                "exports": analysis.exports,
                "symbols": [
                    {
                        "qualified_name": item.qualified_name,
                        "start_line": item.start_line,
                        "visibility": item.visibility,
                        "start_column": item.start_column,
                        "end_column": item.end_column,
                    }
                    for item in analysis.symbols
                ],
            },
        }
    )
    return metadata


def analysis_from_stored(value: dict[str, Any]) -> FileAnalysis:
    metadata = json.loads(value["metadata_json"] or "{}")
    dependencies = [
        Dependency(**{**item, "names": tuple(item.get("names") or ())})
        for item in metadata.pop("dependencies", [])
    ]
    ir = metadata.pop("ir", {})
    symbols = _stored_symbols(value["symbols"], ir.get("symbols", []))
    identity_value = ir.get("module_identity")
    context_value = ir.get("resolver_context")
    return FileAnalysis(
        language=value["language"],
        structural_hash=value["structural_hash"],
        lines_of_code=int(value["lines_of_code"]),
        comment_lines=int(value["comment_lines"]),
        complexity=int(value["complexity"]),
        summary=value["summary"],
        responsibilities=json.loads(value["responsibilities_json"]),
        inputs=json.loads(value["inputs_json"]),
        outputs=json.loads(value["outputs_json"]),
        side_effects=json.loads(value["side_effects_json"]),
        public_interfaces=json.loads(value["public_interfaces_json"]),
        symbols=symbols,
        dependencies=dependencies,
        parse_error=value["parse_error"],
        analyzer=value["analyzer"],
        metadata=metadata,
        module_identity=_stored_identity(identity_value),
        exports=list(ir.get("exports") or []),
        parse_status=str(
            ir.get("parse_status") or ("parse_error" if value["parse_error"] else "fallback")
        ),
        analyzer_version=str(ir.get("analyzer_version") or "legacy"),
        ir_version=str(ir.get("schema_version") or IR_SCHEMA_VERSION),
        resolver_context=_stored_context(context_value),
    )


def compact_stored_metadata(
    metadata: dict[str, Any],
    *,
    path: str,
    language: str,
    public_interfaces: list[str],
) -> dict[str, Any]:
    """Remove derivable IR fields while preserving an expandable JSON contract."""

    result = dict(metadata)
    result["dependencies"] = [
        _compact_dependency(item) for item in metadata.get("dependencies", [])
    ]
    ir = dict(metadata.get("ir") or {})
    identity = ir.get("module_identity")
    if identity == _derived_identity(path, language):
        ir.pop("module_identity", None)
    context = ir.get("resolver_context")
    if isinstance(context, dict):
        ir["resolver_context"] = {
            key: value
            for key, value in context.items()
            if key not in {"importer_path", "module_name", "package_name"} and value
        }
    if ir.get("exports") == public_interfaces:
        ir.pop("exports", None)
    if ir.get("schema_version") == IR_SCHEMA_VERSION:
        ir.pop("schema_version", None)
    if ir.get("analyzer_version") == "1":
        ir.pop("analyzer_version", None)
    ir.pop("symbols", None)
    result["ir"] = ir
    return result


def expand_stored_metadata(
    metadata: dict[str, Any],
    *,
    path: str,
    language: str,
    public_interfaces: list[str],
) -> dict[str, Any]:
    """Restore the stable analyzer-IR shape exposed by canonical snapshot reads."""

    result = dict(metadata)
    result["dependencies"] = [_expand_dependency(item) for item in metadata.get("dependencies", [])]
    ir = dict(metadata.get("ir") or {})
    if "module_identity" not in ir:
        ir["module_identity"] = _derived_identity(path, language)
    identity = ir.get("module_identity") or _derived_identity(path, language)
    context = ir.get("resolver_context")
    if isinstance(context, dict):
        ir["resolver_context"] = {
            "importer_path": identity["path"],
            "module_name": identity["canonical_name"],
            "package_name": identity["package_name"],
            "import_aliases": [],
            "configured_aliases": [],
            "candidate_roots": [],
            **context,
        }
    ir.setdefault("exports", list(public_interfaces))
    ir.setdefault("schema_version", IR_SCHEMA_VERSION)
    ir.setdefault("analyzer_version", "1")
    ir.setdefault("symbols", [])
    result["ir"] = ir
    return result


def _stored_symbols(rows: list[dict[str, Any]], details_rows: list[dict[str, Any]]) -> list[Symbol]:
    symbol_ir = {(item["qualified_name"], int(item["start_line"])): item for item in details_rows}
    symbols = []
    for item in rows:
        details = symbol_ir.get((item["qualified_name"], int(item["start_line"])), {})
        symbols.append(
            Symbol(
                symbol_type=item["symbol_type"],
                name=item["name"],
                qualified_name=item["qualified_name"],
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                signature=item["signature"],
                summary=item["summary"],
                complexity=int(item["complexity"]),
                logical_lines=int(item["logical_lines"]),
                visibility=details.get("visibility", item.get("visibility", "unknown")),
                start_column=int(details.get("start_column", item.get("start_column", 0))),
                end_column=int(details.get("end_column", item.get("end_column", 0))),
            )
        )
    return symbols


def _stored_identity(value: dict[str, Any] | None) -> ModuleIdentity | None:
    if not value:
        return None
    return ModuleIdentity(
        path=value["path"],
        language=value["language"],
        canonical_name=value["canonical_name"],
        package_name=value["package_name"],
        aliases=tuple(value.get("aliases") or ()),
    )


def _stored_context(value: dict[str, Any] | None) -> ResolverContext | None:
    if not value:
        return None
    return ResolverContext(
        importer_path=value["importer_path"],
        module_name=value["module_name"],
        package_name=value["package_name"],
        import_aliases=tuple(tuple(item) for item in value.get("import_aliases") or ()),
        configured_aliases=tuple(tuple(item) for item in value.get("configured_aliases") or ()),
        candidate_roots=tuple(value.get("candidate_roots") or ()),
    )


def _derived_identity(path: str, language: str) -> dict[str, Any]:
    normalized = path.replace("\\", "/").removeprefix("./")
    pure = PurePosixPath(normalized)
    canonical = ".".join(pure.with_suffix("").parts)
    if language == "python":
        parts = list(pure.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        canonical = ".".join(parts)
        aliases = {canonical}
        if len(parts) > 1:
            aliases.add(".".join(parts[1:]))
        if "src" in parts:
            aliases.add(".".join(parts[parts.index("src") + 1 :]))
        for marker in ("app", "lib", "server"):
            if marker in parts:
                aliases.add(".".join(parts[parts.index(marker) :]))
    else:
        aliases = {canonical}
    return {
        "path": normalized,
        "language": language,
        "canonical_name": canonical,
        "package_name": canonical.split(".", 1)[0] if canonical else "",
        "aliases": sorted(alias for alias in aliases if alias),
    }


def _compact_dependency(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key == "target" or item != _DEPENDENCY_DEFAULTS.get(key)
    }


def _expand_dependency(value: dict[str, Any]) -> dict[str, Any]:
    return {**_DEPENDENCY_DEFAULTS, **value}
