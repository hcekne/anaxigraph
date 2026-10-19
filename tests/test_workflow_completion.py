"""Single-card completion checks only that card, without planning downstream work."""

from test_workflow_steps import choice
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.workflow_execution import WorkflowExecution


def test_file_step_finishes_without_planning_next_card_or_rebuilding_repository_status(
    repository, database, monkeypatch
):
    prepare(repository, database, monkeypatch)
    execution = WorkflowExecution(
        database,
        database.repository(repository),
        load_config(repository),
        WorkflowRequest(workflow="mapping", step="intrinsic"),
        {"intrinsic": [choice(workers=2)]},
    )
    plan, run = execution.engine.plan, execution.engine.run_jobs
    plans, runs = [], []

    def track_plan(*args, **kwargs):
        plans.append(1)
        return plan(*args, **kwargs)

    def track_run(*args, **kwargs):
        runs.append(kwargs)
        return run(*args, **kwargs)

    def unrelated_status(*args, **kwargs):
        raise AssertionError("A completed file card must not rebuild unrelated workflow status")

    monkeypatch.setattr(execution.engine, "plan", track_plan)
    monkeypatch.setattr(execution.engine, "run_jobs", track_run)
    monkeypatch.setattr(execution.engine, "status", unrelated_status)
    monkeypatch.setattr(execution.engine, "fresh_eyes_status", unrelated_status)
    result = execution.run()
    assert result["status"] == "complete"
    assert result["processed"] == 8
    assert len(plans) == 1
    assert all(not call["include_status"] for call in runs)
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_jobs WHERE job_kind != 'intrinsic'"
            ).fetchone()[0]
            == 0
        )
    (repository / "pkg" / "util.py").write_text("CHANGED = True\n")
    RepositoryScanner(database).scan(repository)
    stale = execution._finish()
    assert stale["status"] == "waiting"
    assert "source scan changed" in stale["message"]
