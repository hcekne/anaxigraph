"""Legacy values remain exact and queryable without duplicate stored payloads."""

from __future__ import annotations

import json
import sqlite3

import pytest

from anaxigraph.persistence.semantic_payloads import (
    collect_semantic_payloads,
    migrate_semantic_payloads,
    register_semantic_payloads,
)
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_payload import payload_reference


def _saved_rows(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    raw = json.dumps(
        {
            "summary": "A precise original explanation. " * 100,
            "unicode": "résumé",
            "evidence": ["pkg/util.py:3"],
        },
        indent=2,
        ensure_ascii=False,
    )
    with database.transaction() as connection:
        fact = connection.execute(
            "SELECT id,artifact_id FROM file_facts ORDER BY id LIMIT 1"
        ).fetchone()
        document = {
            "repository_id": stats.repository_id,
            "snapshot_id": stats.snapshot_id,
            "scope_type": "module",
            "scope_key": "pkg/util.py",
            "artifact_id": fact["artifact_id"],
            "file_fact_id": fact["id"],
            "document_kind": "intrinsic",
            "input_hash": "original-input",
            "intent_fingerprint": "original-intent",
            "value_json": raw,
            "source": "agent",
            "provider": "agent",
            "model": "original-model",
            "prompt_version": "original-prompt",
            "schema_version": "original-schema",
            "confidence": 0.81,
            "supporting_evidence_json": '["Original document evidence"]',
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        fields = ",".join(document)
        identifier = connection.execute(
            f"INSERT INTO semantic_documents({fields}) VALUES ({','.join('?' for _ in document)})",
            list(document.values()),
        ).lastrowid
        connection.execute(
            """INSERT INTO semantic_claims(file_fact_id,claim_type,value_json,source,provider,model,prompt_version,created_at,confidence,supporting_evidence_json)
        VALUES (?,'module_analysis',?,'agent','agent','original-model','original-prompt','2026-01-01',0.7,'["Independent claim evidence"]')""",
            (fact["id"], raw),
        )
        original_document = dict(
            connection.execute(
                "SELECT * FROM semantic_documents WHERE id=?", (identifier,)
            ).fetchone()
        )
        original_claim = dict(connection.execute("SELECT * FROM semantic_claims").fetchone())
    return original_document, original_claim


def test_legacy_document_and_claim_share_one_body_and_keep_exact_provenance(repository, database):
    document, claim = _saved_rows(repository, database)
    with database.transaction() as connection:
        result = migrate_semantic_payloads(connection)
        assert result == {"archived_documents": 1, "archived_claims": 1}
        assert (
            dict(connection.execute("SELECT * FROM semantic_document_values").fetchone())
            == document
        )
        assert dict(connection.execute("SELECT * FROM semantic_claim_values").fetchone()) == claim
        assert connection.execute("SELECT COUNT(*) FROM semantic_payloads").fetchone()[0] == 1
        stored = connection.execute("SELECT value_json FROM semantic_documents").fetchone()[0]
        assert payload_reference(stored) and len(stored) < 100
        assert (
            connection.execute(
                "SELECT json_extract(value_json,'$.unicode') FROM semantic_document_values"
            ).fetchone()[0]
            == "résumé"
        )
        assert migrate_semantic_payloads(connection) == {
            "archived_documents": 0,
            "archived_claims": 0,
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_collect_only_unreferenced_payloads_and_preserve_independent_claim(repository, database):
    _saved_rows(repository, database)
    with database.transaction() as connection:
        migrate_semantic_payloads(connection)
        connection.execute("DELETE FROM semantic_documents")
        assert collect_semantic_payloads(connection) == 0
        assert (
            json.loads(
                connection.execute("SELECT value_json FROM semantic_claim_values").fetchone()[0]
            )["unicode"]
            == "résumé"
        )
        connection.execute("DELETE FROM semantic_claims")
        assert collect_semantic_payloads(connection) == 1


def test_archive_checksum_is_checked_before_returning_legacy_knowledge(repository, database):
    _saved_rows(repository, database)
    with database.transaction() as connection:
        migrate_semantic_payloads(connection)
        connection.execute("UPDATE semantic_payloads SET data=?", (b"damaged archive",))
        register_semantic_payloads(connection)
        with pytest.raises(sqlite3.OperationalError, match="user-defined function"):
            connection.execute("SELECT value_json FROM semantic_document_values").fetchall()


def test_focused_left_join_decodes_only_selected_saved_result(repository, database, monkeypatch):
    import anaxigraph.persistence.semantic_payloads as payloads

    document, _claim = _saved_rows(repository, database)
    with database.transaction() as connection:
        for number in range(25):
            other = {key: value for key, value in document.items() if key != "id"}
            other["scope_key"] = f"other-{number}"
            other["value_json"] = json.dumps(
                {"summary": "A separate original. " * 200, "unit": number}
            )
            columns = ",".join(other)
            connection.execute(
                f"INSERT INTO semantic_documents({columns}) VALUES ({','.join('?' for _ in other)})",
                list(other.values()),
            )
        migrate_semantic_payloads(connection)
        calls = []
        decode = payloads.decode_payload

        def tracked(*args):
            calls.append(args[0])
            return decode(*args)

        monkeypatch.setattr(payloads, "decode_payload", tracked)
        register_semantic_payloads(connection)
        found = connection.execute(
            "SELECT d.value_json FROM (SELECT ? AS id) selected LEFT JOIN semantic_document_values d ON d.id=selected.id",
            (document["id"],),
        ).fetchone()[0]
        assert found == document["value_json"]
        assert len(calls) == 1
