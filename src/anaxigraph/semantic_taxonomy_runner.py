"""Scale hosted taxonomy proposal and review across whole repositories."""

from __future__ import annotations

from typing import Any

from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_contract import SemanticResult
from anaxigraph.semantic_taxonomy_clusters import (
    cluster_inventory,
    expand_taxonomy,
    group_summaries,
    membership_count,
    representative_locks,
    representative_previous,
    representative_relationships,
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
    chunks: list[dict[str, Any]] = []
    input_tokens = output_tokens = 0
    relationships = list(request.get("relationships") or [])
    provisional: list[dict[str, Any]] = []
    for index, batch in enumerate(batches, start=1):
        paths = {str(item.get("path") or "") for item in batch}
        chunk_request = {
            **base,
            "analysis_kind": "taxonomy_inventory_chunk",
            "chunk": {"index": index, "total": len(batches)},
            "constraints": chunk_constraints(request.get("constraints") or {}, len(batches)),
            "modules": batch,
            "relationships": bounded_relationships(relationships, paths, semantic.max_source_chars),
            "previous_taxonomy": filter_previous(request.get("previous_taxonomy"), paths),
            "provisional_groups": provisional,
            "contract": (
                f"{request['contract']} This is partition {index} of {len(batches)}. "
                "Classify every supplied module, and reuse provisional group keys whenever "
                "the responsibility is materially the same."
            ),
        }
        result = provider.analyze(chunk_request)
        chunks.append({"taxonomy": result.value, "modules": batch})
        provisional = group_summaries(chunks)[-partition_limit(semantic) :]
        input_tokens += result.input_tokens
        output_tokens += result.output_tokens
    clustered = cluster_inventory(
        chunks,
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
    expanded = expand_taxonomy(result.value, clustered["expansion"])
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
    chunks: list[dict[str, Any]] = []
    partition_reviews: list[dict[str, Any]] = []
    input_tokens = output_tokens = 0
    verdicts: list[str] = []
    for index, batch in enumerate(batches, start=1):
        paths = {str(item.get("path") or "") for item in batch}
        chunk_request = {
            **base,
            "analysis_kind": "taxonomy_review_chunk",
            "chunk": {"index": index, "total": len(batches)},
            "constraints": chunk_constraints(request.get("constraints") or {}, len(batches)),
            "candidate_taxonomy": filter_taxonomy(candidate, paths),
            "modules": batch,
            "relationships": bounded_relationships(relationships, paths, semantic.max_source_chars),
            "previous_taxonomy": filter_previous(request.get("previous_taxonomy"), paths),
            "contract": (
                f"{request['contract']} This is review partition {index} of {len(batches)}. "
                "Return the complete corrected taxonomy for every supplied module; global "
                "boundary reconciliation follows automatically."
            ),
        }
        result = provider.analyze(chunk_request)
        chunks.append({"taxonomy": result.value["taxonomy"], "modules": batch})
        verdicts.append(str(result.value["verdict"]))
        partition_reviews.append(
            {
                "partition": index,
                "verdict": result.value["verdict"],
                "summary": result.value["summary"],
                "issues": list(result.value["issues"])[:20],
            }
        )
        input_tokens += result.input_tokens
        output_tokens += result.output_tokens
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
        "taxonomy": expand_taxonomy(result.value["taxonomy"], clustered["expansion"]),
        "evidence": evidence,
    }
    return SemanticResult(
        value=value,
        confidence=result.confidence,
        evidence=tuple(evidence),
        input_tokens=input_tokens + result.input_tokens,
        output_tokens=output_tokens + result.output_tokens,
    )
