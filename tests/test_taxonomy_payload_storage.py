"""Derived map copies share immutable text without changing original values or provenance."""

import json

from test_cold_semantic_payloads import _saved_rows

from anaxigraph.persistence.semantic_payloads import (
    archive_taxonomy_payloads,
    collect_semantic_payloads,
    migrate_semantic_payloads,
    semantic_read_table,
)
from anaxigraph.persistence.semantic_taxonomy_carry import _copy_taxonomy
from anaxigraph.persistence.semantic_taxonomy_read import current_taxonomy, read_semantic_hierarchy
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_payload import payload_reference

_TABLES = (
    "semantic_taxonomies",
    "semantic_taxonomy_nodes",
    "semantic_taxonomy_memberships",
    "semantic_taxonomy_reviews",
)


def _seed(repository, database):
    document, claim = _saved_rows(repository, database)
    text = (
        'A résumé explains the literal "$anaxigraph_payload" token and original obligation. ' * 80
    )
    evidence = json.dumps(["pkg/util.py:3"] * 80, indent=2)
    validation = json.dumps({"accepted": True, "original": text}, indent=2, ensure_ascii=False)
    issues = json.dumps([{"message": text, "evidence": ["pkg/util.py:3"]}] * 12, indent=2)
    with database.transaction() as connection:
        taxonomy = connection.execute(
            """INSERT INTO semantic_taxonomies(repository_id,snapshot_id,input_hash,status,
            source,provider,model,prompt_version,schema_version,confidence,candidate_document_id,
            final_document_id,review_passes,validation_json,created_at,updated_at)
            VALUES (1,?,'original','current','original-source','agent','original-model',
            'original-prompt','original-schema',0.81,?,?,2,?,'2026-01-01','2026-01-02')""",
            (document["snapshot_id"], document["id"], document["id"], validation),
        ).lastrowid
        connection.execute(
            """INSERT INTO semantic_taxonomy_nodes(taxonomy_id,node_key,name,level,
            description,responsibility,confidence,rationale,evidence_json)
            VALUES (?,'responsibility','Original responsibility','area',?,?,0.81,?,?)""",
            (taxonomy, text, "Keep $anaxigraph_payload mentions readable.", text, evidence),
        )
        connection.execute(
            """INSERT INTO semantic_taxonomy_memberships(taxonomy_id,artifact_id,node_key,
            confidence,rationale,evidence_json) VALUES (?,?,'responsibility',0.81,?,?)""",
            (taxonomy, document["artifact_id"], text, evidence),
        )
        connection.executemany(
            """INSERT INTO semantic_taxonomy_reviews(taxonomy_id,pass_index,document_id,
            verdict,issues_json,validation_json,created_at) VALUES (?,?,?,'approve',?,?,'2026-01-02')""",
            [(taxonomy, index, document["id"], issues, validation) for index in (1, 2)],
        )
    return document, claim, taxonomy


def _rows(connection, *, decoded):
    return {
        table: [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM " + (semantic_read_table(table) if decoded else table)
            )
        ]
        for table in _TABLES
    }


def test_archive_preserves_all_taxonomy_rows_and_original_paid_records(repository, database):
    document, claim, taxonomy = _seed(repository, database)
    with database.transaction() as connection:
        originals = _rows(connection, decoded=False)
        assert archive_taxonomy_payloads(connection, taxonomy) == 5
        assert _rows(connection, decoded=True) == originals
        assert archive_taxonomy_payloads(connection, taxonomy) == 0
        assert connection.execute("SELECT COUNT(*) FROM semantic_payloads").fetchone()[0] == 4
        for table, field in (
            ("semantic_taxonomy_nodes", "rationale"),
            ("semantic_taxonomy_memberships", "rationale"),
            ("semantic_taxonomy_reviews", "issues_json"),
        ):
            stored = connection.execute(f"SELECT {field} FROM {table}").fetchone()[0]
            assert payload_reference(stored) and len(stored) < 100
        assert dict(connection.execute("SELECT * FROM semantic_documents").fetchone()) == document
        assert dict(connection.execute("SELECT * FROM semantic_claims").fetchone()) == claim
        assert current_taxonomy(connection, document["snapshot_id"])["review_passes"] == 2
        install_snapshot_projection(connection, document["snapshot_id"], include_symbols=False)
        assert (
            read_semantic_hierarchy(connection, document["snapshot_id"])[0]["description"]
            == (originals["semantic_taxonomy_nodes"][0]["description"])
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_carry_shares_bodies_and_gc_preserves_referenced_copy(repository, database):
    document, _claim, source_id = _seed(repository, database)
    path = repository / "web/helper.ts"
    path.write_text(path.read_text().replace("Sample", "Changed"))
    current = RepositoryScanner(database).scan(repository)
    with database.transaction() as connection:
        previous = connection.execute("SELECT * FROM semantic_taxonomies").fetchone()
        carried = _copy_taxonomy(
            connection,
            previous=previous,
            repository_id=1,
            snapshot_id=current.snapshot_id,
            input_hash="carried-input",
            source="carried_semantic_taxonomy",
        )
        count = connection.execute("SELECT COUNT(*) FROM semantic_payloads").fetchone()[0]
        raw = connection.execute(
            "SELECT taxonomy_id,rationale FROM semantic_taxonomy_memberships ORDER BY taxonomy_id"
        ).fetchall()
        assert len(raw) == 2 and raw[0]["rationale"] == raw[1]["rationale"]
        assert payload_reference(raw[0]["rationale"])
        original_review = connection.execute(
            "SELECT issues_json FROM semantic_taxonomy_review_values WHERE taxonomy_id=? LIMIT 1",
            (source_id,),
        ).fetchone()[0]
        connection.execute("DELETE FROM semantic_taxonomies WHERE id=?", (source_id,))
        assert collect_semantic_payloads(connection) == 0
        assert connection.execute("SELECT COUNT(*) FROM semantic_payloads").fetchone()[0] == count
        assert (
            connection.execute(
                "SELECT issues_json FROM semantic_taxonomy_review_values WHERE taxonomy_id=? LIMIT 1",
                (carried["id"],),
            ).fetchone()[0]
            == original_review
        )
        connection.execute("DELETE FROM semantic_taxonomies WHERE id=?", (carried["id"],))
        assert collect_semantic_payloads(connection) == count
        assert dict(connection.execute("SELECT * FROM semantic_documents").fetchone()) == document


def test_existing_migration_contract_also_normalizes_taxonomy_and_collects_safely(
    repository, database
):
    _document, _claim, _taxonomy = _seed(repository, database)
    with database.transaction() as connection:
        original = _rows(connection, decoded=False)
        assert migrate_semantic_payloads(connection) == {
            "archived_documents": 1,
            "archived_claims": 1,
        }
        assert _rows(connection, decoded=True) == original
        assert collect_semantic_payloads(connection) == 0
