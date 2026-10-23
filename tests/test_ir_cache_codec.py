"""Parser storage encoding does not alter source facts or relationship resolution."""

from __future__ import annotations

import json

import pytest

from anaxigraph.ir_codec import decode_metadata, encode_metadata
from anaxigraph.persistence.temporal_files import compact_file_fact_metadata
from anaxigraph.persistence.temporal_hashing import resolver_context_hash
from anaxigraph.persistence.temporal_reads import snapshot_files
from anaxigraph.scanner import RepositoryScanner


def test_parser_codec_matches_deployed_envelope_and_roundtrips_all_metadata():
    value = {
        "analysis_version": 5,
        "dependencies": [{"target": f"module_{i}", "names": ["deliver"]} for i in range(50)],
        "ir": {"schema_version": "anaxigraph-ir-v2", "evidence_facts": ["fact"] * 500},
    }
    encoded = encode_metadata(value)
    assert json.loads(encoded)["$anaxigraph_metadata"] == "zlib-v1"
    assert len(encoded) < len(json.dumps(value)) / 2
    assert decode_metadata(encoded) == value
    assert encode_metadata(json.loads(encoded)) == encoded
    assert (
        decode_metadata({**json.loads(encoded), "source_read": "cached"})["source_read"] == "cached"
    )
    assert encode_metadata({"small": True}) == '{"small":true}'


@pytest.mark.parametrize(
    "field,value", [("bytes", 1), ("bytes", 16_000_001), ("sha256", "bad"), ("data", "!invalid!")]
)
def test_parser_codec_rejects_corruption_or_invalid_bounds(field, value):
    envelope = json.loads(encode_metadata({"large": "Repeated semantic parser fact. " * 500}))
    envelope[field] = value
    with pytest.raises(ValueError):
        decode_metadata(envelope)


def test_parser_compaction_preserves_snapshots_fact_keys_and_resolver_hashes(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        original = snapshot_files(connection, stats.snapshot_id)
        keys = [
            tuple(row)
            for row in connection.execute("SELECT id,fact_key FROM file_facts ORDER BY id")
        ]
        hashes = {
            row["id"]: resolver_context_hash(row["metadata_json"])
            for row in connection.execute("SELECT id,metadata_json FROM file_facts")
        }
    with database.transaction() as connection:
        # Existing uncompressed schema11 facts remain a valid migration source.
        for row in connection.execute("SELECT id,metadata_json FROM file_facts").fetchall():
            connection.execute(
                "UPDATE file_facts SET metadata_json=? WHERE id=?",
                (
                    json.dumps(decode_metadata(row["metadata_json"])),
                    row["id"],
                ),
            )
        assert compact_file_fact_metadata(connection) > 0
        assert compact_file_fact_metadata(connection) == 0
        assert snapshot_files(connection, stats.snapshot_id) == original
        assert [
            tuple(row)
            for row in connection.execute("SELECT id,fact_key FROM file_facts ORDER BY id")
        ] == keys
        for row in connection.execute("SELECT id,metadata_json FROM file_facts"):
            assert resolver_context_hash(row["metadata_json"]) == hashes[row["id"]]


def test_interrupted_cache_rewrite_resumes_after_saved_schema_upgrade(
    repository, database, monkeypatch
):
    from contextlib import closing

    from test_cold_semantic_payloads import _saved_rows

    import anaxigraph.persistence.index_initialization as initialization
    from anaxigraph.persistence.index_backup import backup_path, validate_schema_backup
    from anaxigraph.persistence.schema import SCHEMA_VERSION
    from anaxigraph.storage import AnaxiIndex

    document, claim = _saved_rows(repository, database)
    with database.transaction() as connection:
        connection.execute("DELETE FROM schema_meta WHERE key='parser-cache-compaction-v2'")
        connection.execute("UPDATE schema_meta SET value='12' WHERE key='schema_version'")
    rewrite = initialization.compact_file_fact_metadata

    def interrupt(*args, **kwargs):
        raise RuntimeError("interrupted disposable cache rewrite")

    monkeypatch.setattr(initialization, "compact_file_fact_metadata", interrupt)
    with pytest.raises(RuntimeError, match="interrupted disposable"):
        AnaxiIndex(database.path)
    validate_schema_backup(backup_path(database.path, 12), expected_version=12)
    with closing(database.connect()) as connection:
        assert (
            int(
                connection.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()[0]
            )
            == SCHEMA_VERSION
        )
        assert (
            dict(connection.execute("SELECT * FROM semantic_document_values").fetchone())
            == document
        )
        assert dict(connection.execute("SELECT * FROM semantic_claim_values").fetchone()) == claim
    monkeypatch.setattr(initialization, "compact_file_fact_metadata", rewrite)
    recovered = AnaxiIndex(database.path)
    with closing(recovered.connect()) as connection:
        assert (
            connection.execute(
                "SELECT value FROM schema_meta WHERE key='parser-cache-compaction-v2'"
            ).fetchone()[0]
            == "complete"
        )
        assert (
            dict(connection.execute("SELECT * FROM semantic_document_values").fetchone())
            == document
        )
        assert dict(connection.execute("SELECT * FROM semantic_claim_values").fetchone()) == claim
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_binary_sqlite_storage_removes_base64_without_changing_logical_metadata():
    from anaxigraph.ir_codec import storage_metadata

    value = {
        "call_sites": [{"target": f"service_{i}.send", "line": i} for i in range(200)],
        "ir": {"evidence_facts": [{"kind": "registrations", "value": "register(service)"}]},
        "symbols": ["deliver"],
    }
    legacy = encode_metadata(value)
    packed = storage_metadata(value)
    assert isinstance(packed, bytes)
    assert len(packed) < len(legacy)
    assert decode_metadata(packed) == decode_metadata(legacy) == value
    assert storage_metadata(decode_metadata(packed)) == packed
    assert storage_metadata({"small": True}) == '{"small":true}'


@pytest.mark.parametrize("damage", ["header", "declared_size", "body", "trailing"])
def test_binary_parser_cache_rejects_corruption_and_unbounded_decode(damage):
    from anaxigraph.ir_codec import storage_metadata

    packed = storage_metadata({"large": "Useful cached syntax evidence. " * 1_000})
    boundary = len(b"ANAXIGRAPH-IR\x00\x01")
    if damage == "header":
        packed = b"invalid" + packed
    elif damage == "declared_size":
        packed = packed[:boundary] + (16_000_001).to_bytes(4, "big") + packed[boundary + 4 :]
    elif damage == "body":
        packed = packed[:-1] + bytes([packed[-1] ^ 1])
    else:
        packed += b"trailing bytes"
    with pytest.raises(ValueError):
        decode_metadata(packed)
