"""Carry compatible semantic claims onto a newly materialized snapshot."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.persistence.temporal_reconstruction import reconstruct_files


def carry_semantic_claims(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    prepared: list[Any],
    version_ids: dict[str, int],
    artifacts: dict[str, int],
) -> None:
    """Reuse claims only when the module's analyzed meaning is unchanged."""

    fact_ids = {
        artifact_id: int(value["file_fact_id"])
        for artifact_id, value in reconstruct_files(connection, snapshot_id).items()
    }
    for item in prepared:
        if item.previous_version_id is None or item.analysis_status not in {
            "raw_unchanged",
            "metadata_only",
        }:
            continue
        path = item.discovered.path
        connection.execute(
            """
            INSERT INTO semantic_claims(
                artifact_version_id, file_fact_id, claim_type, value_json, source, provider,
                model, prompt_version, created_at, confidence, supporting_evidence_json
            )
            SELECT ?, ?, claim_type, value_json, source, provider, model, prompt_version,
                   created_at, confidence, supporting_evidence_json
            FROM semantic_claims WHERE artifact_version_id = ?
            """,
            (version_ids[path], fact_ids[artifacts[path]], item.previous_version_id),
        )
