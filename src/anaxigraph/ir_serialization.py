"""Compatibility bridge between versioned analyzer IR and current snapshot rows."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from anaxigraph.models import (
    IR_SCHEMA_VERSION,
    Dependency,
    FileAnalysis,
    ModuleIdentity,
    ResolverContext,
    Symbol,
)


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
                visibility=details.get("visibility", "unknown"),
                start_column=int(details.get("start_column", 0)),
                end_column=int(details.get("end_column", 0)),
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
