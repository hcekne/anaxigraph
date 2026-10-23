"""Index saved review stages and immutable generations without rebuilding v1 judgments."""

from __future__ import annotations

import json

from anaxigraph.semantic_fresh_eyes_contract import FRESH_EYES_SCOPE, fresh_eyes_plan_options
from anaxigraph.semantic_fresh_eyes_diversity import proposal_diversity
from anaxigraph.semantic_fresh_eyes_records import document_record as document_record
from anaxigraph.semantic_fresh_eyes_records import document_value as document_value
from anaxigraph.semantic_fresh_eyes_records import provenance as provenance
from anaxigraph.semantic_fresh_eyes_telemetry import stage_telemetry, telemetry_totals

FRESH_EYES_STAGES = (
    ("proposal:a", "Independent proposal A"),
    ("proposal:b", "Independent proposal B"),
    ("proposal:c", "Independent proposal C"),
    ("adjudication", "Blind adjudication"),
    ("comparison", "As-built comparison"),
    ("review", "Mission filter and ranked strategy"),
)
_LABELS = dict(FRESH_EYES_STAGES)


def list_generations(connection, repository_id, snapshot_id=None):
    plans, documents, jobs = _indexes(connection, repository_id)
    identities = {(row["scope_key"], row["input_hash"]): row["id"] for row in documents.values()}
    entries, by_hash = {}, {}
    for row in jobs:
        generation = _generation(row, plans)
        by_hash[(row["scope_key"], row["input_hash"])] = generation
        _add(
            entries,
            row,
            generation,
            identities.get((row["scope_key"], row["input_hash"])),
            row["status"],
            row["id"],
        )
    for row in connection.execute(
        "SELECT * FROM semantic_scope_states WHERE repository_id=? AND scope_type=? AND scope_key!='plan'",
        (repository_id, FRESH_EYES_SCOPE),
    ):
        source = {**dict(row), "input_hash": row["context_input_hash"]}
        generation = by_hash.get(
            (row["scope_key"], row["context_input_hash"]), _generation(source, plans)
        )
        _add(entries, source, generation, row["context_document_id"], "reused")
    for document in documents.values():
        generation = by_hash.get(
            (document["scope_key"], document["input_hash"]), _generation(document, plans)
        )
        _add(entries, document, generation, document["id"], "recorded")
    grouped = {}
    for (generation, snapshot, _key), entry in entries.items():
        grouped.setdefault((generation, snapshot), []).append(entry)
    active = (
        (fresh_eyes_plan_options(plans[snapshot_id])[1], snapshot_id)
        if snapshot_id in plans
        else None
    )
    recorded = _recorded_generations(documents, plans, by_hash)
    return [
        _bundle(
            connection, repository_id, key, entries, documents, key == active, recorded.get(key, {})
        )
        for key, entries in sorted(grouped.items())
    ]


def _generation(row, plans):
    row = dict(row)
    manifest = json.loads(row.get("metadata_json") or "{}").get("input_manifest") or {}
    explicit = manifest.get("review_generation")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit >= 1:
        return explicit
    plan = plans.get(row["snapshot_id"]) or {}
    if str(plan.get("interface_hash") or "").startswith("functional-v2|") and not row[
        "scope_key"
    ].startswith("functional:"):
        return 1
    return fresh_eyes_plan_options(plan)[1] if plan else 1


def _add(entries, row, generation, document_id, status, job_id=None):
    key = row["scope_key"]
    if key not in _LABELS and not key.startswith("functional:"):
        return
    identity = (generation, row["snapshot_id"], key)
    existing = entries.get(identity)
    if existing and (existing["document_id"] or not document_id):
        return
    entries[identity] = {
        "key": key,
        "label": _label(key),
        "input_hash": row["input_hash"],
        "document_id": document_id,
        "job_id": job_id,
        "job_status": status,
    }


def _label(key):
    if key in _LABELS:
        return _LABELS[key]
    return {
        "functional:brief": "Prepare functional hierarchy",
        "functional:review": "Review functional alternatives",
    }.get(
        key,
        "Compare retained alternatives"
        if key.endswith(":comparison")
        else "Functional alternative",
    )


def _bundle(connection, repository_id, key, entries, documents, active, recorded):
    entries.sort(key=lambda item: (item["key"] == "functional:review", item["key"]))
    identifiers = dict.fromkeys(
        [item["document_id"] for item in entries] + recorded.get("document_ids", [])
    )
    saved = [documents[identifier] for identifier in identifiers if identifier in documents]
    review = next(
        (
            documents[item["document_id"]]
            for item in entries
            if item["key"] in {"review", "functional:review"} and item["document_id"] in documents
        ),
        None,
    )
    telemetry = list(
        stage_telemetry(
            connection,
            repository_id,
            [(item["key"], item["input_hash"], item["document_id"]) for item in entries],
        ).values()
    )
    return {
        "generation": key[0],
        "snapshot_id": key[1],
        "state": _bundle_state(entries, active, review),
        "ready": bool(active and review),
        "stages": entries,
        "generation_inferred": recorded.get("generation_inferred", False),
        **_bundle_facts(saved, review),
        "telemetry": {"stages": telemetry, **telemetry_totals(telemetry)},
    }


def select_generation(generations, generation):
    matches = [item for item in generations if item["generation"] == int(generation)]
    if not matches:
        available = ", ".join(str(item["generation"]) for item in generations) or "none"
        raise ValueError(
            f"Fresh-eyes generation {generation} was never recorded for this repository; available generations: {available}"
        )
    return matches[-1]


def input_manifests(connection, repository_id, stages):
    result = []
    for key, fingerprint in stages:
        row = connection.execute(
            "SELECT scope_key,job_kind,status,input_hash,metadata_json FROM semantic_jobs WHERE repository_id=? AND scope_type=? AND scope_key=? AND input_hash=? ORDER BY id DESC LIMIT 1",
            (repository_id, FRESH_EYES_SCOPE, key, fingerprint),
        ).fetchone()
        metadata = json.loads(row["metadata_json"] or "{}") if row else {}
        if metadata.get("input_manifest"):
            result.append(
                {
                    "scope": key,
                    "job_kind": row["job_kind"],
                    "status": row["status"],
                    "input_hash": fingerprint,
                    "manifest": metadata["input_manifest"],
                    "information_boundary": metadata.get("information_boundary"),
                }
            )
    return result


def generation_payload(
    connection, repository_id, bundle, generations, semantic_status, *, scope_id="", details=True
):
    if any(item["key"].startswith("functional:") for item in bundle["stages"]):
        from anaxigraph.semantic_fresh_eyes_functional_read import functional_generation

        return functional_generation(
            connection, repository_id, bundle, generations, scope_id=scope_id, details=details
        )
    from anaxigraph.semantic_fresh_eyes_payload import archive_payload

    documents = [
        record
        for identifier in bundle.get(
            "document_ids", [entry["document_id"] for entry in bundle["stages"]]
        )
        if (record := document_record(connection, identifier))
    ]
    manifests = input_manifests(
        connection,
        repository_id,
        [(entry["key"], entry["input_hash"]) for entry in bundle["stages"]],
    )
    return archive_payload(
        repository_id, bundle, generations, documents, manifests, details=details
    )


def _indexes(connection, repository_id):
    plans = {
        row["snapshot_id"]: dict(row)
        for row in connection.execute(
            "SELECT snapshot_id,interface_hash,status FROM semantic_scope_states WHERE repository_id=? AND scope_type=? AND scope_key='plan'",
            (repository_id, FRESH_EYES_SCOPE),
        )
    }
    documents = {
        row["id"]: dict(row)
        for row in connection.execute(
            "SELECT id,snapshot_id,scope_key,input_hash,provider,model,executor_id,executor_model,created_at,confidence,"
            "json_array_length(value_json,'$.recommendations') AS recommendation_count,"
            "json_array_length(value_json,'$.rejected_ideas') AS rejected_idea_count FROM semantic_document_values "
            "WHERE repository_id=? AND scope_type=? AND document_kind!='fresh_grounding'",
            (repository_id, FRESH_EYES_SCOPE),
        )
    }
    jobs = list(
        connection.execute(
            "SELECT * FROM semantic_jobs WHERE repository_id=? AND scope_type=? ORDER BY id",
            (repository_id, FRESH_EYES_SCOPE),
        )
    )
    return plans, documents, jobs


def _bundle_state(entries, active, review):
    if review:
        return "current" if active else "superseded"
    return "failed" if any(item["job_status"] == "failed" for item in entries) else "incomplete"


def _bundle_facts(saved, review):
    dates = sorted(item["created_at"] for item in saved)
    return {
        "document_ids": [item["id"] for item in saved],
        "review_document_id": review["id"] if review else None,
        "executor_models": sorted(
            {item["executor_model"] for item in saved if item["executor_model"]}
        ),
        "diversity": proposal_diversity(
            [item for item in saved if "proposal:" in item["scope_key"]]
        ),
        "recommendation_count": int((review or {}).get("recommendation_count") or 0),
        "rejected_idea_count": int((review or {}).get("rejected_idea_count") or 0),
        "first_recorded_at": dates[0] if dates else None,
        "last_recorded_at": dates[-1] if dates else None,
    }


def _recorded_generations(documents, plans, by_hash):
    recorded = {}
    for row in documents.values():
        identity = (row["scope_key"], row["input_hash"])
        generation = by_hash.get(identity, _generation(row, plans))
        bundle = recorded.setdefault(
            (generation, row["snapshot_id"]), {"document_ids": [], "generation_inferred": False}
        )
        bundle["document_ids"].append(row["id"])
        token = str((plans.get(row["snapshot_id"]) or {}).get("interface_hash") or "")
        if (
            token.startswith("functional-v2|")
            and not row["scope_key"].startswith("functional:")
            and identity not in by_hash
        ):
            bundle["generation_inferred"] = True
    return recorded
