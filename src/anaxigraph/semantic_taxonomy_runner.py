"""Scale hosted taxonomy proposal and review across whole repositories."""

from __future__ import annotations

from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_contract import SemanticResult
from anaxigraph.semantic_parallel import parallel_map
from anaxigraph.semantic_taxonomy_clusters import (
    cluster_inventory,
    representative_locks,
    representative_previous,
    representative_relationships,
)
from anaxigraph.semantic_taxonomy_expansion import (
    complete_representative_taxonomy,
    expand_taxonomy,
    membership_count,
    unique_strings,
)
from anaxigraph.semantic_taxonomy_partition import (
    bounded_relationships,
    chunk_constraints,
    cluster_limit,
    filter_previous,
    filter_taxonomy,
    module_batches,
    needs_partition,
    partition_limit,
    request_base,
)


def _proposal_requests(
    request: dict[str, Any],
    semantic: SemanticConfig,
    base: dict[str, Any],
    batches: list[list[dict[str, Any]]],
    relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests = []
    for index, batch in enumerate(batches, start=1):
        paths = {str(item.get("path") or "") for item in batch}
        requests.append(
            {
                **base,
                "analysis_kind": "taxonomy_inventory_chunk",
                "chunk": {"index": index, "total": len(batches)},
                "constraints": chunk_constraints(request.get("constraints") or {}, len(batches)),
                "modules": batch,
                "relationships": bounded_relationships(
                    relationships, paths, semantic.max_source_chars
                ),
                "previous_taxonomy": filter_previous(request.get("previous_taxonomy"), paths),
                "provisional_groups": [],
                "contract": (
                    f"{request['contract']} This is partition {index} of {len(batches)}. "
                    "Classify every supplied module. Independent partition results are reconciled "
                    "into stable global groups automatically."
                ),
            }
        )
    return requests


def _review_requests(
    request: dict[str, Any],
    semantic: SemanticConfig,
    base: dict[str, Any],
    batches: list[list[dict[str, Any]]],
    relationships: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    requests = []
    for index, batch in enumerate(batches, start=1):
        paths = {str(item.get("path") or "") for item in batch}
        requests.append(
            {
                **base,
                "analysis_kind": "taxonomy_review_chunk",
                "chunk": {"index": index, "total": len(batches)},
                "constraints": chunk_constraints(request.get("constraints") or {}, len(batches)),
                "candidate_taxonomy": filter_taxonomy(candidate, paths),
                "modules": batch,
                "relationships": bounded_relationships(
                    relationships, paths, semantic.max_source_chars
                ),
                "previous_taxonomy": filter_previous(request.get("previous_taxonomy"), paths),
                "contract": (
                    f"{request['contract']} This is review partition {index} of {len(batches)}. "
                    "Return the complete corrected taxonomy for every supplied module; global "
                    "boundary reconciliation follows automatically."
                ),
            }
        )
    return requests


def _token_usage(results: list[SemanticResult]) -> tuple[int, int]:
    return (
        sum(result.input_tokens for result in results),
        sum(result.output_tokens for result in results),
    )


def _inventory_chunks(
    batches: list[list[dict[str, Any]]],
    results: list[SemanticResult],
) -> list[dict[str, Any]]:
    return [
        {"taxonomy": result.value, "modules": batch}
        for batch, result in zip(batches, results, strict=True)
    ]


def _partition_reviews(
    batches: list[list[dict[str, Any]]],
    results: list[SemanticResult],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    chunks = []
    verdicts = []
    reviews = []
    for index, (batch, result) in enumerate(zip(batches, results, strict=True), start=1):
        chunks.append({"taxonomy": result.value["taxonomy"], "modules": batch})
        verdicts.append(str(result.value["verdict"]))
        reviews.append(
            {
                "partition": index,
                "verdict": result.value["verdict"],
                "summary": result.value["summary"],
                "issues": list(result.value["issues"])[:20],
            }
        )
    return chunks, verdicts, reviews


def _expanded_taxonomy(value: dict[str, Any], clustered: dict[str, Any]) -> dict[str, Any]:
    complete = complete_representative_taxonomy(value, clustered["taxonomy"])
    return expand_taxonomy(complete, clustered["expansion"])


def analyze_taxonomy_proposal(
    provider: Any,
    request: dict[str, Any],
    semantic: SemanticConfig,
) -> SemanticResult:
    modules = list(request.get("modules") or [])
    if not needs_partition(request, semantic, len(modules)):
        return provider.analyze(request)
    base = request_base(request)
    batches = module_batches(
        modules,
        semantic.max_source_chars,
        base,
        partition_limit(semantic),
    )
    relationships = list(request.get("relationships") or [])
    chunk_requests = _proposal_requests(request, semantic, base, batches, relationships)
    results = parallel_map(provider.analyze, chunk_requests, semantic.max_parallel_jobs)
    input_tokens, output_tokens = _token_usage(results)
    clustered = cluster_inventory(
        _inventory_chunks(batches, results),
        modules,
        maximum=cluster_limit(request, semantic),
    )
    final_request = {
        **base,
        "analysis_kind": "taxonomy_proposal",
        "modules": clustered["modules"],
        "relationships": representative_relationships(
            relationships,
            clustered["path_to_representative"],
            semantic.max_source_chars,
        ),
        "partial_taxonomies": clustered["summaries"],
        "previous_taxonomy": representative_previous(
            request.get("previous_taxonomy"), clustered["path_to_representative"]
        ),
        "locked_memberships": representative_locks(
            request.get("locked_memberships") or {},
            clustered["path_to_representative"],
        ),
        "contract": (
            f"{request['contract']} Each supplied module now represents a reviewed cluster from "
            "one inventory partition. Reconcile the clusters into one global map and assign every "
            "representative exactly once; AnaxiGraph will expand those memberships back to the "
            "original modules before deterministic validation."
        ),
    }
    result = provider.analyze(final_request)
    expanded = _expanded_taxonomy(result.value, clustered)
    return SemanticResult(
        value=expanded,
        confidence=result.confidence,
        evidence=tuple(expanded["evidence"]),
        input_tokens=input_tokens + result.input_tokens,
        output_tokens=output_tokens + result.output_tokens,
    )


def analyze_taxonomy_review(
    provider: Any,
    request: dict[str, Any],
    semantic: SemanticConfig,
) -> SemanticResult:
    modules = list(request.get("modules") or [])
    candidate = dict(request.get("candidate_taxonomy") or {})
    candidate_memberships = max(len(modules), membership_count(candidate))
    if not needs_partition(request, semantic, candidate_memberships):
        return provider.analyze(request)
    base = request_base(request)
    batches = module_batches(
        modules,
        semantic.max_source_chars,
        base,
        partition_limit(semantic),
    )
    relationships = list(request.get("relationships") or [])
    chunk_requests = _review_requests(request, semantic, base, batches, relationships, candidate)
    results = parallel_map(provider.analyze, chunk_requests, semantic.max_parallel_jobs)
    chunks, verdicts, partition_reviews = _partition_reviews(batches, results)
    input_tokens, output_tokens = _token_usage(results)
    clustered = cluster_inventory(
        chunks,
        modules,
        maximum=cluster_limit(request, semantic),
    )
    final_request = {
        **base,
        "analysis_kind": "taxonomy_review",
        "candidate_taxonomy": clustered["taxonomy"],
        "modules": clustered["modules"],
        "relationships": representative_relationships(
            relationships,
            clustered["path_to_representative"],
            semantic.max_source_chars,
        ),
        "partition_reviews": partition_reviews,
        "previous_taxonomy": representative_previous(
            request.get("previous_taxonomy"), clustered["path_to_representative"]
        ),
        "locked_memberships": representative_locks(
            request.get("locked_memberships") or {},
            clustered["path_to_representative"],
        ),
        "contract": (
            f"{request['contract']} Partition critics have already corrected local membership. "
            "Review their representative clusters as one global candidate, correct global "
            "boundaries, and assign every representative exactly once. AnaxiGraph expands the "
            "result to every original module before deterministic validation."
        ),
    }
    result = provider.analyze(final_request)
    issues = [issue for review in partition_reviews for issue in review["issues"]] + list(
        result.value["issues"]
    )
    evidence = unique_strings(
        [
            *(review["summary"] for review in partition_reviews),
            *result.value["evidence"],
        ],
        limit=100,
    )
    value = {
        **result.value,
        "verdict": (
            "revise" if result.value["verdict"] == "revise" or "revise" in verdicts else "approve"
        ),
        "issues": issues[:500],
        "taxonomy": _expanded_taxonomy(result.value["taxonomy"], clustered),
        "evidence": evidence,
    }
    return SemanticResult(
        value=value,
        confidence=result.confidence,
        evidence=tuple(evidence),
        input_tokens=input_tokens + result.input_tokens,
        output_tokens=output_tokens + result.output_tokens,
    )
