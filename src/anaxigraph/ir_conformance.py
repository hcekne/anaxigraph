"""Executable conformance checks for the versioned analyzer IR contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from anaxigraph.models import (
    IR_SCHEMA_VERSION,
    PARSE_STATUSES,
    REFERENCE_KINDS,
    VISIBILITIES,
    FileAnalysis,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ConformanceIssue:
    field: str
    message: str


class AnalyzerConformanceError(ValueError):
    pass


class AnalyzerContract(Protocol):
    name: str
    version: str
    languages: frozenset[str]


def validate_analysis(
    analyzer: AnalyzerContract,
    path: str,
    analysis: FileAnalysis,
) -> tuple[ConformanceIssue, ...]:
    """Validate facts without making language-specific parsing assumptions."""

    issues: list[ConformanceIssue] = []

    def require(condition: bool, field: str, message: str) -> None:
        if not condition:
            issues.append(ConformanceIssue(field, message))

    require(analysis.ir_version == IR_SCHEMA_VERSION, "ir_version", "unsupported IR version")
    require(analysis.analyzer == analyzer.name, "analyzer", "result must identify its analyzer")
    require(
        analysis.analyzer_version == analyzer.version,
        "analyzer_version",
        "result version must match its analyzer",
    )
    require(analysis.language in analyzer.languages, "language", "language is not declared")
    require(bool(_SHA256.fullmatch(analysis.structural_hash)), "structural_hash", "not SHA-256")
    require(analysis.parse_status in PARSE_STATUSES, "parse_status", "unknown parse status")
    require(
        (analysis.parse_status == "parse_error") == bool(analysis.parse_error),
        "parse_error",
        "parse status and error must agree",
    )
    issues.extend(_identity_issues(path, analysis))
    issues.extend(_symbol_issues(analysis))
    issues.extend(_reference_issues(analysis))
    return tuple(issues)


def _identity_issues(path: str, analysis: FileAnalysis) -> list[ConformanceIssue]:
    issues = []
    identity = analysis.module_identity
    if identity is None:
        return [ConformanceIssue("module_identity", "module identity is required")]
    if identity.path != path:
        issues.append(ConformanceIssue("module_identity.path", "path must match input"))
    if identity.language != analysis.language:
        issues.append(ConformanceIssue("module_identity.language", "language differs"))
    if not identity.canonical_name:
        issues.append(ConformanceIssue("module_identity.canonical_name", "name is empty"))
    context = analysis.resolver_context
    if context is None:
        issues.append(ConformanceIssue("resolver_context", "resolver inputs are required"))
    elif context.importer_path != identity.path or context.module_name != identity.canonical_name:
        issues.append(ConformanceIssue("resolver_context", "module identity differs"))
    return issues


def _symbol_issues(analysis: FileAnalysis) -> list[ConformanceIssue]:
    issues = []
    for index, symbol in enumerate(analysis.symbols):
        prefix = f"symbols[{index}]"
        if not symbol.name or not symbol.qualified_name:
            issues.append(ConformanceIssue(prefix, "symbol identity is empty"))
        if symbol.start_line < 1 or symbol.end_line < symbol.start_line:
            issues.append(ConformanceIssue(f"{prefix}.span", "invalid source span"))
        if symbol.visibility not in VISIBILITIES:
            issues.append(ConformanceIssue(f"{prefix}.visibility", "unknown visibility"))
    return issues


def _reference_issues(analysis: FileAnalysis) -> list[ConformanceIssue]:
    issues = []
    for index, reference in enumerate(analysis.dependencies):
        prefix = f"dependencies[{index}]"
        if reference.relationship_type not in REFERENCE_KINDS or not reference.target:
            issues.append(ConformanceIssue(prefix, "reference kind or target is invalid"))
        if not 0 <= reference.confidence <= 1:
            issues.append(ConformanceIssue(f"{prefix}.confidence", "outside 0..1"))
        if reference.line < 0:
            issues.append(ConformanceIssue(f"{prefix}.line", "line cannot be negative"))
        if not reference.evidence:
            issues.append(ConformanceIssue(f"{prefix}.evidence", "source evidence is required"))
    return issues


def ensure_analysis_conforms(
    analyzer: AnalyzerContract,
    path: str,
    analysis: FileAnalysis,
) -> None:
    issues = validate_analysis(analyzer, path, analysis)
    if issues:
        details = "; ".join(f"{item.field}: {item.message}" for item in issues)
        raise AnalyzerConformanceError(f"{analyzer.name} produced invalid IR for {path}: {details}")
