"""Semantic graph evidence, fingerprints, prioritization, and source chunking."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from anaxigraph.config import SemanticConfig


class SupersededSemanticJob(RuntimeError):
    pass


def _inventory(
    connection: sqlite3.Connection, snapshot_id: int
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    rows = connection.execute(
        """
        SELECT a.id AS artifact_id, a.artifact_type, fv.id AS artifact_version_id, fv.*
        FROM file_versions fv JOIN artifacts a ON a.id = fv.artifact_id
        WHERE fv.snapshot_id = ? ORDER BY fv.path
        """,
        (snapshot_id,),
    ).fetchall()
    inventory = {str(row["path"]): dict(row) for row in rows}
    for module in inventory.values():
        module["public_interfaces"] = json.loads(module["public_interfaces_json"] or "[]")
        module["symbols"] = [
            dict(row)
            for row in connection.execute(
                """
                SELECT symbol_type, name, signature, start_line, end_line
                FROM symbols WHERE artifact_version_id = ? ORDER BY start_line
                """,
                (module["artifact_version_id"],),
            ).fetchall()
        ]
    relationships: dict[str, list[dict[str, Any]]] = {path: [] for path in inventory}
    rows = connection.execute(
        """
        SELECT r.*, source.canonical_path AS source_path, target.canonical_path AS target_path
        FROM relationships r
        JOIN artifacts source ON source.id = r.source_artifact_id
        LEFT JOIN artifacts target ON target.id = r.target_artifact_id
        WHERE r.snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchall()
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        source = str(row["source_path"])
        target = row["target_path"] or row["target_external"]
        relationships.setdefault(source, []).append(
            {
                "direction": "uses",
                "path": target,
                "type": row["relationship_type"],
                "resolution": metadata.get("resolution_status", "unknown"),
                "candidates": metadata.get("candidate_paths", []),
            }
        )
        if row["target_path"]:
            relationships.setdefault(str(row["target_path"]), []).append(
                {
                    "direction": "used_by",
                    "path": source,
                    "type": row["relationship_type"],
                    "resolution": metadata.get("resolution_status", "resolved_internal"),
                    "candidates": [],
                }
            )
    for values in relationships.values():
        values.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return inventory, relationships


def _interface_hash(module: dict[str, Any]) -> str:
    return _canonical_hash(
        {
            "public_interfaces": module.get("public_interfaces", []),
            "symbols": [
                {
                    "type": item["symbol_type"],
                    "name": item["name"],
                    "signature": item["signature"],
                }
                for item in module.get("symbols", [])
            ],
        }
    )


def _module_priority(module: dict[str, Any], reason: str) -> int:
    reason_weight = {
        "bootstrap_missing": 80,
        "source_or_semantic_policy_changed": 100,
        "manual_full_review": 90,
        "age_expired": 40,
        "context_missing": 60,
        "architectural_context_changed": 75,
    }.get(reason, 50)
    size = min(20, int(module.get("lines_of_code") or 0) // 100)
    complexity = min(20, int(float(module.get("complexity") or 0) // 10))
    return reason_weight + size + complexity


def _relationships_for_artifact(
    connection: sqlite3.Connection, snapshot_id: int, artifact_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT r.*, source.canonical_path AS source_path, target.canonical_path AS target_path
        FROM relationships r
        JOIN artifacts source ON source.id = r.source_artifact_id
        LEFT JOIN artifacts target ON target.id = r.target_artifact_id
        WHERE r.snapshot_id = ? AND (r.source_artifact_id = ? OR r.target_artifact_id = ?)
        ORDER BY source_path, target_path, r.target_external
        """,
        (snapshot_id, artifact_id, artifact_id),
    ).fetchall()
    result = []
    for row in rows:
        outgoing = int(row["source_artifact_id"]) == artifact_id
        metadata = json.loads(row["metadata_json"] or "{}")
        result.append(
            {
                "direction": "uses" if outgoing else "used_by",
                "path": (
                    row["target_path"] or row["target_external"] if outgoing else row["source_path"]
                ),
                "type": row["relationship_type"],
                "confidence": row["confidence"],
                "resolution": metadata.get("resolution_status", "unknown"),
                "evidence": row["evidence"],
            }
        )
    return result


def _source_chunks(
    source: str, symbols: list[dict[str, Any]], max_chars: int
) -> list[tuple[int, int, str]]:
    lines = source.splitlines(keepends=True)
    symbol_ends = sorted(
        {int(item.get("end_line") or 0) for item in symbols if int(item.get("end_line") or 0) > 0}
    )
    result = []
    start = 0
    while start < len(lines):
        size = 0
        end = start
        while end < len(lines) and (size + len(lines[end]) <= max_chars or end == start):
            size += len(lines[end])
            end += 1
        candidate_ends = [line for line in symbol_ends if start + 1 < line <= end]
        if candidate_ends and end < len(lines):
            end = max(candidate_ends)
        result.append((start + 1, end, "".join(lines[start:end])))
        start = end
    return result or [(1, 1, "")]


def _intent_fingerprint(value: dict[str, Any]) -> str:
    def normalized_terms(key: str) -> list[str]:
        terms = {
            " ".join(str(item).split()).casefold()
            for item in (value.get(key) or [])
            if str(item).strip()
        }
        return sorted(terms)

    return _canonical_hash(
        {
            key: normalized_terms(key)
            for key in (
                "responsibilities",
                "inputs",
                "outputs",
                "side_effects",
                "public_contracts",
                "invariants",
                "domain_concepts",
            )
        }
        | {
            "architecture_role": " ".join(
                str(value.get("architecture_role") or "").split()
            ).casefold()
        }
    )


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expired(created_at: str, max_age_days: int) -> bool:
    if max_age_days <= 0:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created < datetime.now(UTC) - timedelta(days=max_age_days)


def _cost(input_tokens: int, output_tokens: int, semantic: SemanticConfig) -> float:
    return round(
        input_tokens * semantic.input_cost_per_million / 1_000_000
        + output_tokens * semantic.output_cost_per_million / 1_000_000,
        8,
    )
