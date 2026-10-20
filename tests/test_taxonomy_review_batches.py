"""Review batches survive interruption, save independently and keep provider passes ordered."""

import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from semantic_support import _DeterministicLifecycleProvider
from test_workflow_steps import choice
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.storage import AnaxiIndex
from anaxigraph.workflow_execution import WorkflowExecution
from anaxigraph.workflow_settings import WorkflowSettings


def test_batches_save_during_pass_and_resume_only_failed_work(repository, database, monkeypatch):
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    row = database.repository(repository)
    settings = WorkflowSettings(database.path).read(row["id"], 2)["steps"]

    def run(policy, step="taxonomy_review", max_jobs=None, db=database):
        return WorkflowExecution(
            db,
            row,
            policy,
            WorkflowRequest(workflow="mapping", step=step, max_jobs=max_jobs),
            settings,
        ).run()

    assert run(config, "taxonomy_proposal")["status"] == "complete"
    config = replace(
        config,
        semantic=replace(
            config.semantic, max_output_tokens=360, max_source_chars=5_000, max_attempts=1
        ),
    )
    entered, release = threading.Event(), threading.Event()
    barrier, lock = threading.Barrier(2), threading.Lock()
    calls, active, peak = Counter(), Counter(), Counter()
    fail = True

    class Provider(_DeterministicLifecycleProvider):
        def __init__(self, semantic):
            self.provider = semantic.provider

        def analyze(self, request):
            review_pass = request["review_pass"]
            index = request.get("chunk", {}).get("index", 0)
            key = (review_pass, index)
            with lock:
                calls[key] += 1
                active[review_pass] += 1
                peak[review_pass] = max(peak[review_pass], active[review_pass])
            try:
                assert self.provider == ("codex" if review_pass == 1 else "claude")
                if fail and review_pass == 1 and index in {1, 2}:
                    barrier.wait(5)
                    if index == 2:
                        entered.set()
                        assert release.wait(10)
                        raise RuntimeError("Only this batch needs retrying")
                if review_pass == 2:
                    with database.connect() as connection:
                        assert (
                            connection.execute(
                                "SELECT COUNT(*) FROM semantic_taxonomy_reviews"
                            ).fetchone()[0]
                            == 1
                        )
                return super().analyze(request)
            finally:
                with lock:
                    active[review_pass] -= 1

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", Provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, config)
        try:
            assert entered.wait(5)
            for _ in range(200):
                with database.connect() as connection:
                    progress = workflow_coverage(connection, row["current_snapshot_id"])[
                        "taxonomy_review"
                    ]
                if progress["passes"] and progress["passes"][0]["completed_batches"]:
                    break
                time.sleep(0.01)
            first = progress["passes"][0]
            assert first["completed_batches"] > 0
            assert first["completed_batches"] < first["total_batches"]
            assert first["active_workers"] >= 1
            assert first["reconciliation"] == "not_started"
            assert first["elapsed_seconds"] >= 0
        finally:
            release.set()
        assert future.result(timeout=15)["status"] == "waiting"
    assert peak[1] == 2
    assert calls[(1, 0)] == 0  # No reconciliation or second pass until every batch finishes.
    assert not any(key[0] == 2 for key in calls)
    before = calls.copy()
    with database.connect() as connection:
        saved = list(
            connection.execute(
                "SELECT id, attempts FROM semantic_jobs WHERE status = 'completed' ORDER BY id"
            )
        )
    fail = False
    reopened = AnaxiIndex(database.path)
    reopened.initialize()
    # Removing an old output cap must preserve the saved batch boundaries.
    config = replace(config, semantic=replace(config.semantic, max_output_tokens=None))
    assert run(config, db=reopened)["status"] == "complete"
    assert calls[(1, 2)] == 2
    assert calls[(1, 0)] == calls[(2, 0)] == 1
    assert all(calls[key] == count for key, count in before.items() if key != (1, 2))
    with database.connect() as connection:
        after = {
            row["id"]: row["attempts"]
            for row in connection.execute(
                "SELECT id, attempts FROM semantic_jobs WHERE status = 'completed'"
            )
        }
        assert all(after[row["id"]] == row["attempts"] for row in saved)
        progress = workflow_coverage(connection, row["current_snapshot_id"])["taxonomy_review"]
        for review in progress["passes"]:
            assert review["completed_batches"] == review["total_batches"]
            assert review["reconciliation"] == "complete"
            assert review["active_workers"] == 0
        assert progress["passes"][-1]["final"]
        final = connection.execute(
            "SELECT d.value_json FROM semantic_taxonomies t JOIN semantic_documents d "
            "ON d.id = t.final_document_id WHERE t.status = 'current'"
        ).fetchone()
        paths = {
            member["path"]
            for area in json.loads(final[0])["taxonomy"]["areas"]
            for group in area["subsystems"]
            for member in group["members"]
        }
        assert len(paths) == 8
        assert not any(path.startswith("@anaxigraph/") for path in paths)
    assert run(config, db=reopened)["processed"] == 0


def test_sample_limit_checkpoints_a_batch(repository, database, monkeypatch):
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    row = database.repository(repository)
    settings = WorkflowSettings(database.path).read(row["id"], 2)["steps"]
    assert (
        WorkflowExecution(
            database,
            row,
            config,
            WorkflowRequest(workflow="mapping", step="taxonomy_proposal"),
            settings,
        ).run()["status"]
        == "complete"
    )
    config = replace(config, semantic=replace(config.semantic, max_output_tokens=360))
    settings["taxonomy_review"] = [
        choice(workers=2),
        choice("claude", "claude-opus-5-5", workers=2),
    ]
    result = WorkflowExecution(
        database,
        row,
        config,
        WorkflowRequest(workflow="mapping", step="taxonomy_review", max_jobs=1),
        settings,
    ).run()
    assert result["status"] == "waiting"
    assert result["processed"] == 1
    with database.connect() as connection:
        progress = workflow_coverage(connection, row["current_snapshot_id"])["taxonomy_review"]
    assert progress["passes"][0]["completed_batches"] == 1
    assert progress["passes"][0]["total_batches"] > 1
