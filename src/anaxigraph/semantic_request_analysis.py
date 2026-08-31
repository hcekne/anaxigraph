"""Provider execution for one fully assembled semantic request."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.architecture_charter_contract import compact_architecture_charter
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import SEMANTIC_SCHEMA_VERSION, SemanticResult
from anaxigraph.semantic_graph import _source_chunks
from anaxigraph.semantic_parallel import parallel_map
from anaxigraph.semantic_request_support import compact_dossier
from anaxigraph.semantic_taxonomy_runner import (
    analyze_taxonomy_proposal,
    analyze_taxonomy_review,
)


def analyze_semantic_request(
    provider: Any,
    request: dict[str, Any],
    semantic: SemanticConfig,
) -> SemanticResult:
    """Execute a request with bounded chunking independent of index location."""

    if request["analysis_kind"] == "taxonomy_proposal":
        return analyze_taxonomy_proposal(provider, request, semantic)
    if request["analysis_kind"] == "taxonomy_review":
        return analyze_taxonomy_review(provider, request, semantic)
    if request["analysis_kind"] == "synthesis":
        return _analyze_synthesis(provider, request, semantic)
    source = str(request.get("source") or "")
    if request["analysis_kind"] != "intrinsic" or len(source) <= semantic.max_source_chars:
        return provider.analyze(request)
    return _analyze_intrinsic_chunks(provider, request, semantic, source)


def _analyze_intrinsic_chunks(
    provider: Any,
    request: dict[str, Any],
    semantic: SemanticConfig,
    source: str,
) -> SemanticResult:
    symbols = request.get("deterministic_facts", {}).get("symbols") or []
    chunks = _source_chunks(source, symbols, semantic.max_source_chars)
    requests = []
    for index, (start, end, content) in enumerate(chunks, start=1):
        partial = dict(request)
        partial["analysis_kind"] = "intrinsic_chunk"
        partial["chunk"] = {
            "index": index,
            "total": len(chunks),
            "start_line": start,
            "end_line": end,
        }
        partial["source"] = content
        requests.append(partial)
    results = parallel_map(provider.analyze, requests, semantic.max_parallel_jobs)
    partials = [result.value for result in results]
    input_tokens = sum(result.input_tokens for result in results)
    output_tokens = sum(result.output_tokens for result in results)
    synthesis = {
        "contract": request["contract"],
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "analysis_kind": "intrinsic_synthesis",
        "path": request.get("path"),
        "language": request.get("language"),
        "deterministic_facts": request.get("deterministic_facts"),
        "chunk_dossiers": partials,
    }
    result = provider.analyze(synthesis)
    return SemanticResult(
        value=result.value,
        confidence=result.confidence,
        evidence=result.evidence,
        input_tokens=input_tokens + result.input_tokens,
        output_tokens=output_tokens + result.output_tokens,
    )


def _analyze_synthesis(
    provider: Any,
    request: dict[str, Any],
    semantic: SemanticConfig,
) -> SemanticResult:
    children = list(request.get("child_dossiers") or [])
    if len(json.dumps(request, default=str)) <= semantic.max_source_chars or len(children) < 2:
        return provider.analyze(request)

    base = {key: value for key, value in request.items() if key != "child_dossiers"}
    batches = _payload_batches(children, semantic.max_source_chars, base)
    partials, input_tokens, output_tokens = _run_synthesis_chunks(
        provider, base, batches, semantic.max_parallel_jobs
    )
    reduction_width = max(2, min(20, semantic.max_context_modules))
    partials, reduction_input, reduction_output = _reduce_synthesis_partials(
        provider, base, partials, reduction_width, semantic.max_parallel_jobs
    )

    final_request = {**base, "analysis_kind": "synthesis", "child_dossiers": partials}
    result = provider.analyze(final_request)
    return SemanticResult(
        value=result.value,
        confidence=result.confidence,
        evidence=result.evidence,
        input_tokens=input_tokens + reduction_input + result.input_tokens,
        output_tokens=output_tokens + reduction_output + result.output_tokens,
    )


def _payload_batches(
    children: list[dict[str, Any]], max_chars: int, base: dict[str, Any]
) -> list[list[dict[str, Any]]]:
    overhead = len(json.dumps(base, default=str)) + 500
    budget = max(1_000, max_chars - overhead)
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for child in children:
        child_size = len(json.dumps(child, default=str)) + 1
        if current and size + child_size > budget:
            batches.append(current)
            current = []
            size = 0
        current.append(child)
        size += child_size
    if current:
        batches.append(current)
    return batches


def _run_synthesis_chunks(
    provider: Any,
    base: dict[str, Any],
    batches: list[list[dict[str, Any]]],
    parallel_jobs: int,
) -> tuple[list[dict[str, Any]], int, int]:
    requests = []
    for index, batch in enumerate(batches, start=1):
        requests.append(
            {
                **base,
                "analysis_kind": "synthesis_chunk",
                "chunk": {"index": index, "total": len(batches)},
                "child_dossiers": batch,
            }
        )
    results = parallel_map(provider.analyze, requests, parallel_jobs)
    partials = [_partial_dossier(index, result) for index, result in enumerate(results, start=1)]
    input_tokens = sum(result.input_tokens for result in results)
    output_tokens = sum(result.output_tokens for result in results)
    return partials, input_tokens, output_tokens


def _reduce_synthesis_partials(
    provider: Any,
    base: dict[str, Any],
    partials: list[dict[str, Any]],
    width: int,
    parallel_jobs: int,
) -> tuple[list[dict[str, Any]], int, int]:
    input_tokens = output_tokens = 0
    level = 1
    while len(partials) > width:
        groups = [partials[index : index + width] for index in range(0, len(partials), width)]
        requests = []
        for index, batch in enumerate(groups, start=1):
            requests.append(
                {
                    **base,
                    "analysis_kind": "synthesis_reduction",
                    "reduction": {"level": level, "index": index, "total": len(groups)},
                    "child_dossiers": batch,
                }
            )
        results = parallel_map(provider.analyze, requests, parallel_jobs)
        reduced = [_partial_dossier(index, result) for index, result in enumerate(results, start=1)]
        input_tokens += sum(result.input_tokens for result in results)
        output_tokens += sum(result.output_tokens for result in results)
        partials = reduced
        level += 1
    return partials, input_tokens, output_tokens


def _partial_dossier(index: int, result: SemanticResult) -> dict[str, Any]:
    value = (
        compact_architecture_charter(result.value)
        if result.value.get("contract_version") == "architecture-charter-v1"
        else compact_dossier(result.value)
    )
    return {
        "scope": f"semantic-chunk-{index}",
        "kind": "synthesis",
        "confidence": result.confidence,
        "value": value,
    }
