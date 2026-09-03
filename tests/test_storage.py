from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex


def test_scan_lock_serializes_index_users(database):
    entered = threading.Event()
    release = threading.Event()
    acquired = threading.Event()
    second = AnaxiIndex(database.path)

    def hold_lock() -> None:
        with database.scan_lock():
            entered.set()
            assert release.wait(timeout=2)

    def wait_for_lock() -> None:
        assert entered.wait(timeout=2)
        with second.scan_lock():
            acquired.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        holder = executor.submit(hold_lock)
        assert entered.wait(timeout=2)
        waiter = executor.submit(wait_for_lock)
        try:
            assert not acquired.wait(timeout=0.1)
        finally:
            release.set()
        holder.result(timeout=2)
        waiter.result(timeout=2)

    assert acquired.is_set()


def test_reopening_index_compacts_only_terminal_semantic_work_packets(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    candidate = {
        "input_fingerprint": "candidate-v1",
        "matched_signals": [{"kind": "large_module", "evidence": ["pkg/core.py"]}],
        "priority": 90,
        "selection_reasons": ["Architectural hotspot"],
        "target": {"key": "module:pkg/core.py", "path": "pkg/core.py"},
    }
    rows = (
        ("completed-module", "intrinsic", "completed", {"neighbors": ["pkg/util.py"]}),
        (
            "completed-pattern",
            "pattern_assessment",
            "completed",
            {"candidate": candidate, "target_evidence": {"large": "discard me"}},
        ),
        (
            "proposal:a",
            "fresh_proposal",
            "completed",
            {
                "retention": "fresh-eyes-input-v1",
                "stage": "proposal",
                "slot": "a",
                "input_manifest": {"review_generation": 2, "stage": "clean_sheet_proposal"},
                "information_boundary": {"withheld": ["repository_paths"]},
            },
        ),
        ("superseded-module", "context", "superseded", {"neighbors": ["pkg/util.py"]}),
        ("failed-module", "context", "failed", {"neighbors": ["pkg/util.py"]}),
        ("pending-module", "context", "pending", {"neighbors": ["pkg/util.py"]}),
    )
    with database.transaction() as connection:
        connection.executemany(
            """
            INSERT INTO semantic_jobs(
                repository_id, snapshot_id, scope_type, scope_key, job_kind, reason, status,
                input_hash, provider, model, prompt_version, schema_version, available_at,
                metadata_json
            ) VALUES (?, ?, 'module', ?, ?, 'test', ?, ?, 'agent', '', 'test-v1',
                      'module-dossier-v4', '2026-08-30T00:00:00+00:00', ?)
            """,
            [
                (
                    stats.repository_id,
                    stats.snapshot_id,
                    scope_key,
                    job_kind,
                    status,
                    f"hash-{scope_key}",
                    json.dumps(metadata, sort_keys=True),
                )
                for scope_key, job_kind, status, metadata in rows
            ],
        )

    AnaxiIndex(database.path)

    with database.connect() as connection:
        stored = {
            row["scope_key"]: json.loads(row["metadata_json"])
            for row in connection.execute(
                "SELECT scope_key, metadata_json FROM semantic_jobs ORDER BY id"
            )
        }
    assert stored["completed-module"] == {}
    assert stored["superseded-module"] == {}
    assert stored["completed-pattern"] == {
        "retention": "pattern-evaluation-v1",
        "candidate": candidate,
    }
    assert stored["proposal:a"]["input_manifest"] == {
        "review_generation": 2,
        "stage": "clean_sheet_proposal",
    }
    assert stored["proposal:a"]["information_boundary"] == {"withheld": ["repository_paths"]}
    assert stored["failed-module"] == {"neighbors": ["pkg/util.py"]}
    assert stored["pending-module"] == {"neighbors": ["pkg/util.py"]}
