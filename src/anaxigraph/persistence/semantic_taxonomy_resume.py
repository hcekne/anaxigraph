"""Reuse a saved proposal for a local change without inventing fresh reviews."""

from __future__ import annotations

import json
import math
from typing import Any

from anaxigraph.persistence.semantic_taxonomy_carry import (
    TaxonomyCarry,
    TaxonomyStability,
    _compatible_policy,
    _copy_taxonomy,
    _intrinsic_intents,
)


def resume_taxonomy_proposal(
    connection: Any,
    *,
    repository_id: int,
    snapshot_id: int,
    input_hash: str,
    prompt_version: str,
    stability: TaxonomyStability,
) -> TaxonomyCarry | None:
    rows = connection.execute(
        """SELECT t.*, ss.interface_hash AS stability_hash FROM semantic_taxonomy_values t
           LEFT JOIN semantic_scope_states ss ON ss.snapshot_id = t.snapshot_id
             AND ss.scope_type = 'taxonomy' AND ss.scope_key = CAST(t.repository_id AS TEXT)
           WHERE t.repository_id = ? AND t.snapshot_id < ? AND t.prompt_version = ?
             AND t.status IN ('current', 'proposed', 'reviewing')
           ORDER BY t.snapshot_id DESC, t.id DESC""",
        (repository_id, snapshot_id, prompt_version),
    ).fetchall()
    current = _intrinsic_intents(connection, snapshot_id)
    for row in rows:
        previous = _intrinsic_intents(connection, int(row["snapshot_id"]))
        if not _compatible_policy(row, stability, previous):
            continue
        unchanged = sum(
            bool(intent) and current.get(path) == intent for path, intent in previous.items()
        )
        total = max(len(previous), len(current))
        exact = row["input_hash"] == input_hash
        if not exact and (not total or unchanged < math.ceil(total * stability.bias)):
            continue
        source = dict(row)
        if not exact:
            source = _updated_candidate(connection, source, previous, current)
        copied = _copy_taxonomy(
            connection,
            previous=source,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            input_hash=input_hash,
            source="reused_taxonomy_proposal",
            status=source["status"],
            copy_reviews=exact,
        )
        return TaxonomyCarry(copied, "proposal", unchanged, total)
    return None


def _updated_candidate(
    connection: Any, source: dict[str, Any], previous: Any, current: Any
) -> dict[str, Any]:
    latest = connection.execute(
        "SELECT document_id FROM semantic_taxonomy_review_values WHERE taxonomy_id = ? ORDER BY pass_index DESC LIMIT 1",
        (source["id"],),
    ).fetchone()
    changes = {
        "kind": "source_update",
        "previous_snapshot_id": source["snapshot_id"],
        "added": sorted(current.keys() - previous.keys()),
        "removed": sorted(previous.keys() - current.keys()),
        "changed_roles": sorted(
            path for path in current.keys() & previous.keys() if current[path] != previous[path]
        ),
        "review": "Reuse the saved map. Check the changed evidence and its boundaries; preserve unaffected groups. Earlier reviews remain historical evidence, not approval of these changes.",
    }
    return {
        **source,
        "status": "proposed",
        "review_passes": 0,
        "final_document_id": None,
        "candidate_document_id": latest["document_id"]
        if latest
        else source["candidate_document_id"],
        "change_json": json.dumps([changes], sort_keys=True),
    }
