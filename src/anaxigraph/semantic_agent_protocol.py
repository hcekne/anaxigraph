"""Wire contract, evidence paging, and identity helpers for agent-funded semantics."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from anaxigraph.config import AnaxiGraphConfig, SemanticConfig
from anaxigraph.pattern_evaluation_contract import (
    PATTERN_EVALUATION_SCHEMA,
    PATTERN_REVIEW_SCHEMA,
)
from anaxigraph.semantic_contract import DOSSIER_SCHEMA, SEMANTIC_SCHEMA_VERSION
from anaxigraph.semantic_graph import _source_chunks
from anaxigraph.semantic_taxonomy_contract import (
    TAXONOMY_REVIEW_SCHEMA,
    TAXONOMY_SCHEMA,
)


def semantic_agent_schema() -> dict[str, Any]:
    return {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "dossier_schema": DOSSIER_SCHEMA,
        "taxonomy_schema": TAXONOMY_SCHEMA,
        "taxonomy_review_schema": TAXONOMY_REVIEW_SCHEMA,
        "pattern_evaluation_schema": PATTERN_EVALUATION_SCHEMA,
        "pattern_review_schema": PATTERN_REVIEW_SCHEMA,
        "instructions": (
            "Return the complete artifact named by each work packet's response_contract: a "
            "dossier, taxonomy, taxonomy review, pattern evaluation, or pattern review. Ground "
            "it only in supplied source, static facts, and prior semantic records. Reviews must "
            "critique and return the corrected full artifact without requesting human approval. "
            "Score pattern suitability independently from existing conformance and refactoring "
            "opportunity. Treat missing edges as uncertainty, not proof of dead code. Do not "
            "change repository files while mapping."
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


def rehydrate_agent_request(
    bounded_request: dict[str, Any], evidence_pages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Assemble paged MCP evidence into one provider request on the agent host."""

    request = json.loads(json.dumps(bounded_request))
    source_chunks: list[tuple[int, str]] = []
    for page in evidence_pages:
        payload = page.get("payload") if "payload" in page else page
        if not isinstance(payload, dict):
            raise ValueError("Semantic evidence page payload must be an object")
        if isinstance(payload.get("source"), str):
            source_chunks.append((int(payload.get("start_line") or 0), str(payload["source"])))
            continue
        for field, value in payload.items():
            if isinstance(value, dict) and value.get("kind") in {
                "area",
                "subsystem",
                "memberships",
                "facets",
                "evidence",
            }:
                _merge_taxonomy_fragment(request, field, value)
            else:
                _merge_paged_value(request, field, value)
    if source_chunks:
        source = "".join(value for _, value in sorted(source_chunks))
        reference = request.pop("source_reference", {})
        expected = str(reference.get("text_sha256") or "")
        actual = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if expected and not hmac.compare_digest(expected, actual):
            raise ValueError("Semantic source evidence pages did not match their manifest hash")
        request["source"] = source
    return request


def _merge_paged_value(target: dict[str, Any], field: str, value: Any) -> None:
    current = target.get(field)
    if isinstance(value, list):
        if not isinstance(current, list):
            current = []
            target[field] = current
        current.extend(value)
        return
    if isinstance(value, dict):
        if not isinstance(current, dict):
            current = {}
            target[field] = current
        for child_field, child_value in value.items():
            _merge_paged_value(current, child_field, child_value)
        return
    target[field] = value


def _merge_taxonomy_fragment(request: dict[str, Any], field: str, fragment: dict[str, Any]) -> None:
    taxonomy = request.setdefault(
        field,
        {"summary": "", "areas": [], "facets": [], "confidence": 0, "evidence": []},
    )
    kind = fragment["kind"]
    if kind == "area":
        area = dict(fragment.get("area") or {})
        area["subsystems"] = []
        taxonomy["areas"].append(area)
        return
    if kind == "facets":
        taxonomy["facets"].extend(fragment.get("facets") or [])
        return
    if kind == "evidence":
        taxonomy["evidence"].extend(fragment.get("evidence") or [])
        return
    area = _taxonomy_child(taxonomy["areas"], str(fragment.get("area_key") or ""), "area")
    if kind == "subsystem":
        subsystem = dict(fragment.get("subsystem") or {})
        subsystem["members"] = []
        area["subsystems"].append(subsystem)
        return
    subsystem = _taxonomy_child(
        area["subsystems"], str(fragment.get("subsystem_key") or ""), "subsystem"
    )
    subsystem["members"].extend(fragment.get("members") or [])


def _taxonomy_child(items: list[dict[str, Any]], key: str, label: str) -> dict[str, Any]:
    for item in items:
        if str(item.get("key") or item.get("name") or "") == key:
            return item
    raise ValueError(f"Semantic evidence referenced an unknown taxonomy {label}: {key}")


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
        "complete": "The semantic and pattern map is current; no model work is required.",
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
