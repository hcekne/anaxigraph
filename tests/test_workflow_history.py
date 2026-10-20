"""Source updates retain visible work and resume a proposal instead of rebuilding it."""

from collections import Counter
from dataclasses import replace
from subprocess import TimeoutExpired

import pytest
from semantic_support import _DeterministicLifecycleProvider
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.persistence.workflow_read import workflow_coverage
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_contract import SemanticAnalysisError
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_execution import WorkflowExecution
from anaxigraph.workflow_settings import WorkflowSettings


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("The earlier review failed", "SemanticAnalysisError: The earlier review failed"),
        (
            f"Claude semantic run failed: {TimeoutExpired(['claude', '--json-schema', 'schema' * 400], 300)}",
            "Claude timed out after 300 seconds",
        ),
    ],
    ids=["ordinary-failure", "legacy-timeout"],
)
def test_changed_source_keeps_saved_work_visible_and_reuses_an_unfinished_proposal(
    repository, database, monkeypatch, failure, message
):
    calls = Counter()
    fail_review = True

    class Provider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            calls[request["analysis_kind"]] += 1
            if (
                fail_review
                and request["analysis_kind"] == "taxonomy_review"
                and request["review_pass"] == 2
            ):
                raise SemanticAnalysisError(failure)
            return super().analyze(request)

    prepare(repository, database, monkeypatch, Provider())
    config = load_config(repository)
    config = replace(config, semantic=replace(config.semantic, max_attempts=1))
    row = database.repository(repository)
    settings = WorkflowSettings(database.path).read(row["id"], 2)["steps"]

    def run(step):
        return WorkflowExecution(
            database, row, config, WorkflowRequest(workflow="mapping", step=step), settings
        ).run()

    for step in ("intrinsic", "context", "taxonomy_proposal"):
        assert run(step)["status"] == "complete"
    assert run("taxonomy_review")["status"] == "waiting"
    before = database.latest_snapshot(row["id"])["id"]
    with database.connect() as connection:
        visible = workflow_coverage(connection, before)["failures"][0]["error"]
        assert visible.startswith(message)
        assert len(visible) < 1000
    source = repository / "pkg" / "util.py"
    source.write_text(source.read_text() + "\nLOCAL_CHANGE = 1\n")
    (repository / "pkg" / "new.py").write_text("def extra():\n    return 1\n")
    scanner = RepositoryScanner(database)
    scanner.scan(repository)
    with database.connect() as connection:
        pending = workflow_coverage(connection, database.latest_snapshot(row["id"])["id"])[
            "history"
        ]
        assert pending["modules"]["reuse_pending"]
        assert pending["modules"]["saved"] == {"intrinsic": 8, "context": 8}
    engine = SemanticEngine(database)
    engine.plan(row["id"], repository, config)

    def coverage():
        with database.connect() as connection:
            return workflow_coverage(connection, database.latest_snapshot(row["id"])["id"])

    history = coverage()["history"]
    assert history["taxonomy"]["snapshot_id"] == before
    assert history["taxonomy"]["reviews"] == 1
    assert history["taxonomy"]["failed_reviews"] == 1
    assert history["taxonomy"]["error"].startswith(message)
    assert len(history["taxonomy"]["error"]) < 1000
    assert history["modules"]["intrinsic"]["refresh"] == 1
    assert history["modules"]["intrinsic"]["new"] == 1
    assert history["modules"]["context"]["refresh"] >= 1
    assert any(
        item["path"] == "pkg/new.py" and item["intrinsic"] == "new"
        for item in history["modules"]["affected"]
    )
    # Another scan before the update must not hide the original proposal or descriptions.
    source.write_text(source.read_text() + "\nLOCAL_CHANGE = 2\n")
    scanner.scan(repository)
    engine.plan(row["id"], repository, config)
    assert coverage()["history"]["taxonomy"] == history["taxonomy"]
    assert coverage()["history"]["modules"]["intrinsic"]["refresh"] == 1
    for step in ("intrinsic", "context", "taxonomy_proposal"):
        assert run(step)["status"] == "complete"
    assert calls["taxonomy_proposal"] == 1
    current_id = database.latest_snapshot(row["id"])["id"]
    with database.connect() as connection:
        current = connection.execute(
            "SELECT * FROM semantic_taxonomies WHERE snapshot_id = ?", (current_id,)
        ).fetchone()
        assert current["source"] == "reused_taxonomy_proposal"
        assert current["review_passes"] == 0
        assert current["final_document_id"] is None
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_taxonomy_reviews WHERE taxonomy_id = ?",
                (current["id"],),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_taxonomy_reviews WHERE taxonomy_id = ?",
                (history["taxonomy"]["id"],),
            ).fetchone()[0]
            == 1
        )
    fail_review = False
    assert run("taxonomy_review")["status"] == "complete"
    assert calls["taxonomy_proposal"] == 1
    assert coverage()["history"]["modules"]["intrinsic"]["refresh"] == 0
