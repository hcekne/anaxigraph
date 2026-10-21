"""Rebuild physical cache identities while preserving the imported semantic judgments."""

from __future__ import annotations

from typing import Any

from anaxigraph.pattern_catalog import bundled_pattern_catalog
from anaxigraph.semantic_pattern_identity import pattern_plan_input_hash
from anaxigraph.semantic_pattern_state import baseline_documents


def rebind_pattern_cache(connection: Any, repository_id: int, manifest: Any, semantic: Any) -> None:
    contracts = manifest.get("contracts", {})
    catalog = bundled_pattern_catalog()
    if (
        contracts.get("prompt_version") != semantic.prompt_version
        or contracts.get("pattern_catalog") != catalog.fingerprint
    ):
        return
    rows = connection.execute(
        "SELECT snapshot_id FROM semantic_scope_states WHERE repository_id = ? AND scope_type = 'pattern_plan'",
        (repository_id,),
    ).fetchall()
    for row in rows:
        snapshot_id = row["snapshot_id"]
        digest = pattern_plan_input_hash(
            semantic.prompt_version,
            snapshot_id=snapshot_id,
            catalog_fingerprint=catalog.fingerprint,
            baseline_documents=baseline_documents(connection, snapshot_id),
        )
        connection.execute(
            "UPDATE semantic_scope_states SET context_input_hash = ? WHERE snapshot_id = ? AND scope_type = 'pattern_plan'",
            (digest, snapshot_id),
        )
