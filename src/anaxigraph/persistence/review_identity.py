"""Review checkpoints follow candidate content across independently allocated local IDs."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from anaxigraph.semantic_freshness import (
    TAXONOMY_REVIEW_CONTRACT,
    semantic_digest,
    semantic_input_hash,
)


def review_input_hash(connection: Any, prompt: str, evidence: dict[str, Any]) -> str:
    candidate = connection.execute(
        "SELECT value_json FROM semantic_documents WHERE id=?", (evidence["candidate_document_id"],)
    ).fetchone()
    stable = {key: value for key, value in evidence.items() if key != "candidate_document_id"}
    stable["candidate_fingerprint"] = semantic_digest(json.loads(candidate[0]))
    return semantic_input_hash(TAXONOMY_REVIEW_CONTRACT, prompt, stable)


def prepare_review_identity(
    connection: Any, repository_id: int, snapshot_id: int, prompt: str, evidence: Any
) -> str:
    old = semantic_input_hash(TAXONOMY_REVIEW_CONTRACT, prompt, evidence)
    new = review_input_hash(connection, prompt, evidence)
    jobs = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM semantic_jobs WHERE repository_id=? AND snapshot_id=? AND job_kind='taxonomy_review' AND status='completed' AND json_extract(metadata_json,'$.review_group_hash')=?",
            (repository_id, snapshot_id, old),
        )
    ]
    if not jobs:
        return new
    documents = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM semantic_documents WHERE repository_id=? AND snapshot_id=? AND document_kind='taxonomy_review'",
            (repository_id, snapshot_id),
        )
    ]
    changed = _rewrite_batches(connection, jobs, documents, repository_id, old, new)
    for job in jobs:
        if job["id"] in changed:
            connection.execute(
                "UPDATE semantic_jobs SET scope_key=?,input_hash=?,metadata_json=? WHERE id=?",
                (job["scope_key"], job["input_hash"], job["metadata_json"], job["id"]),
            )
    for document in documents:
        if document.pop("_rebound", False):
            connection.execute(
                "UPDATE semantic_documents SET scope_key=?,input_hash=? WHERE id=?",
                (document["scope_key"], document["input_hash"], document["id"]),
            )
    return new


def normalize_review_export(connection: Any, source: Any, prompt: str) -> None:
    for taxonomy in source["semantic_taxonomies"]:
        reviews = [
            row
            for row in source["semantic_taxonomy_reviews"]
            if row["taxonomy_id"] == taxonomy["id"]
        ]
        latest = max(reviews, key=lambda row: row["pass_index"], default=None)
        candidate = latest["document_id"] if latest else taxonomy["candidate_document_id"]
        if candidate is None:
            continue
        evidence = {
            "taxonomy_input_hash": taxonomy["input_hash"],
            "candidate_document_id": candidate,
            "review_pass": latest["pass_index"] + 1 if latest else 1,
            "validation": json.loads(taxonomy["validation_json"]),
        }
        old = semantic_input_hash(TAXONOMY_REVIEW_CONTRACT, prompt, evidence)
        new = review_input_hash(connection, prompt, evidence)
        _rewrite_batches(
            connection,
            source["semantic_jobs"],
            source["semantic_documents"],
            taxonomy["repository_id"],
            old,
            new,
        )
        for document in source["semantic_documents"]:
            document.pop("_rebound", None)
        for state in source["semantic_scope_states"]:
            if state.get("context_input_hash") == old:
                state["context_input_hash"] = new


def _rewrite_batches(
    connection: Any, jobs: Any, documents: Any, repository_id: int, old: str, new: str
) -> set[int]:
    changed = set()
    by_job = {(row["snapshot_id"], row["scope_key"], row["input_hash"]): row for row in documents}
    for job in jobs:
        metadata = json.loads(job["metadata_json"])
        if metadata.get("review_phase") != "batch" or metadata.get("review_group_hash") != old:
            continue
        document = by_job.get((job["snapshot_id"], job["scope_key"], job["input_hash"]))
        if document is None:
            continue
        paths = [
            connection.execute(
                "SELECT scope_key FROM semantic_documents WHERE id=?", (identifier,)
            ).fetchone()[0]
            for identifier in metadata["document_ids"]
        ]
        digest = sha256(
            json.dumps({"review": new, "paths": paths}, sort_keys=True).encode()
        ).hexdigest()
        scope = f"{repository_id}:review:{new}:batch:{metadata['batch_index']}"
        metadata["review_group_hash"] = new
        job.update(
            scope_key=scope, input_hash=digest, metadata_json=json.dumps(metadata, sort_keys=True)
        )
        document.update(scope_key=scope, input_hash=digest, _rebound=True)
        changed.add(job["id"])
    return changed
