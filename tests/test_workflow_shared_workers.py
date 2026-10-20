"""A selected workflow joins live work instead of stopping when shared slots are full."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from semantic_support import _agent_dossier
from test_workflow_steps import choice
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_execution import WorkflowExecution


@pytest.mark.parametrize("only_one", [False, True])
def test_dashboard_joins_external_work_and_finishes_remaining_files(
    repository, database, monkeypatch, only_one
):
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    config = replace(
        config,
        semantic=replace(
            config.semantic,
            max_parallel_jobs=1,
            include=("pkg/core.py",) if only_one else (),
        ),
    )
    row = database.repository(repository)
    engine = SemanticEngine(database)
    packet = engine.claim_agent_work(row["id"], repository, config, agent_id="external")
    assert packet["status"] == "work"
    run = WorkflowExecution(
        database,
        row,
        config,
        WorkflowRequest(workflow="mapping", step="intrinsic"),
        {"intrinsic": [choice()]},
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run.run)
        try:
            deadline = time.monotonic() + 5
            while not run.joined_workers and not future.done() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert run.joined_workers, "Run Step stopped while another worker owned unfinished work"
            assert not future.done()
        finally:
            engine.submit_agent_work(
                row["id"],
                repository,
                config,
                job_id=packet["job"]["id"],
                lease_token=packet["lease"]["token"],
                dossier=_agent_dossier(packet["analysis_request"]),
            )
        result = future.result(timeout=15)
    assert result["status"] == "complete"
    assert result["processed"] == (0 if only_one else 7)
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT status, attempts FROM semantic_jobs WHERE job_kind = 'intrinsic'"
        ).fetchall()
    assert all(tuple(row) == ("completed", 1) for row in rows)


def test_dashboard_reclaims_an_expired_external_lease(repository, database, monkeypatch):
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    config = replace(config, semantic=replace(config.semantic, include=("pkg/core.py",)))
    row = database.repository(repository)
    engine = SemanticEngine(database)
    packet = engine.claim_agent_work(row["id"], repository, config, agent_id="crashed")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (packet["job"]["id"],),
        )
    result = WorkflowExecution(
        database,
        row,
        config,
        WorkflowRequest(workflow="mapping", step="intrinsic"),
        {"intrinsic": [choice()]},
    ).run()
    assert result["status"] == "complete"
    assert result["processed"] == 1
