"""Parser upgrades share identical-source caches while retaining original paid provenance."""

import json

import pytest
from test_cold_semantic_payloads import _saved_rows

import anaxigraph.scanner as scanner
from anaxigraph.ir_codec import decode_metadata
from anaxigraph.persistence.temporal_reads import snapshot_files
from anaxigraph.scanner import RepositoryScanner


def _files(database, snapshot):
    with database.connect() as connection:
        return {row["path"]: row for row in snapshot_files(connection, snapshot)}


def test_parser_upgrade_reindexes_identical_source_and_preserves_paid_rows(
    repository, database, monkeypatch
):
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 5)
    document, claim = _saved_rows(repository, database)
    first = database.latest_snapshot(1)
    original = _files(database, first["id"])
    with database.connect() as connection:
        symbols = connection.execute("SELECT COUNT(*)FROM fact_symbols").fetchone()[0]
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 6)
    current = RepositoryScanner(database).scan(repository)
    historical = _files(database, first["id"])
    present = _files(database, current.snapshot_id)
    assert {path: row["file_fact_id"] for path, row in historical.items()} == {
        path: row["file_fact_id"] for path, row in present.items()
    }
    assert any(
        original[path]["file_fact_id"] != row["file_fact_id"] for path, row in present.items()
    )
    with database.connect() as connection:
        assert (
            dict(connection.execute("SELECT *FROM semantic_document_values").fetchone()) == document
        )
        assert dict(connection.execute("SELECT *FROM semantic_claim_values").fetchone()) == claim
        assert connection.execute("SELECT COUNT(*)FROM fact_symbols").fetchone()[0] == symbols
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_json FROM snapshots WHERE id=?", (first["id"],)
            ).fetchone()[0]
        )
        assert (
            metadata["analysis_signature"]
            == json.loads(first["metadata_json"])["analysis_signature"]
        )
        assert (
            metadata["structural_cache_reindex"]["rule"]
            == "same_path_raw_hash_and_resolver_context"
        )
        fact = connection.execute(
            "SELECT metadata_json FROM file_facts WHERE id=?", (document["file_fact_id"],)
        ).fetchone()
        metadata = decode_metadata(fact[0])
        assert (
            metadata["structural_cache_reindex"]["state"]
            == "current_cache_reuses_original_identity"
        )
        assert metadata["analysis_version"] == 6
        assert metadata["original_structural_identity"]["analysis_version"] == 5
        assert (
            connection.execute(
                "SELECT file_fact_id FROM checkpoint_files WHERE artifact_id=? LIMIT 1",
                (document["artifact_id"],),
            ).fetchone()[0]
            == document["file_fact_id"]
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_changed_source_keeps_original_parser_facts_for_the_saved_baseline(
    repository, database, monkeypatch
):
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 5)
    first = RepositoryScanner(database).scan(repository)
    original = _files(database, first.snapshot_id)
    path = repository / "pkg/util.py"
    path.write_text(path.read_text() + "\nEXTRA_BEHAVIOR = 2\n")
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 6)
    current = RepositoryScanner(database).scan(repository)
    historical = _files(database, first.snapshot_id)
    present = _files(database, current.snapshot_id)
    assert historical["pkg/util.py"]["file_fact_id"] == original["pkg/util.py"]["file_fact_id"]
    assert historical["pkg/util.py"]["raw_hash"] != present["pkg/util.py"]["raw_hash"]
    assert historical["pkg/core.py"]["file_fact_id"] == present["pkg/core.py"]["file_fact_id"]
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*)FROM fact_symbols WHERE file_fact_id=?",
                (original["pkg/util.py"]["file_fact_id"],),
            ).fetchone()[0]
            > 0
        )


@pytest.mark.parametrize("preserve", ["history", "resolver", "pin"])
def test_recorded_history_and_changed_resolution_policy_preserve_original_facts(
    repository, database, monkeypatch, preserve
):
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 5)
    first = RepositoryScanner(database).scan(repository)
    original = _files(database, first.snapshot_id)
    if preserve == "history":
        with database.transaction() as connection:
            connection.execute("INSERT INTO schema_meta VALUES ('history-opt-in:1','true')")
    elif preserve == "pin":
        metadata = json.loads(
            database.resolve_snapshot(first.repository_id, first.snapshot_id)["metadata_json"]
        )
        metadata["structural_analysis"] = "as_recorded"
        with database.transaction() as connection:
            connection.execute(
                "UPDATE snapshots SET metadata_json=? WHERE id=?",
                (json.dumps(metadata), first.snapshot_id),
            )
    else:
        config = repository / ".anaxigraph.yml"
        config.write_text(config.read_text() + "\naliases:\n  '@domain': pkg\n")
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 6)
    RepositoryScanner(database).scan(repository)
    historical = _files(database, first.snapshot_id)
    assert {path: row["file_fact_id"] for path, row in historical.items()} == {
        path: row["file_fact_id"] for path, row in original.items()
    }


def test_coverage_reuses_only_equal_edges_and_preserves_measured_provenance(
    repository, database, monkeypatch
):
    from anaxigraph.persistence.temporal_relationships import _edge_value

    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 5)
    first = RepositoryScanner(database).scan(repository)
    with database.transaction() as connection:
        edge = dict(connection.execute("SELECT * FROM relationship_edges LIMIT 1").fetchone())
        connection.execute(
            "INSERT INTO coverage_measurements(snapshot_id,relationship_edge_id,provider,line_coverage,evidence) VALUES (?,?,?, ?,?)",
            (first.snapshot_id, edge["id"], "measured-test", 0.375, "original execution witness"),
        )
        measured = dict(
            connection.execute(
                "SELECT * FROM coverage_measurements WHERE provider='measured-test'"
            ).fetchone()
        )
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 6)
    RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        after = dict(
            connection.execute(
                "SELECT * FROM coverage_measurements WHERE id=?", (measured["id"],)
            ).fetchone()
        )
        effective = dict(
            connection.execute(
                "SELECT * FROM relationship_edges WHERE id=?", (after["relationship_edge_id"],)
            ).fetchone()
        )
        assert after["relationship_edge_id"] != measured["relationship_edge_id"]
        assert _edge_value(effective) == _edge_value(edge)
        assert {k: v for k, v in after.items() if k != "relationship_edge_id"} == {
            k: v for k, v in measured.items() if k != "relationship_edge_id"
        }
        assert not connection.execute(
            "SELECT 1 FROM relationship_sets WHERE id=?", (edge["relationship_set_id"],)
        ).fetchone()
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_current_cache_merge_never_retargets_a_new_paid_fact(repository, database, monkeypatch):
    import anaxigraph.persistence.temporal_cache_reindex as reindex
    from anaxigraph.persistence.temporal_cache_merge import merge_current_fact_identities

    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 5)
    document, _claim = _saved_rows(repository, database)
    with database.connect() as connection:
        original = dict(
            connection.execute(
                "SELECT * FROM file_facts WHERE id=?", (document["file_fact_id"],)
            ).fetchone()
        )
    monkeypatch.setattr(reindex, "merge_current_fact_identities", lambda *_arguments: 0)
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 6)
    current = RepositoryScanner(database).scan(repository)
    present = next(
        row
        for row in _files(database, current.snapshot_id).values()
        if row["artifact_id"] == document["artifact_id"]
    )
    with database.transaction() as connection:
        copied = {key: value for key, value in document.items() if key != "id"}
        copied.update(file_fact_id=present["file_fact_id"], input_hash="another-paid-execution")
        connection.execute(
            "INSERT INTO semantic_documents("
            + ",".join(copied)
            + ")VALUES("
            + ",".join("?" for _ in copied)
            + ")",
            list(copied.values()),
        )
        before = [dict(row) for row in connection.execute("SELECT *FROM semantic_document_values")]
        merged = merge_current_fact_identities(
            connection,
            {original["id"]: (present["file_fact_id"], present["path"], "current")},
            {original["id"]: original},
        )
        assert merged == 0
        assert [
            dict(row) for row in connection.execute("SELECT *FROM semantic_document_values")
        ] == before
        assert connection.execute(
            "SELECT 1 FROM file_facts WHERE id=?", (present["file_fact_id"],)
        ).fetchone()


def test_merged_original_identity_is_reused_after_an_unrelated_edit(
    repository, database, monkeypatch
):
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 5)
    document, _claim = _saved_rows(repository, database)
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", 6)
    RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        before = connection.execute("SELECT COUNT(*)FROM file_facts").fetchone()[0]
    path = repository / "pkg/util.py"
    path.write_text(path.read_text() + "\nANOTHER_VALUE=3\n")
    stats = RepositoryScanner(database).scan(repository)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*)FROM file_facts").fetchone()[0] == before + 1
        assert (
            dict(connection.execute("SELECT *FROM semantic_document_values").fetchone()) == document
        )
    assert stats.analyzed == 1
