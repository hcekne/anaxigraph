"""Incremental annotation planning on the existing durable job queue."""

from __future__ import annotations

import json

from anaxigraph.knowledge_annotation import attach_annotation
from anaxigraph.knowledge_annotation_contract import ANNOTATION_VERSION
from anaxigraph.knowledge_legacy import attach_legacy, bound_legacy, compatible_legacy
from anaxigraph.knowledge_sync import sync_knowledge
from anaxigraph.semantic_freshness import is_expired, semantic_digest
from anaxigraph.semantic_records import (
    _active_job,
    _ensure_job,
    _latest_document,
    _matching_document,
    _supersede_duplicate_jobs,
    _upsert_state,
)


def plan_annotations(
    connection,
    *,
    repository_id,
    snapshot_id,
    inventory,
    relationships,
    semantic,
    force=False,
    retry_failed=False,
):
    sync_knowledge(connection, snapshot_id)
    count = 0
    for path, module in inventory.items():
        arguments = {
            "repository_id": repository_id,
            "snapshot_id": snapshot_id,
            "scope_type": "module",
            "scope_key": path,
            "artifact_id": module["artifact_id"],
            "file_fact_id": module["file_fact_id"],
            "artifact_version_id": None,
        }
        count += _plan_module(
            connection,
            arguments,
            module,
            relationships.get(path, []),
            semantic,
            force,
            retry_failed,
        )
    return count


def _plan_module(connection, arguments, module, relationships, semantic, force, retry_failed):
    path = arguments["scope_key"]
    if not semantic.includes_path(path):
        _upsert_state(connection, **arguments, status="excluded", reason="Excluded by policy")
        return 0
    evidence = {
        "contract": ANNOTATION_VERSION,
        "prompt_version": semantic.prompt_version,
        "raw_hash": module["raw_hash"],
        "interfaces": module["public_interfaces"],
        "relationships": relationships,
        "analysis_contract": module.get("analysis_contract"),
    }
    fingerprint = semantic_digest(evidence)
    saved = _matching_document(
        connection, arguments["repository_id"], "module", path, "annotation", fingerprint, semantic
    )
    reserved = _reserved_job(connection, arguments, fingerprint)
    expired = bool(saved and is_expired(saved["created_at"], semantic.max_age_days))
    if saved and not force and not reserved and not expired:
        _reuse(connection, arguments, fingerprint, saved)
        return 0
    bound = (
        bound_legacy(connection, arguments, module, semantic)
        if not force and not reserved
        else None
    )
    if bound:
        _supersede_duplicate_jobs(
            connection, arguments["snapshot_id"], "module", path, "annotation"
        )
        attach_legacy(connection, arguments["snapshot_id"], path, bound)
        return 0
    legacy = (
        compatible_legacy(connection, arguments, module, semantic)
        if not force and not reserved
        else None
    )
    if legacy:
        _reuse_legacy(connection, arguments, fingerprint, legacy)
        return 0
    return _enqueue(
        connection, arguments, module, fingerprint, semantic, force, retry_failed, expired
    )


def _enqueue(connection, arguments, module, fingerprint, semantic, force, retry_failed, expired):
    previous = _latest_document(
        connection, arguments["repository_id"], "module", arguments["scope_key"], "annotation"
    )
    status, created, error = _ensure_job(
        connection,
        **arguments,
        job_kind="annotation",
        reason=(
            "manual_full_review"
            if force
            else "analysis_expired"
            if expired
            else "graph_semantics_missing"
        ),
        priority=100,
        input_hash=fingerprint,
        semantic=semantic,
        estimated_input_tokens=max(250, int(module["lines_of_code"]) * 8),
        metadata={
            "path": arguments["scope_key"],
            "source_fingerprint": module["raw_hash"],
            "previous_document_id": int(previous["id"]) if previous else None,
        },
        retry_failed=retry_failed,
        force_new=force or expired,
    )
    _upsert_state(
        connection,
        **arguments,
        status=status,
        reason=error or "Concise module, function and contract annotation pending",
        intrinsic_input_hash=fingerprint,
        context_input_hash=fingerprint,
    )
    return int(created)


def _reuse_legacy(connection, arguments, fingerprint, saved):
    _supersede_duplicate_jobs(
        connection, arguments["snapshot_id"], "module", arguments["scope_key"], "annotation"
    )
    attach_legacy(connection, arguments["snapshot_id"], arguments["scope_key"], saved)
    _upsert_state(
        connection,
        **arguments,
        status="current",
        reason="Saved module understanding reused; function descriptions remain extracted until enrichment",
        intrinsic_input_hash=saved["input_hash"],
        context_input_hash=saved["input_hash"],
        intrinsic_document_id=saved["id"],
        context_document_id=saved["id"],
    )


def _reuse(connection, arguments, fingerprint, saved):
    _supersede_duplicate_jobs(
        connection, arguments["snapshot_id"], "module", arguments["scope_key"], "annotation"
    )
    attach_annotation(connection, arguments, saved["id"], json.loads(saved["value_json"]))
    _upsert_state(
        connection,
        **arguments,
        status="current",
        reason="Saved graph annotation reused",
        intrinsic_input_hash=fingerprint,
        context_input_hash=fingerprint,
        intrinsic_document_id=saved["id"],
        context_document_id=saved["id"],
    )


def _reserved_job(connection, arguments, fingerprint):
    active = _active_job(
        connection,
        repository_id=arguments["repository_id"],
        snapshot_id=arguments["snapshot_id"],
        scope_type="module",
        scope_key=arguments["scope_key"],
        job_kind="annotation",
        input_hash=fingerprint,
    )
    return bool(
        active and (active["status"] == "running" or active["reason"] == "manual_full_review")
    )
