from __future__ import annotations

import json
import subprocess
import sys

from anaxigraph.persistence import inspect_index
from anaxigraph.scanner import RepositoryScanner


def test_doctor_proves_parity_and_refuses_early_compaction(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    report = inspect_index(database.path, database.connect)

    assert report["status"] == "healthy"
    assert report["schema_version"] == 8
    assert report["integrity"] == "ok"
    assert report["parity"] == {
        "status": "exact",
        "snapshots_checked": 1,
        "mismatch_count": 0,
        "mismatches": [],
        "truncated": False,
    }
    assert report["lineage"]["status"] == "valid"
    assert report["reconstruction"]["status"] == "bounded"
    assert report["reconstruction"]["maximum_traversed_deltas"] == 0
    assert report["reconstruction"]["checkpoint_count"] == 1
    assert report["semantic_references"]["status"] == "exact"
    assert report["semantic_references"]["missing_canonical_references"] == 0
    assert report["rows"]["file_facts"] == stats.discovered
    assert report["compaction"]["eligible"] is False
    assert "compatibility_read_paths_active" in report["compaction"]["blockers"]
    assert report["compaction"]["message"].endswith("No data was deleted.")


def test_doctor_fails_closed_when_canonical_fact_diverges(repository, database):
    RepositoryScanner(database).scan(repository)
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE file_facts SET summary = 'corrupted canonical fact'
            WHERE id = (SELECT MIN(id) FROM file_facts)
            """
        )

    report = inspect_index(database.path, database.connect)

    assert report["status"] == "blocked"
    assert report["parity"]["status"] == "mismatch"
    assert report["parity"]["mismatches"][0]["records"] == ["files"]
    assert "temporal_parity_mismatch" in report["blockers"]


def test_doctor_cli_emits_machine_readable_report(tmp_path):
    database = tmp_path / "doctor.db"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "anaxigraph",
            "doctor",
            "--db",
            str(database),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)

    assert report["status"] == "healthy"
    assert report["backup"] == {"required": False, "status": "not_required"}
    assert report["parity"]["snapshots_checked"] == 0
