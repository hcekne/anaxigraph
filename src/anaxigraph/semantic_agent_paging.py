"""Bound large semantic requests into MCP work packets and evidence pages."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from anaxigraph.semantic_graph import _source_chunks


class _PagingConfig(Protocol):
    max_source_chars: int


def packetize_agent_request(
    request: dict[str, Any], semantic: _PagingConfig
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    if _serialized_size(request) <= semantic.max_source_chars:
        return request, None, []
    bounded = dict(request)
    kind = str(request.get("analysis_kind") or "")
    pages: list[dict[str, Any]] = []
    evidence_kinds: list[str] = []
    _page_oversized_request(
        bounded,
        request,
        kind,
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
        "instruction": "Fetch and consider every page before submitting the response artifact.",
    }
    return bounded, manifest, pages


def _page_oversized_request(
    bounded: dict[str, Any],
    request: dict[str, Any],
    kind: str,
    pages: list[dict[str, Any]],
    evidence_kinds: list[str],
    max_chars: int,
) -> None:
    if kind == "intrinsic" and isinstance(request.get("source"), str):
        _page_source(bounded, request, pages, evidence_kinds, max_chars)
    if kind == "context" and isinstance(request.get("neighbor_dossiers"), list):
        _page_list_field(
            bounded,
            request,
            "neighbor_dossiers",
            pages,
            evidence_kinds,
            max_chars,
        )
    if kind == "synthesis" and isinstance(request.get("child_dossiers"), list):
        _page_list_field(
            bounded,
            request,
            "child_dossiers",
            pages,
            evidence_kinds,
            max_chars,
        )
    if kind.startswith("taxonomy_"):
        _page_taxonomy_request(bounded, request, pages, evidence_kinds, max_chars)
    if kind.startswith("pattern_"):
        _page_pattern_request(bounded, request, pages, evidence_kinds, max_chars)
    if kind.startswith("fresh_"):
        _page_fresh_eyes_request(bounded, request, pages, evidence_kinds, max_chars)
    if _serialized_size(bounded) > max_chars and kind == "context":
        _page_list_field(
            bounded,
            request,
            "relationships",
            pages,
            evidence_kinds,
            max_chars,
        )
    if _serialized_size(bounded) > max_chars and kind == "intrinsic":
        _page_intrinsic_facts(bounded, request, pages, evidence_kinds, max_chars)


def _page_source(
    bounded: dict[str, Any],
    request: dict[str, Any],
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    source = str(request["source"])
    symbols = request.get("deterministic_facts", {}).get("symbols") or []
    chunks = _source_chunks(source, symbols, max_chars)
    pages.extend(
        {
            "source": content,
            "start_line": start,
            "end_line": end,
            "chunk": index,
            "chunk_count": len(chunks),
        }
        for index, (start, end, content) in enumerate(chunks, start=1)
    )
    bounded.pop("source", None)
    bounded["source_reference"] = {
        "path": request.get("path"),
        "text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "characters": len(source),
        "delivery": "ANAXIGRAPH_SEMANTIC_EVIDENCE",
    }
    kinds.append("source_chunks")


def _page_taxonomy_request(
    bounded: dict[str, Any],
    request: dict[str, Any],
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    for field in ("modules", "relationships"):
        if _serialized_size(bounded) <= max_chars:
            break
        _page_list_field(bounded, request, field, pages, kinds, max_chars)
    if _serialized_size(bounded) > max_chars:
        _page_taxonomy_field(bounded, request, "candidate_taxonomy", pages, kinds, max_chars)
    previous = request.get("previous_taxonomy")
    if _serialized_size(bounded) > max_chars and isinstance(previous, dict):
        bounded["previous_taxonomy"] = dict(previous)
        for field in ("memberships", "nodes"):
            if _serialized_size(bounded) <= max_chars:
                break
            _page_nested_list_field(
                bounded, previous, "previous_taxonomy", field, pages, kinds, max_chars
            )
    validation = request.get("deterministic_validation")
    if _serialized_size(bounded) > max_chars and isinstance(validation, dict):
        bounded["deterministic_validation"] = dict(validation)
        _page_nested_list_field(
            bounded,
            validation,
            "deterministic_validation",
            "issues",
            pages,
            kinds,
            max_chars,
        )


def _page_pattern_request(
    bounded: dict[str, Any],
    request: dict[str, Any],
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    if isinstance(request.get("source"), str):
        _page_source(bounded, request, pages, kinds, max_chars)
    evidence = request.get("target_evidence")
    if _serialized_size(bounded) > max_chars and isinstance(evidence, dict):
        bounded["target_evidence"] = dict(evidence)
        _page_nested_list_field(
            bounded,
            evidence,
            "target_evidence",
            "features",
            pages,
            kinds,
            max_chars,
        )


def _page_fresh_eyes_request(
    bounded: dict[str, Any],
    request: dict[str, Any],
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    if isinstance(request.get("proposals"), list):
        _page_list_field(bounded, request, "proposals", pages, kinds, max_chars)
    current = request.get("current_system")
    if isinstance(current, dict):
        bounded["current_system"] = dict(current)
        for field in (
            "module_dossiers",
            "area_summaries",
            "pattern_reviews",
            "dependency_evidence",
            "active_findings",
            "recent_history",
            "declared_context",
        ):
            if _serialized_size(bounded) <= max_chars:
                break
            _page_nested_list_field(
                bounded, current, "current_system", field, pages, kinds, max_chars
            )
    comparison = request.get("comparison")
    if _serialized_size(bounded) > max_chars and isinstance(comparison, dict):
        bounded["comparison"] = dict(comparison)
        for field in ("mappings", "candidate_changes", "current_strengths"):
            if _serialized_size(bounded) <= max_chars:
                break
            _page_nested_list_field(
                bounded, comparison, "comparison", field, pages, kinds, max_chars
            )
    if _serialized_size(bounded) > max_chars:
        _page_list_field(bounded, request, "declared_context", pages, kinds, max_chars)


def _page_intrinsic_facts(
    bounded: dict[str, Any],
    request: dict[str, Any],
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    facts = dict(request.get("deterministic_facts") or {})
    bounded["deterministic_facts"] = dict(facts)
    for field in ("symbols", "relationships", "recent_changes"):
        if _serialized_size(bounded) <= max_chars:
            break
        _page_nested_list_field(
            bounded, facts, "deterministic_facts", field, pages, kinds, max_chars
        )


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


def _page_taxonomy_field(
    bounded: dict[str, Any],
    original: dict[str, Any],
    field: str,
    pages: list[dict[str, Any]],
    kinds: list[str],
    max_chars: int,
) -> None:
    taxonomy = original.get(field)
    if not isinstance(taxonomy, dict):
        return
    bounded[field] = {
        "summary": str(taxonomy.get("summary") or "")[:500],
        "areas": [],
        "facets": [],
        "confidence": taxonomy.get("confidence", 0),
        "evidence": [],
    }
    for area_index, area in enumerate(taxonomy.get("areas") or [], start=1):
        _page_taxonomy_area(field, area, area_index, pages, max_chars)
    pages.extend(
        {field: {"kind": "facets", "facets": batch}}
        for batch in _list_batches(taxonomy.get("facets") or [], max_chars)
    )
    pages.extend(
        {field: {"kind": "evidence", "evidence": batch}}
        for batch in _list_batches(taxonomy.get("evidence") or [], max_chars)
    )
    kinds.append(field)


def _page_taxonomy_area(
    field: str,
    area: dict[str, Any],
    area_index: int,
    pages: list[dict[str, Any]],
    max_chars: int,
) -> None:
    area_key = str(area.get("key") or area.get("name") or f"area-{area_index}")
    pages.append(
        {
            field: {
                "kind": "area",
                "area": {key: value for key, value in area.items() if key != "subsystems"},
            }
        }
    )
    for subsystem_index, subsystem in enumerate(area.get("subsystems") or [], start=1):
        subsystem_key = str(
            subsystem.get("key") or subsystem.get("name") or f"subsystem-{subsystem_index}"
        )
        pages.append(
            {
                field: {
                    "kind": "subsystem",
                    "area_key": area_key,
                    "subsystem": {
                        key: value for key, value in subsystem.items() if key != "members"
                    },
                }
            }
        )
        pages.extend(
            {
                field: {
                    "kind": "memberships",
                    "area_key": area_key,
                    "subsystem_key": subsystem_key,
                    "members": batch,
                }
            }
            for batch in _list_batches(subsystem.get("members") or [], max_chars)
        )


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
