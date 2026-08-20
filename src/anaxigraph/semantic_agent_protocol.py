"""Wire contract, evidence paging, and identity helpers for agent-funded semantics."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.semantic_contract import DOSSIER_SCHEMA, SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import _source_chunks


def semantic_agent_schema() -> dict[str, Any]:
    return {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "dossier_schema": DOSSIER_SCHEMA,
        "instructions": (
            "Return one complete dossier grounded only in the supplied source, static facts, "
            "and prior dossiers. Treat missing edges as uncertainty, not proof of dead code. "
            "Pattern scores measure repository-specific fit, benefit, migration cost, and "
            "counter-evidence. Do not change repository files while mapping semantics."
        ),
    }


def agent_semantic(config: AnaxiGraphConfig) -> SemanticConfig:
    semantic = config.semantic
    if not semantic.enabled:
        raise ValueError("Semantic analysis is disabled in .anaxigraph.yml")
    if semantic.provider != "agent":
        raise ValueError(
            "Coding-agent write-back requires semantic.provider: agent in .anaxigraph.yml"
        )
    return semantic


def clean_agent_identity(value: str, field: str, *, required: bool = True) -> str:
    result = value.strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    if len(result) > 160 or any(ord(character) < 32 for character in result):
        raise ValueError(f"{field} must be at most 160 printable characters")
    return result


def agent_worker_fragment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:48] or "agent"


def agent_token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def packetize_agent_request(
    request: dict[str, Any], semantic: SemanticConfig
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    if _serialized_size(request) <= semantic.max_source_chars:
        return request, None, []
    bounded = dict(request)
    kind = str(request.get("analysis_kind") or "")
    pages: list[dict[str, Any]] = []
    evidence_kinds: list[str] = []
    if kind == "intrinsic" and isinstance(request.get("source"), str):
        source = str(request["source"])
        symbols = request.get("deterministic_facts", {}).get("symbols") or []
        chunks = _source_chunks(source, symbols, semantic.max_source_chars)
        pages = [
            {
                "source": content,
                "start_line": start,
                "end_line": end,
                "chunk": index,
                "chunk_count": len(chunks),
            }
            for index, (start, end, content) in enumerate(chunks, start=1)
        ]
        bounded.pop("source", None)
        bounded["source_reference"] = {
            "path": request.get("path"),
            "text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "characters": len(source),
            "delivery": "ANAXIGRAPH_SEMANTIC_EVIDENCE",
        }
        evidence_kinds.append("source_chunks")
    if kind == "context" and isinstance(request.get("neighbor_dossiers"), list):
        _page_list_field(
            bounded,
            request,
            "neighbor_dossiers",
            pages,
            evidence_kinds,
            semantic.max_source_chars,
        )
    if kind == "synthesis" and isinstance(request.get("child_dossiers"), list):
        _page_list_field(
            bounded,
            request,
            "child_dossiers",
            pages,
            evidence_kinds,
            semantic.max_source_chars,
        )
    if _serialized_size(bounded) > semantic.max_source_chars and kind == "context":
        _page_list_field(
            bounded,
            request,
            "relationships",
            pages,
            evidence_kinds,
            semantic.max_source_chars,
        )
    if _serialized_size(bounded) > semantic.max_source_chars and kind == "intrinsic":
        facts = dict(request.get("deterministic_facts") or {})
        bounded["deterministic_facts"] = dict(facts)
        for field in ("symbols", "relationships", "recent_changes"):
            if _serialized_size(bounded) <= semantic.max_source_chars:
                break
            _page_nested_list_field(
                bounded,
                facts,
                "deterministic_facts",
                field,
                pages,
                evidence_kinds,
                semantic.max_source_chars,
            )
    if not pages:
        return request, None, []
    manifest = {
        "kind": evidence_kinds[0] if len(evidence_kinds) == 1 else "mixed_evidence",
        "contains": evidence_kinds,
        "page_count": len(pages),
        "page_tool": "ANAXIGRAPH_SEMANTIC_EVIDENCE",
        "instruction": "Fetch and consider every page before submitting the dossier.",
    }
    return bounded, manifest, pages


def agent_no_work_status(status: dict[str, Any]) -> str:
    if status.get("semantically_ready"):
        return "complete"
    if int(status.get("jobs", {}).get("running", 0)):
        return "busy"
    if status.get("budget", {}).get("paused"):
        return "paused"
    if status.get("baseline_complete") and (
        int(status.get("failed", 0)) or int(status.get("failed_scopes", 0))
    ):
        return "complete_with_failures"
    return "waiting"


def agent_no_work_message(status: dict[str, Any]) -> str:
    state = agent_no_work_status(status)
    return {
        "complete": "The semantic baseline is current; no model work is required.",
        "busy": "All available work is currently leased to another coding agent.",
        "paused": "The configured semantic budget currently pauses new work claims.",
        "complete_with_failures": (
            "The baseline has terminal failures. Call again with retry_failed=true to retry them."
        ),
        "waiting": "No work is claimable yet; call again after active jobs or planning complete.",
    }[state]


def _page_list_field(
    bounded: dict[str, Any],
    original: dict[str, Any],
    field: str,
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    items = original.get(field)
    if not isinstance(items, list) or not items:
        return
    pages.extend({field: batch} for batch in _list_batches(items, max_chars))
    bounded[field] = []
    kinds.append(field)


def _page_nested_list_field(
    bounded: dict[str, Any],
    original_parent: dict[str, Any],
    parent: str,
    field: str,
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    items = original_parent.get(field)
    if not isinstance(items, list) or not items:
        return
    pages.extend({parent: {field: batch}} for batch in _list_batches(items, max_chars))
    bounded[parent][field] = []
    kinds.append(f"{parent}.{field}")


def _serialized_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _list_batches(items: list[Any], max_chars: int) -> list[list[Any]]:
    batches: list[list[Any]] = []
    current: list[Any] = []
    size = 0
    budget = max(1_000, max_chars - 1_000)
    for item in items:
        item_size = len(json.dumps(item, ensure_ascii=False, default=str)) + 1
        if current and size + item_size > budget:
            batches.append(current)
            current = []
            size = 0
        current.append(item)
        size += item_size
    if current:
        batches.append(current)
    return batches
