"""A cached candidate plan must not strand assessments or reviews after work is retired."""

import pytest
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.workflow_execution import WorkflowExecution
from anaxigraph.workflow_settings import WorkflowSettings


@pytest.mark.parametrize("retired_kind", ["pattern_assessment", "pattern_review"])
def test_cached_plan_recreates_retired_work_without_repeating_saved_results(
    repository, database, monkeypatch, retired_kind
):
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    row = database.repository(repository)
    settings = WorkflowSettings(database.path).read(row["id"], 2)["steps"]

    def run(step):
        return WorkflowExecution(
            database, row, config, WorkflowRequest(workflow="patterns", step=step), settings
        ).run()

    assert run("pattern_plan")["status"] == "complete"
    if retired_kind == "pattern_review":
        assert run("pattern_assessment")["status"] == "complete"
    with database.transaction() as connection:
        retired = connection.execute(
            "SELECT id, scope_key FROM semantic_jobs WHERE job_kind = ? AND status = 'pending' LIMIT 1",
            (retired_kind,),
        ).fetchone()
        assert retired
        connection.execute(
            "UPDATE semantic_jobs SET status = 'superseded', metadata_json = '{}' WHERE id = ?",
            (retired["id"],),
        )
        saved = list(
            connection.execute("SELECT id, attempts FROM semantic_jobs WHERE status = 'completed'")
        )
    result = run("pattern_assessment" if retired_kind == "pattern_assessment" else "pattern_review")
    assert result["status"] == "complete", result
    assert run("pattern_review")["status"] == "complete"
    with database.connect() as connection:
        coverage = workflow_coverage(connection, row["current_snapshot_id"])["scopes"]["pattern"]
        assert coverage["current"] == coverage["total"] > 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_jobs WHERE scope_key = ? AND job_kind = ? AND status = 'completed'",
                (retired["scope_key"], retired_kind),
            ).fetchone()[0]
            == 1
        )
        after = {
            job["id"]: job["attempts"]
            for job in connection.execute(
                "SELECT id, attempts FROM semantic_jobs WHERE status = 'completed'"
            )
        }
        assert all(after[job["id"]] == job["attempts"] for job in saved)
    assert run("pattern_review")["processed"] == 0
