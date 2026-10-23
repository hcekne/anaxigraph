"""Saved v1 evidence is an immutable archive, never a newly generated verdict."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256

from saved_fresh_eyes_support import seed_legacy_review

from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_fresh_eyes_contract import semantic_digest
from anaxigraph.semantic_fresh_eyes_grounding import read_review_grounding


def _saved(repository, database, *, grounding=None):
    stats = RepositoryScanner(database).scan(repository)
    documents = seed_legacy_review(
        database, stats.repository_id, stats.snapshot_id, grounding=grounding
    )
    with database.connect() as connection:
        row = connection.execute(
            "SELECT id,value_json FROM semantic_document_values WHERE repository_id=? "
            "AND document_kind='fresh_grounding'",
            (stats.repository_id,),
        ).fetchone()
    original = json.loads(row["value_json"]) if row else None
    return stats, documents["review"], original


def _read(database, stats, review_id):
    with database.connect() as connection:
        return read_review_grounding(
            connection,
            repository_id=stats.repository_id,
            snapshot_id=stats.snapshot_id,
            review_id=review_id,
        )


def _state(database):
    with database.connect() as connection:
        documents = [
            tuple(row)
            for row in connection.execute(
                "SELECT id,snapshot_id,document_kind,input_hash,value_json FROM semantic_documents ORDER BY id"
            )
        ]
        scopes = [
            tuple(row)
            for row in connection.execute(
                "SELECT snapshot_id,scope_type,scope_key,status,context_document_id FROM semantic_scope_states "
                "ORDER BY snapshot_id,scope_type,scope_key"
            )
        ]
    return sha256(json.dumps([documents, scopes]).encode()).hexdigest()


def test_original_grounding_values_are_returned_without_interpretation(repository, database):
    stats, review_id, original = _saved(repository, database)
    restored = _read(database, stats, review_id)
    assert restored == original
    assert restored["recommendations"][0]["evidence_state"] == {
        "reference_resolution": "resolved",
        "claim_support": "unchecked",
        "behavior_verification": "unchecked",
    }
    assert restored["recommendations"][0]["checks"][0]["value"] == "pkg/core.py"
    assert restored["summary"]["reviewed_snapshot_id"] == stats.snapshot_id


def test_source_changes_do_not_rewrite_historical_grounding(repository, database):
    stats, review_id, original = _saved(repository, database)
    core = repository / "pkg/core.py"
    core.write_text(core.read_text().replace("double(value)", "double(value) + 1"))
    changed = RepositoryScanner(database).scan(repository)
    assert changed.snapshot_id != stats.snapshot_id
    before = _state(database)
    restored = _read(database, changed, review_id)
    assert restored == original
    assert restored["snapshot_id"] == stats.snapshot_id
    assert _state(database) == before


def test_repeated_archive_reads_never_write_or_create_grounding(repository, database):
    stats, review_id, original = _saved(repository, database)
    before = _state(database)
    for _ in range(3):
        assert _read(database, stats, review_id) == original
    assert _state(database) == before
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT provider,source,previous_document_id,input_tokens FROM semantic_documents "
            "WHERE document_kind='fresh_grounding'"
        ).fetchall()
    assert len(rows) == 1
    assert tuple(rows[0]) == ("deterministic", "deterministic", review_id, 0)


def test_missing_original_grounding_remains_unknown(repository, database):
    stats, review_id, original = _saved(repository, database, grounding=False)
    assert original is None
    before = _state(database)
    assert _read(database, stats, review_id) is None
    assert _state(database) == before


def test_earlier_contract_and_status_are_preserved_exactly(repository, database):
    stats, review_id, original = _saved(repository, database)
    legacy = deepcopy(original)
    legacy["contract_version"] = "fresh-eyes-grounding-v1"
    legacy["recommendations"][0]["status"] = "confirmed"
    del legacy["recommendations"][0]["evidence_state"]
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_documents SET value_json=?,schema_version=?,input_hash=? "
            "WHERE document_kind='fresh_grounding'",
            (
                json.dumps(legacy),
                legacy["contract_version"],
                semantic_digest(
                    {"contract": legacy["contract_version"], "review_document_id": review_id}
                ),
            ),
        )
    assert _read(database, stats, review_id) == legacy
