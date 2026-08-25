"""Small, provider-neutral records shared by extraction and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

IR_SCHEMA_VERSION = "anaxigraph-ir-v1"
PARSE_STATUSES = frozenset({"parsed", "lexical", "fallback", "parse_error"})
REFERENCE_KINDS = frozenset({"imports", "exports", "calls", "extends", "references"})
VISIBILITIES = frozenset({"public", "protected", "private", "unknown"})


@dataclass(frozen=True, slots=True)
class ModuleIdentity:
    """Stable analyzer view of a module before repository-wide resolution."""

    path: str
    language: str
    canonical_name: str
    package_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolverContext:
    """Inputs that make a reference-resolution result reproducible."""

    importer_path: str
    module_name: str
    package_name: str
    import_aliases: tuple[tuple[str, str], ...] = ()
    configured_aliases: tuple[tuple[str, str], ...] = ()
    candidate_roots: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Symbol:
    symbol_type: str
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: str = ""
    summary: str = ""
    complexity: int = 1
    logical_lines: int = 0
    visibility: str = "unknown"
    start_column: int = 0
    end_column: int = 0


@dataclass(frozen=True, slots=True)
class Dependency:
    target: str
    relationship_type: str = "imports"
    line: int = 0
    evidence: str = ""
    confidence: float = 1.0
    names: tuple[str, ...] = ()
    column: int = 0
    end_line: int = 0
    end_column: int = 0


@dataclass(slots=True)
class FileAnalysis:
    language: str
    structural_hash: str
    lines_of_code: int
    comment_lines: int
    complexity: int
    summary: str
    responsibilities: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    public_interfaces: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    evidence_facts: list[Any] = field(default_factory=list)
    parse_error: str | None = None
    analyzer: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    module_identity: ModuleIdentity | None = None
    exports: list[str] = field(default_factory=list)
    parse_status: str = "fallback"
    analyzer_version: str = "1"
    ir_version: str = IR_SCHEMA_VERSION
    resolver_context: ResolverContext | None = None
    analyzer_capabilities: Any | None = None


@dataclass(frozen=True, slots=True)
class GitMetadata:
    commit_sha: str
    parent_commit_sha: str | None
    branch: str
    commit_timestamp: str | None
    dirty: bool
    remote_url: str | None
    default_branch: str | None
    working_tree_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class ScanStats:
    repository_id: int
    snapshot_id: int
    analysis_run_id: int
    discovered: int
    analyzed: int
    reused: int
    deleted: int
    relationships: int
    findings: int
    duration_ms: int

    def as_dict(self) -> dict[str, int]:
        return {
            "repository_id": self.repository_id,
            "snapshot_id": self.snapshot_id,
            "analysis_run_id": self.analysis_run_id,
            "discovered": self.discovered,
            "analyzed": self.analyzed,
            "reused": self.reused,
            "deleted": self.deleted,
            "relationships": self.relationships,
            "findings": self.findings,
            "duration_ms": self.duration_ms,
        }
