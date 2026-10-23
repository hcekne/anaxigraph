"""Size-limited evidence for pattern assessment and a separate AI check."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.pattern_catalogue_contract import (
    CATALOGUE_REVIEW_VERSION,
    CATALOGUE_SCORE_VERSION,
    assessment_fingerprint,
    is_catalogue_request,
)
from anaxigraph.pattern_evaluation_contract import (
    PATTERN_REVIEW_CONTRACT_VERSION,
    PATTERN_SCORE_CONTRACT_VERSION,
    PATTERN_SCORE_DIMENSIONS,
    pattern_recommendations,
)
from anaxigraph.persistence.pattern_manifest import manifest_card
from anaxigraph.persistence.semantic_evidence import module_facts
from anaxigraph.persistence.temporal_reads import snapshot_file_paths
from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_contract import SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_index_port import SemanticIndex
from anaxigraph.semantic_records import _document_by_id
from anaxigraph.semantic_target_source import read_mounted_source, require_unchanged_source
from anaxigraph.understandability import AGENT_REVIEW_POLICY


def pattern_request(
    database: SemanticIndex,
    job: dict[str, Any],
    root: Path,
    semantic: SemanticConfig,
) -> dict[str, Any]:
    metadata = job["metadata"]
    kind = str(job["job_kind"])
    catalogue = is_catalogue_request({"candidate": metadata["candidate"]})
    with database.connect() as connection:
        pattern = metadata.get("pattern") or manifest_card(
            connection, int(job["repository_id"]), int(job["snapshot_id"]), metadata["candidate"]
        )
    request = {
        "contract": _contract(kind, catalogue=catalogue),
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "analysis_kind": kind,
        "candidate": metadata["candidate"],
        "pattern": pattern,
        "target_evidence": metadata["target_evidence"],
        "score_contract_version": CATALOGUE_SCORE_VERSION
        if catalogue
        else PATTERN_SCORE_CONTRACT_VERSION,
        "review_contract_version": CATALOGUE_REVIEW_VERSION
        if catalogue
        else PATTERN_REVIEW_CONTRACT_VERSION,
        "constraints": _constraints(str(pattern.get("kind") or ""), catalogue=catalogue),
    }
    request.update(_source_evidence(database, job, root, semantic))
    if kind == "pattern_review":
        assessment = _assessment(database, metadata)
        request["assessment"] = assessment["value"]
        request["assessment_fingerprint"] = assessment_fingerprint(request["assessment"])
        request["assessment_input_hash"] = assessment["input_hash"]
    return request


def _contract(kind: str, *, catalogue=False) -> str:
    if catalogue:
        return _catalogue_contract(kind)
    if kind == "pattern_assessment":
        return (
            "Evaluate this one possible pattern match against the supplied evidence from this "
            "repository. Answer every score question separately using the pattern-kind-specific "
            "constraints. Presence alone is not a reason to change or retain code. Return every "
            "required result field. Do not edit source or ask a person to approve the answer."
        )
    if kind == "pattern_review":
        return (
            "Independently check the supplied pattern result. Check whether it judged the right "
            "piece of code and the right pattern, considered simpler alternatives and evidence "
            "against the idea, used its scores consistently, counted the work and disruption of "
            "changing code, and avoided adding more concepts than the problem needs. Rewrite any "
            "sentence that uses an expert term without explaining the concrete fact it represents. Return every "
            "field of the corrected result even when the first result was right. Keep a different "
            "explanation when evidence truly supports both. Do not ask a person to approve it."
        )
    raise ValueError(f"unsupported pattern job kind: {kind}")


def _catalogue_contract(kind: str) -> str:
    common = (
        "Consider this catalogue entry across the reviewed repository architecture, including "
        "places where it is absent. A bug is not required for a useful opportunity. Give the "
        "strongest concrete case for improving the design with this pattern and the strongest "
        "case against it; compare keeping the current design, a simpler change and related "
        "patterns. Rate every independent dimension and give contextual pros and cons. Identify "
        "relevant graph targets, preserved contracts, change-isolation effects, migration costs "
        "and verification. Supplied placement hints are leads, not a complete target inventory. "
        "Do not confuse a familiar current design with an optimal one, missing evidence with "
        "poor fit, or many connections with proof that a component must be split. "
    )
    if kind == "pattern_assessment":
        return (
            common
            + "Return the complete contextual assessment. Do not edit source or request approval."
        )
    return common + (
        "Independently critique the supplied assessment. Challenge overlooked opportunities, "
        "weak evidence and unnecessary abstractions. For approve, return evaluation=null and "
        "the supplied assessment_fingerprint and assessment_input_hash; the canonical assessment is retained once. For "
        "revise or retain_competing, supply the complete corrected evaluation and explain issues."
    )


def _constraints(pattern_kind: str = "constructive", *, catalogue=False) -> dict[str, Any]:
    result = {
        "score_range": [0, 100],
        "recommendations": list(pattern_recommendations(pattern_kind)),
        "independent_dimensions": list(PATTERN_SCORE_DIMENSIONS),
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
        "evidence_rule": "Cite supplied facts and explicitly record counter-evidence. "
        + AGENT_REVIEW_POLICY,
        "language_rule": (
            "Write summaries, reasons, evidence, cautions, and verification rules in short, "
            "ordinary sentences that a smart twelve-year-old and another coding agent can both "
            "understand. Explain necessary design terms when they first appear."
        ),
        "automation": "Complete the map without a human approval or edit gate.",
    }
    if pattern_kind == "failure_mode":
        result["score_meanings"].update(_failure_mode_score_meanings())
        result["high_conformance_rule"] = (
            "High conformance means strong presence of this failure mode, not a desirable design. "
            "Recommend remediate only for an evidenced harmful condition; avoid for prevention, "
            "no_action when changing it is unjustified, or insufficient_evidence when uncertain. "
            "Never retain, introduce, replace with, or improve conformance to a failure mode."
        )
    elif catalogue:
        result["high_conformance_rule"] = (
            "Assess conformance separately from opportunity. A pattern already used well in one "
            "area can still be useful elsewhere; do not clamp its repository-wide opportunity. "
            "An introduction or replacement needs a concrete, evidence-linked placement."
        )
    if catalogue:
        result["evidence_rule"] = _catalogue_evidence_rule()
    return result


def _catalogue_evidence_rule() -> str:
    return (
        "Assess this catalogue card explicitly even when no defect has been demonstrated. "
        "Consider repeated responsibilities, future change needs, clearer interfaces and useful "
        "separation. Compare the current approach, plausible applications of this pattern, "
        "and competing approaches. Rate all dimensions and give contextual pros and cons; "
        "poor fit and insufficient evidence are legitimate outcomes. Cite supplied witnesses "
        "and counter-evidence. Completing catalogue consideration does not require recommending "
        "every pattern, finding a bug, or inventing source facts."
    )


def _failure_mode_score_meanings() -> dict[str, str]:
    return {
        "applicability": "Is this the kind of problem this failure-mode diagnosis describes?",
        "suitability": "How well does this diagnosis explain the observed problem here?",
        "conformance": "How strongly does the code exhibit this harmful structure? Not quality.",
        "opportunity": "How much evidence says reducing this failure mode would help?",
        "benefit": "How much could reducing the harmful condition improve user-visible behavior?",
    }


def _assessment(database: SemanticIndex, metadata: dict[str, Any]) -> dict[str, Any]:
    document_id = int(metadata.get("assessment_document_id") or 0)
    if not document_id:
        raise SupersededSemanticJob("Pattern review no longer has its assessment document")
    with database.connect() as connection:
        return _document_by_id(connection, document_id)


def _source_evidence(
    database: SemanticIndex,
    job: dict[str, Any],
    root: Path,
    semantic: SemanticConfig,
) -> dict[str, Any]:
    target = job["metadata"]["candidate"].get("target") or {}
    path = str(target.get("path") or "")
    if not path:
        return _parent_source_evidence(database, job, root, semantic)
    raw = read_mounted_source(
        root, path, missing="The file for this pattern check no longer exists"
    )
    with database.connect() as connection:
        version, symbols = module_facts(
            connection, int(job["snapshot_id"]), int(job["artifact_id"])
        )
    require_unchanged_source(
        raw, version, changed="The pattern target changed after this work was planned"
    )
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


def _parent_source_evidence(database, job, root, semantic):
    target_evidence = job["metadata"]["target_evidence"]
    features = target_evidence.get("features") or []
    witness = next(
        (item["value"] for item in features if item["name"] == "architecture.witnesses"), {}
    )
    hints = [item["target"] for item in target_evidence.get("placement_hints") or []]
    hint_by_path = {item["path"]: item for item in hints if item.get("path")}
    paths = list(
        dict.fromkeys([*hint_by_path, *[item["path"] for item in witness.get("items") or []]])
    )
    if not paths:
        return {
            "source_witnesses": [],
            "source_caveat": "No current child source witnesses were available.",
        }
    witnesses = _witness_facts(database, int(job["snapshot_id"]), paths[:8])
    result = []
    for path in paths[:8]:
        raw = read_mounted_source(
            root, path, missing="A parent-pattern source witness no longer exists"
        )
        version, symbols = witnesses.get(path, (None, []))
        require_unchanged_source(
            raw, version, changed="A parent-pattern source witness changed after planning"
        )
        target = hint_by_path.get(path) or {}
        source, line_range, truncated = _bounded_source(
            raw.decode("utf-8", errors="replace"),
            target,
            symbols,
            min(5_000, max(1_000, semantic.max_source_chars // 8)),
        )
        result.append(
            {
                "path": path,
                "source": source,
                "source_range": line_range,
                "source_truncated": truncated,
            }
        )
    return {
        "source_witnesses": result,
        "source_caveat": "Bounded child examples, not exhaustive parent or runtime evidence.",
    }


def _witness_facts(database, snapshot, paths):
    with database.connect() as connection:
        identities = {
            path: identifier
            for identifier, path in snapshot_file_paths(connection, snapshot).items()
        }
        return {
            path: module_facts(connection, snapshot, identities[path])
            for path in paths
            if path in identities
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
    qualified = str(target.get("qualified_name") or "")
    symbol = next(
        (
            item
            for item in symbols
            if (item.get("qualified_name") == qualified if qualified else item["name"] == label)
        ),
        None,
    )
    if symbol is None:
        return None
    return max(1, int(symbol["start_line"]) - 20), min(total_lines, int(symbol["end_line"]) + 20)
