"""Small, provider-neutral records shared by extraction and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True, slots=True)
class Dependency:
    target: str
    relationship_type: str = "imports"
    line: int = 0
    evidence: str = ""
    confidence: float = 1.0
    names: tuple[str, ...] = ()


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
    parse_error: str | None = None
    analyzer: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GitMetadata:
    commit_sha: str
    parent_commit_sha: str | None
    branch: str
    commit_timestamp: str | None
    dirty: bool
    remote_url: str | None
    default_branch: str | None


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


@dataclass(frozen=True, slots=True)
class SemanticClaim:
    summary: str
    responsibilities: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    architectural_group: str | None = None
    source: str = "llm"
    provider: str = ""
    model: str = ""
    prompt_version: str = "v1"
    confidence: float = 0.0
    supporting_evidence: tuple[str, ...] = ()
