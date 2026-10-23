"""Distribution releases do not invent a new structural analysis contract."""

from anaxigraph import scan_commit, scan_preparation, scanner


def test_release_only_update_reuses_structure_but_contract_change_reanalyzes(
    repository, database, monkeypatch
):
    runner = scanner.RepositoryScanner(database)
    first = runner.scan(repository)
    with database.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM file_facts").fetchone()[0]
    monkeypatch.setattr(scan_preparation, "__version__", "999.0.0", raising=False)
    monkeypatch.setattr(scan_commit, "__version__", "999.0.0")
    same = runner.scan(repository)
    assert same.snapshot_id == first.snapshot_id
    assert same.analyzed == 0
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM file_facts").fetchone()[0] == before
    monkeypatch.setattr(scanner, "ANALYSIS_VERSION", scanner.ANALYSIS_VERSION + 1)
    changed = runner.scan(repository)
    assert changed.snapshot_id != same.snapshot_id
    assert changed.analyzed == changed.discovered
