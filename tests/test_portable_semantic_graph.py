"""Semantic transport preserves paid results while rebuilding graph caches per clone."""

from __future__ import annotations

import hashlib
import json
import lzma

import pytest

from anaxigraph.persistence.portable_rows import decoded_row
from anaxigraph.portable_codec import decode_partition
from anaxigraph.portable_io import publish_record, read_record


def _document(key, kind, value):
    return {
        "key": "semantic_documents:" + key,
        "value": {"document_kind": kind, "value_json": value},
    }


def test_legacy_results_are_cold_compressed_without_truncating_original_values(tmp_path):
    legacy = {
        "summary": "An explicitly saved legacy description. " * 1_000,
        "responsibilities": [f"Original responsibility {i}" for i in range(30)],
        "command": "A public command contract, not a worker process",
        "evidence": [f"service.py:{i}" for i in range(50)],
    }
    annotation = {"overview": "Serve requests.", "detail": "Preserves the public contract."}
    rows = [
        _document("a", "intrinsic", legacy),
        _document("b", "annotation", annotation),
    ]
    saved = publish_record(tmp_path, {"semantic_documents": rows}, {})
    manifest, tables = read_record(tmp_path)
    parts = manifest["parts"]
    assert manifest["format"] == "anaxigraph-record-v4"
    assert {part["codec"] for part in parts} == {"jsonl", "xz"}
    archived = next(part for part in parts if part["codec"] == "xz")
    assert archived["bytes"] < archived["decoded_bytes"] / 10
    assert archived["path"].startswith("legacy/")
    assert sorted(tables["semantic_documents"], key=lambda row: row["key"]) == rows
    assert saved["files"] <= 32
    assert publish_record(tmp_path, {"semantic_documents": rows}, {})["changed_files"] == 0


def test_current_results_are_not_subject_to_runtime_key_scrubbing():
    value = {"command": "Run a public operation", "pid": "A domain identifier"}
    row = decoded_row({"value_json": json.dumps(value), "metadata_json": '{"pid":42}'}, "/repo")
    assert row["value_json"] == value
    assert row["metadata_json"] == {}


@pytest.mark.parametrize("size", [0, 10, 4_000_001, -1, "10"])
def test_compressed_record_refuses_incorrect_or_unbounded_decoded_size(size):
    content = lzma.compress(b"original result" * 100, preset=1)
    with pytest.raises(ValueError, match="size"):
        decode_partition(content, {"codec": "xz", "decoded_bytes": size})


def test_record_checks_compressed_checksum_before_decoding(tmp_path):
    publish_record(tmp_path, {"semantic_documents": [_document("a", "intrinsic", {})]}, {})
    path = tmp_path / "anaxigraph/manifest.json"
    manifest = json.loads(path.read_bytes())
    part = manifest["parts"][0]
    target = tmp_path / "anaxigraph" / part["path"]
    target.write_bytes(b"altered archive")
    with pytest.raises(ValueError, match="incomplete or changed"):
        read_record(tmp_path)
    # A valid checksum still cannot authorize an understated decompression bound.
    content = lzma.compress(b"X" * 100_000, preset=1)
    target.write_bytes(content)
    part.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), decoded_bytes=1)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="declared size"):
        read_record(tmp_path)


def test_unchanged_hash_bucket_is_reused_when_another_row_changes(tmp_path):
    rows = [{"key": f"source_files:{i}", "value": {"path": f"file-{i}.py"}} for i in range(40)]
    first = publish_record(tmp_path, {"source_files": rows}, {})["manifest"]
    assert len(first["parts"]) == 2
    rows[0]["value"]["path"] = "updated.py"
    second = publish_record(tmp_path, {"source_files": rows}, {})["manifest"]
    old = {part["path"] for part in first["parts"]}
    new = {part["path"] for part in second["parts"]}
    assert len(old & new) == 1
    assert len(list((tmp_path / "anaxigraph/mapping").glob("*.jsonl"))) == 2


def test_plain_v2_records_remain_readable(tmp_path):
    publish_record(tmp_path, {"source_files": [{"key": "source_files:a", "value": {}}]}, {})
    path = tmp_path / "anaxigraph/manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["format"] = "anaxigraph-record-v2"
    for part in manifest["parts"]:
        part.pop("codec")
        part.pop("decoded_bytes")
    path.write_text(json.dumps(manifest))
    assert read_record(tmp_path)[1]["source_files"][0]["key"] == "source_files:a"


def test_catalogue_manifest_and_immutable_review_reuse_across_a_clone(
    repository, database, tmp_path
):
    from semantic_support import _agent_pattern_response
    from test_pattern_catalogue_review import _claim, _prepare
    from test_portable_record import publish_and_clone

    from anaxigraph.pattern_evaluation_contract import validated_pattern_response
    from anaxigraph.pattern_intelligence import PatternIntelligenceService
    from anaxigraph.persistence.pattern_review_references import expanded_pattern_review
    from anaxigraph.portable_record import save_record
    from anaxigraph.scanner import RepositoryScanner
    from anaxigraph.semantic_pattern_requests import pattern_request
    from anaxigraph.semantic_results import SemanticPersistenceService
    from anaxigraph.storage import AnaxiIndex

    stats, semantic = _prepare(repository, database)
    persistence = SemanticPersistenceService(database)
    for kind in ("pattern_assessment", "pattern_review"):
        with database.connect() as connection:
            identifier = connection.execute(
                "SELECT id FROM semantic_jobs WHERE job_kind=? ORDER BY id LIMIT 1", (kind,)
            ).fetchone()[0]
        job = _claim(database, stats, semantic, identifier)
        request = pattern_request(database, job, repository, semantic)
        value = _agent_pattern_response(request, kind)
        persistence.complete_job(job, validated_pattern_response(value, request), "agent", semantic)
    before = PatternIntelligenceService(database).catalogue(stats.repository_id)
    save_record(database, stats.repository_id)
    clone = publish_and_clone(repository, tmp_path / "other-clone")
    local = AnaxiIndex(tmp_path / "local.db")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "shift_ids.py").write_text("VALUE=1\n")
    RepositoryScanner(local).scan(elsewhere)
    restored = RepositoryScanner(local).scan(clone)
    assert restored.repository_id != stats.repository_id
    after = PatternIntelligenceService(local).catalogue(restored.repository_id)
    for field in ("expected", "considered", "rated", "reviewed", "missing", "pending_review"):
        assert after["catalogue"][field] == before["catalogue"][field]
    assert after["catalogue"]["manifest_saved"]
    with local.connect() as connection:
        row = dict(
            connection.execute(
                "SELECT * FROM semantic_documents WHERE repository_id=? AND document_kind='pattern_review'",
                (restored.repository_id,),
            ).fetchone()
        )
        resolved = expanded_pattern_review(connection, row)
        assert resolved["evaluation"] and not resolved.get("assessment_unavailable")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM semantic_claims").fetchone()[0] == 0


def test_function_and_contract_annotations_are_rebuilt_without_model_calls(
    tmp_path, database, monkeypatch
):
    from test_knowledge_graph import _annotation, _repository
    from test_portable_record import git, publish_and_clone

    from anaxigraph.config import load_config
    from anaxigraph.knowledge_annotation_contract import validated_annotation
    from anaxigraph.knowledge_detail import entity_detail
    from anaxigraph.portable_record import save_record
    from anaxigraph.scanner import RepositoryScanner
    from anaxigraph.storage import AnaxiIndex
    from anaxigraph.understanding import SemanticEngine

    root = _repository(tmp_path)
    (root / ".anaxigraph.yml").write_text("semantic:\n  enabled: true\n  provider: agent\n")
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.com")
    git(root, "config", "user.name", "Fixture")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Source")
    stats = RepositoryScanner(database).scan(root)
    config = load_config(root)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, root, config)
    with database.connect() as connection:
        identifier = connection.execute(
            "SELECT id FROM semantic_jobs WHERE job_kind='annotation' AND scope_key='service.py'"
        ).fetchone()[0]
    job = engine._services.leases.claim_job(
        stats.repository_id, config.semantic, job_ids=(identifier,)
    )
    value = _annotation()
    engine._services.persistence.complete_job(
        job, validated_annotation(value), "agent", config.semantic
    )
    save_record(database, stats.repository_id)
    clone = publish_and_clone(root, tmp_path / "fresh-clone")
    local = AnaxiIndex(tmp_path / "fresh-index.db")

    def forbidden(*args, **kwargs):
        raise AssertionError("Portable import must not invoke a model")

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", forbidden)
    restored = RepositoryScanner(local).scan(clone)
    (clone / "service.py").unlink()
    module = entity_detail(local, restored.repository_id, "module:service.py")
    function = entity_detail(local, restored.repository_id, "function:service.py#service.calculate")
    assert module["node"]["overview"] == value["overview"]
    assert module["node"]["detail"] == value["detail"]
    assert function["node"]["overview"] == value["functions"][0]["overview"]
    assert module["contracts"][0]["properties"]["invariants"] == ["input is unchanged"]
    assert module["contracts"][0]["provenance"]["annotation"]["verification"] == "unverified"
    assert save_record(local, restored.repository_id)["files"] <= 32


def test_publication_checks_staging_space_before_any_write(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import anaxigraph.portable_io as io

    publish_record(tmp_path, {}, {})
    before = {
        path: path.read_bytes() for path in (tmp_path / "anaxigraph").rglob("*") if path.is_file()
    }
    monkeypatch.setattr(io.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="space"):
        publish_record(tmp_path, {"source_files": [{"key": "source_files:a", "value": {}}]}, {})
    assert {path: path.read_bytes() for path in before} == before
    assert set(path for path in (tmp_path / "anaxigraph").rglob("*") if path.is_file()) == set(
        before
    )


def test_locally_deployed_v3_mixed_xz_record_is_readable(tmp_path):
    rows = [{"key": "source_files:a", "value": {"path": "service.py"}}]
    publish_record(tmp_path, {"source_files": rows}, {})
    directory = tmp_path / "anaxigraph"
    manifest = json.loads((directory / "manifest.json").read_bytes())
    part = manifest["parts"][0]
    decoded = json.dumps({"table": "source_files", **rows[0]}).encode() + b"\n"
    content = lzma.compress(decoded, preset=1)
    (directory / part["path"]).write_bytes(content)
    part.update(
        table="mixed",
        encoding="xz",
        uncompressed_bytes=len(decoded),
        bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    part.pop("codec")
    part.pop("decoded_bytes")
    manifest["format"] = "anaxigraph-record-v3"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    assert read_record(tmp_path)[1]["source_files"] == rows
    manifest["format"] = "anaxigraph-record-v4"
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="legacy v3"):
        read_record(tmp_path)


def test_unchanged_cold_chunks_reuse_checked_bytes_without_recompressing(tmp_path, monkeypatch):
    import anaxigraph.portable_io as io

    rows = [_document("a", "intrinsic", {"summary": "A preserved original. " * 300})]
    saved = publish_record(tmp_path, {"semantic_documents": rows}, {})
    assert saved["parts"] == 1

    def forbidden(*args, **kwargs):
        raise AssertionError("Unchanged cold records must reuse their checked encoding")

    monkeypatch.setattr(io, "encode_partition", forbidden)
    again = publish_record(tmp_path, {"semantic_documents": rows}, {})
    assert again["changed_files"] == again["temporary_bytes"] == 0


def test_paid_understanding_survives_local_parser_version_change(repository, database, tmp_path):
    from fresh_eyes_support import baseline_review
    from test_portable_record import _selected_values, publish_and_clone

    from anaxigraph.config import load_config
    from anaxigraph.portable_record import save_record
    from anaxigraph.scanner import RepositoryScanner
    from anaxigraph.storage import AnaxiIndex
    from anaxigraph.understanding import SemanticEngine

    review = baseline_review(repository, database)
    with database.connect() as connection:
        original = _selected_values(connection, review.repository_id)
    save_record(database, review.repository_id)
    manifest, tables = read_record(repository)
    # A prior release used a different deterministic parser/app signature, while
    # every paid interpretation still describes the exact same file contents.
    for row in tables["source_files"]:
        row["value"]["analysis_signature"] = "previous-parser-release"
    parts = {"parts", "views", "created_at", "format", "files"}
    publish_record(repository, tables, {k: v for k, v in manifest.items() if k not in parts})
    clone = publish_and_clone(repository, tmp_path / "upgraded-clone")
    local = AnaxiIndex(tmp_path / "upgraded.db")
    restored = RepositoryScanner(local).scan(clone)
    with local.connect() as connection:
        assert _selected_values(connection, restored.repository_id) == original
    config = load_config(clone)
    assert SemanticEngine(local).plan(restored.repository_id, clone, config).enqueued == 0


def test_reimport_after_other_file_edits_reuses_immutable_paid_rows(repository, database, tmp_path):
    from fresh_eyes_support import baseline_review
    from test_portable_record import git, publish_and_clone

    from anaxigraph.portable_record import save_record
    from anaxigraph.scanner import RepositoryScanner
    from anaxigraph.storage import AnaxiIndex

    review = baseline_review(repository, database)
    save_record(database, review.repository_id)
    clone = publish_and_clone(repository, tmp_path / "local-edits")
    local = AnaxiIndex(tmp_path / "local-edits.db")
    restored = RepositoryScanner(local).scan(clone)
    with local.connect() as connection:
        originals = [
            dict(row)
            for row in connection.execute("SELECT * FROM semantic_document_values ORDER BY id")
        ]
    for number in range(2):
        (repository / "other_feature.py").write_text(f"VALUE = {number}\n")
        current = RepositoryScanner(database).scan(repository)
        review.engine.plan(current.repository_id, repository, review.config)
        save_record(database, review.repository_id)
        git(repository, "add", ".")
        git(repository, "commit", "-qm", f"Update unrelated source and shared record {number}")
        git(clone, "pull", "--ff-only", "-q")
        restored = RepositoryScanner(local).scan(clone)
        with local.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute("SELECT * FROM semantic_document_values ORDER BY id")
            ]
            assert rows == originals
            selected = connection.execute(
                "SELECT DISTINCT intrinsic_document_id FROM semantic_scope_states "
                "WHERE snapshot_id=? AND scope_type='module' AND intrinsic_document_id IS NOT NULL",
                (restored.snapshot_id,),
            ).fetchall()
            assert selected
            assert {row[0] for row in selected} <= {row["id"] for row in originals}
