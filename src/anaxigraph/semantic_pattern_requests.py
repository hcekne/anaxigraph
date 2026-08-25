"""Size-limited evidence for pattern assessment and a separate AI check."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from anaxigraph.pattern_evaluation_contract import (
    PATTERN_REVIEW_CONTRACT_VERSION,
    PATTERN_SCORE_CONTRACT_VERSION,
)
from anaxigraph.persistence.semantic_evidence import module_facts
from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_contract import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_records import _document_by_id


def pattern_request(
    database: SemanticIndex,
    job: dict[str, Any],
    root: Path,
    semantic: SemanticConfig,
) -> dict[str, Any]:
    metadata = job["metadata"]
    kind = str(job["job_kind"])
    request = {
        "contract": _contract(kind),
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "analysis_kind": kind,
        "candidate": metadata["candidate"],
        "pattern": metadata["pattern"],
        "target_evidence": metadata["target_evidence"],
        "score_contract_version": PATTERN_SCORE_CONTRACT_VERSION,
        "review_contract_version": PATTERN_REVIEW_CONTRACT_VERSION,
        "constraints": _constraints(),
    }
    request.update(_source_evidence(database, job, root, semantic))
    if kind == "pattern_review":
        request["assessment"] = _assessment(database, metadata)
    return request


def _contract(kind: str) -> str:
    if kind == "pattern_assessment":
        return (
            "Evaluate this one possible pattern match against the supplied evidence from this "
            "repository. Answer every score question separately. A pattern can fit well and "
            "already be present, which usually means no code change is useful. Return every "
            "required result field. Do not edit source or ask a person to approve the answer."
        )
    if kind == "pattern_review":
        return (
            "Independently check the supplied pattern result. Check whether it judged the right "
            "piece of code and the right pattern, considered simpler alternatives and evidence "
            "against the idea, used its scores consistently, counted the work and disruption of "
            "changing code, and avoided adding more concepts than the problem needs. Return every "
            "field of the corrected result even when the first result was right. Keep a different "
            "explanation when evidence truly supports both. Do not ask a person to approve it."
        )
    raise ValueError(f"unsupported pattern job kind: {kind}")


def _constraints() -> dict[str, Any]:
    return {
        "score_range": [0, 100],
        "independent_dimensions": [
            "applicability",
            "suitability",
            "conformance",
            "opportunity",
            "confidence",
            "benefit",
            "urgency",
            "execution_safety",
            "migration_cost",
        ],
        "score_meanings": {
            "applicability": "Does this pattern address the kind of problem found here?",
            "suitability": "How well does this pattern fit this exact code and repository?",
            "conformance": "How much of this pattern does the code already use?",
            "opportunity": "How much evidence says changing the code would help?",
            "confidence": "How strongly does the supplied evidence support this result?",
            "benefit": "How much could the supported change improve the code?",
            "urgency": "How soon, if at all, does this need attention?",
            "execution_safety": "How safely could the change be made and checked in small steps?",
            "migration_cost": (
                "How much work and disruption would the change require? A higher score means "
                "more cost, not a better result."
            ),
        },
        "high_conformance_rule": (
            "High suitability plus high conformance describes a retained example, not a high "
            "refactoring opportunity."
        ),
        "evidence_rule": "Cite supplied facts and explicitly record counter-evidence.",
        "language_rule": (
            "Write summaries, reasons, evidence, cautions, and verification rules in short, "
            "ordinary sentences that a smart twelve-year-old and another coding agent can both "
            "understand. Explain necessary design terms when they first appear."
        ),
        "automation": "Complete the map without a human approval or edit gate.",
    }


def _assessment(database: SemanticIndex, metadata: dict[str, Any]) -> dict[str, Any]:
    document_id = int(metadata.get("assessment_document_id") or 0)
    if not document_id:
        raise SupersededSemanticJob("Pattern review no longer has its assessment document")
    with database.connect() as connection:
        return _document_by_id(connection, document_id)["value"]


def _source_evidence(
    database: SemanticIndex,
    job: dict[str, Any],
    root: Path,
    semantic: SemanticConfig,
) -> dict[str, Any]:
    target = job["metadata"]["candidate"].get("target") or {}
    path = str(target.get("path") or "")
    if not path:
        return {}
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
        raise SupersededSemanticJob("The file for this pattern check no longer exists")
    raw = candidate.read_bytes()
    with database.connect() as connection:
        version, symbols = module_facts(
            connection, int(job["snapshot_id"]), int(job["artifact_id"])
        )
    if version is None or version["raw_hash"] != hashlib.sha256(raw).hexdigest():
        raise SupersededSemanticJob("The pattern target changed after this work was planned")
    source, line_range, truncated = _bounded_source(
        raw.decode("utf-8", errors="replace"),
        target,
        symbols,
        min(50_000, max(4_000, semantic.max_source_chars // 2)),
    )
    return {
        "path": path,
        "language": version["language"],
        "source": source,
        "source_range": line_range,
        "source_truncated": truncated,
    }


def _bounded_source(
    source: str,
    target: dict[str, Any],
    symbols: list[dict[str, Any]],
    limit: int,
) -> tuple[str, dict[str, int], bool]:
    lines = source.splitlines(keepends=True)
    selected = _target_lines(target, symbols, len(lines))
    if selected is not None:
        start, end = selected
        excerpt = "".join(lines[start - 1 : end])
        if len(excerpt) <= limit:
            return excerpt, {"start_line": start, "end_line": end}, len(excerpt) < len(source)
    if len(source) <= limit:
        return source, {"start_line": 1, "end_line": len(lines)}, False
    head = source[: limit // 2]
    tail = source[-(limit // 2) :]
    marker = "\n# … source middle omitted to keep this evidence page small …\n"
    return head + marker + tail, {"start_line": 1, "end_line": len(lines)}, True


def _target_lines(
    target: dict[str, Any], symbols: list[dict[str, Any]], total_lines: int
) -> tuple[int, int] | None:
    if target.get("level") not in {"symbol", "type"}:
        return None
    label = str(target.get("label") or "")
    symbol = next((item for item in symbols if item["name"] == label), None)
    if symbol is None:
        return None
    return max(1, int(symbol["start_line"]) - 20), min(total_lines, int(symbol["end_line"]) + 20)
