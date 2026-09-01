"""Parser-backed JavaScript, JSX, TypeScript, and TSX analysis facades."""

from __future__ import annotations

import hashlib
from importlib.metadata import version as distribution_version
from pathlib import PurePosixPath
from typing import Any

from anaxigraph.analyzer_capabilities import declare_capabilities
from anaxigraph.analyzers.javascript_dependencies import extract_dependencies
from anaxigraph.analyzers.javascript_evidence import extract_javascript_evidence
from anaxigraph.analyzers.javascript_parser import (
    leading_comment,
    node_complexity,
    parse_source,
    parser_languages,
    source_metrics,
    structural_hash,
)
from anaxigraph.analyzers.javascript_semantics import module_semantics
from anaxigraph.analyzers.javascript_symbols import extract_symbols
from anaxigraph.ir import module_identity, resolver_context
from anaxigraph.languages import (
    ECMASCRIPT_ANALYZER_LANGUAGES,
    TYPESCRIPT_ANALYZER_LANGUAGES,
    detect_language,
)
from anaxigraph.models import FileAnalysis

_STRUCTURAL_FACTS = (
    "async_behavior",
    "calls",
    "complexity",
    "constructors",
    "control_flow",
    "decorators",
    "entry_points",
    "error_handling",
    "exports",
    "imports",
    "inheritance",
    "module_documentation",
    "mutation",
    "registrations",
    "signatures",
    "source_spans",
    "symbol_documentation",
    "symbol_kind",
    "symbol_visibility",
    "symbols",
    "test_relationships",
)
_PARSER_VERSIONS = {
    "binding": distribution_version("tree-sitter"),
    "javascript": distribution_version("tree-sitter-javascript"),
    "typescript": distribution_version("tree-sitter-typescript"),
}


class JavaScriptAnalyzer:
    name = "builtin-javascript-tree-sitter"
    version = "1"
    languages = ECMASCRIPT_ANALYZER_LANGUAGES
    capabilities = declare_capabilities(
        name,
        version,
        "structural",
        deep=("module_identity",),
        structural=_STRUCTURAL_FACTS,
        heuristic=("concurrency", "side_effects"),
        limitations=(
            "Call relationships cover imported roots rather than complete runtime dispatch.",
            "Dynamic expressions are retained as unresolved evidence rather than guessed targets.",
            "Data flow, generated modules, and runtime framework wiring are not inferred.",
        ),
    )

    def analyze(self, path: str, content: str) -> FileAnalysis:
        return _analyze(self, path, content, typescript=False)


class TypeScriptAnalyzer:
    name = "builtin-typescript-tree-sitter"
    version = "1"
    languages = TYPESCRIPT_ANALYZER_LANGUAGES
    capabilities = declare_capabilities(
        name,
        version,
        "structural",
        deep=("module_identity",),
        structural=(*_STRUCTURAL_FACTS, "annotations", "generics", "types"),
        heuristic=("concurrency", "side_effects"),
        limitations=(
            "Types, interfaces, decorators, and generics are syntax facts, not type-checker results.",
            "Call relationships cover imported roots rather than complete runtime dispatch.",
            "Project aliases resolve only from indexed configuration evidence; runtime wiring is absent.",
        ),
    )

    def analyze(self, path: str, content: str) -> FileAnalysis:
        return _analyze(self, path, content, typescript=True)


def _analyze(analyzer: Any, path: str, content: str, *, typescript: bool) -> FileAnalysis:
    language = detect_language(path) or ("typescript" if typescript else "javascript")
    identity = module_identity(path, language)
    try:
        parsed = parse_source(language, content)
    except (TypeError, ValueError, RuntimeError) as exc:
        return _parse_failure(analyzer, path, content, identity, language, exc)
    return _parsed_analysis(analyzer, path, language, identity, parsed, typescript=typescript)


def _parsed_analysis(
    analyzer: Any,
    path: str,
    language: str,
    identity: Any,
    parsed: Any,
    *,
    typescript: bool,
) -> FileAnalysis:
    dependencies = extract_dependencies(parsed)
    symbols = extract_symbols(path, parsed, dependencies)
    evidence = extract_javascript_evidence(
        path,
        parsed,
        symbols,
        dependencies,
        typescript=typescript,
    )
    summary, responsibilities, inputs, outputs, side_effects, public = module_semantics(
        path,
        language,
        leading_comment(parsed),
        symbols,
        dependencies,
        evidence,
    )
    semantics = summary, responsibilities, inputs, outputs, side_effects, public
    return _build_analysis(
        analyzer,
        language,
        identity,
        parsed,
        dependencies,
        symbols,
        evidence,
        semantics,
        source_metrics(parsed),
        typescript=typescript,
    )


def _build_analysis(
    analyzer: Any,
    language: str,
    identity: Any,
    parsed: Any,
    dependencies: Any,
    symbols: Any,
    evidence: Any,
    semantics: Any,
    metrics: tuple[int, int],
    *,
    typescript: bool,
) -> FileAnalysis:
    summary, responsibilities, inputs, outputs, side_effects, public = semantics
    lines_of_code, comment_lines = metrics
    return FileAnalysis(
        language=language,
        structural_hash=structural_hash(parsed),
        lines_of_code=lines_of_code,
        comment_lines=comment_lines,
        complexity=node_complexity(parsed.root),
        summary=summary,
        responsibilities=responsibilities,
        inputs=inputs,
        outputs=outputs,
        side_effects=side_effects,
        public_interfaces=public,
        symbols=symbols,
        dependencies=dependencies.dependencies,
        evidence_facts=evidence,
        parse_error=parsed.parse_error,
        analyzer=analyzer.name,
        metadata={
            "module_documentation": leading_comment(parsed),
            "parse_diagnostics": list(parsed.diagnostics),
            "parser": _parser_metadata(language, typescript=typescript),
        },
        module_identity=identity,
        exports=public,
        parse_status="parse_error" if parsed.parse_error else "parsed",
        analyzer_version=analyzer.version,
        resolver_context=resolver_context(identity, import_aliases=dependencies.aliases),
        analyzer_capabilities=analyzer.capabilities,
    )


def _parser_metadata(language: str, *, typescript: bool) -> dict[str, Any]:
    grammar = parser_languages()[language]
    return {
        "engine": "tree-sitter",
        "binding_version": _PARSER_VERSIONS["binding"],
        "grammar_version": (
            _PARSER_VERSIONS["typescript"] if typescript else _PARSER_VERSIONS["javascript"]
        ),
        "grammar_abi": grammar.abi_version,
    }


def _parse_failure(
    analyzer: Any,
    path: str,
    content: str,
    identity: Any,
    language: str,
    exc: Exception,
) -> FileAnalysis:
    normalized = content.replace("\r\n", "\n")
    return FileAnalysis(
        language=language,
        structural_hash=hashlib.sha256(normalized.encode()).hexdigest(),
        lines_of_code=sum(1 for line in normalized.splitlines() if line.strip()),
        comment_lines=0,
        complexity=1,
        summary=f"{language.title()} module {PurePosixPath(path).stem}",
        parse_error=f"{type(exc).__name__}: {exc}",
        analyzer=analyzer.name,
        metadata={"parser": {"engine": "tree-sitter", "failure": type(exc).__name__}},
        module_identity=identity,
        parse_status="parse_error",
        analyzer_version=analyzer.version,
        resolver_context=resolver_context(identity),
        analyzer_capabilities=analyzer.capabilities,
    )
