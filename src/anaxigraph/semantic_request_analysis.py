"""Provider execution for one fully assembled semantic request."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from anaxigraph.architecture_charter_contract import compact_architecture_charter
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic import SemanticAnalysisError, SemanticResult
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

    provider = _OutputRecovery(provider, semantic)
    if request["analysis_kind"] == "taxonomy_proposal":
        return analyze_taxonomy_proposal(provider, request, semantic)
    if request["analysis_kind"] == "taxonomy_review":
        return analyze_taxonomy_review(provider, request, semantic)
    if request["analysis_kind"] == "synthesis":
        if request.get("scope_type") == "group":
            request = {**request, "detailed_reviews": False}
        return _analyze_synthesis(provider, request, semantic)
    source = str(request.get("source") or "")
    if request["analysis_kind"] == "annotation" and len(source) > semantic.max_source_chars:
        return _analyze_annotation_chunks(provider, request, semantic, source)
    return provider.analyze(request)


class _OutputRecovery:
    """Retry confirmed output truncation once, preserving the schema and all reported usage."""

    def __init__(self, provider: Any, semantic: SemanticConfig) -> None:
        self.provider, self.semantic = provider, semantic

    def analyze(self, request: dict[str, Any]) -> SemanticResult:
        try:
            return self.provider.analyze(request)
        except SemanticAnalysisError as exc:
            limit = int(request.get("max_output_tokens") or self.semantic.max_output_tokens or 0)
            ceiling = self.semantic.max_output_tokens_on_retry
            if not exc.output_truncated or not limit or ceiling is None or ceiling <= limit:
                raise
            previous = exc
        retry = {
            **request,
            "max_output_tokens": min(limit * 2, ceiling),
            "output_recovery": "The previous response hit its output limit. Return complete JSON; keep each statement concise.",
        }
        try:
            result = self.provider.analyze(retry)
        except SemanticAnalysisError as exc:
            for key, value in _combined_usage(exc, previous).items():
                setattr(exc, key, value)
            raise
        return replace(result, **_combined_usage(result, previous))


def _combined_usage(result: Any, previous: SemanticAnalysisError) -> dict[str, Any]:
    return {
        **{
            key: getattr(result, key) + getattr(previous, key)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        },
        "usage_reported": result.usage_reported and previous.usage_reported,
    }


def _analyze_annotation_chunks(provider, request, semantic, source):
    chunks = _source_chunks(source, request.get("functions", []), semantic.max_source_chars)
    requests = [
        _annotation_chunk(request, chunk, index, len(chunks))
        for index, chunk in enumerate(chunks, 1)
    ]
    outcomes = parallel_map(
        lambda item: _annotation_attempt(provider, item), requests, semantic.max_parallel_jobs
    )
    failures = [item for item in outcomes if isinstance(item, Exception)]
    if failures:
        _annotation_failure_usage(
            failures[0], [item for item in outcomes if item is not failures[0]]
        )
        raise failures[0]
    results = outcomes
    synthesis = {
        **{key: value for key, value in request.items() if key != "source"},
        "annotation_chunks": [result.value for result in results],
        "writing_requirements": "Combine the partial graph annotations into one concise module overview and paragraph. Describe every supplied qualified function exactly once. Preserve all caller obligations, failures, side effects and ordering from the partial contracts; consolidate only equivalent statements. Do not copy each chunk's repeated module description.",
    }
    try:
        result = provider.analyze(synthesis)
    except Exception as error:
        _annotation_failure_usage(error, results)
        raise
    usage = {
        field: getattr(result, field) + sum(getattr(part, field) for part in results)
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    }
    return replace(
        result,
        **usage,
        usage_reported=result.usage_reported and all(part.usage_reported for part in results),
    )


def _annotation_attempt(provider, request):
    try:
        return provider.analyze(request)
    except Exception as error:
        return error


def _annotation_failure_usage(error, outcomes):
    for field in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        setattr(
            error,
            field,
            getattr(error, field, 0) + sum(getattr(item, field, 0) for item in outcomes),
        )
    error.usage_reported = bool(getattr(error, "usage_reported", False)) and all(
        getattr(item, "usage_reported", False) for item in outcomes
    )


def _annotation_chunk(request, chunk, index, total):
    start, end, source = chunk
    functions = [
        item
        for item in request.get("functions", [])
        if item["start_line"] <= end and item["end_line"] >= start
    ]
    return {
        **request,
        "source": source,
        "functions": functions,
        "chunk": {"index": index, "total": total, "start_line": start, "end_line": end},
        "writing_requirements": "Annotate only this source range. Describe each supplied qualified function once, retaining uncertainty about unseen code. Preserve caller obligations and exact source evidence for final combination.",
    }


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
        else compact_dossier(result.value, detailed="detailed_summary" in result.value)
    )
    return {
        "scope": f"semantic-chunk-{index}",
        "kind": "synthesis",
        "confidence": result.confidence,
        "value": value,
    }
