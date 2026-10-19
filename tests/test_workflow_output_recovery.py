"""Resume a failed Claude map review without repeating completed model work."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

from semantic_support import _agent_dossier, _DeterministicLifecycleProvider
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.semantic import ClaudeSemanticProvider
from anaxigraph.workflow_execution import WorkflowExecution
from anaxigraph.workflow_settings import WorkflowSettings


def test_resume_review_after_removing_old_cap_keeps_completed_pass_and_descriptions(
    repository, database, monkeypatch
):
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    limited = replace(
        config,
        semantic=replace(
            config.semantic,
            max_attempts=1,
            max_output_tokens=4_000,
            max_output_tokens_on_retry=8_000,
        ),
    )
    row = database.repository(repository)
    settings = WorkflowSettings(database.path).read(row["id"], 2)["steps"]
    calls, limits = Counter(), []
    _mock_executors(monkeypatch, calls, limits)

    def run(step, policy):
        return WorkflowExecution(
            database,
            row,
            policy,
            WorkflowRequest(workflow="mapping", step=step),
            settings,
        ).run()

    for step in ("intrinsic", "context", "taxonomy_proposal"):
        assert run(step, limited)["status"] == "complete"
    assert run("taxonomy_review", limited)["status"] == "waiting"
    with database.connect() as connection:
        completed = connection.execute(
            "SELECT id, attempts, executor_model FROM semantic_jobs WHERE status='completed' ORDER BY id"
        ).fetchall()
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_jobs WHERE status='failed' AND job_kind='taxonomy_review'"
            ).fetchone()[0]
            == 1
        )
    before = dict(calls)
    resumed = run("taxonomy_review", config)
    assert resumed["status"] == "complete"
    assert resumed["processed"] == 1
    assert limits == ["4000", "8000", None]
    assert dict(calls) == before  # Only the Claude subprocess mock runs on resume.
    assert calls["taxonomy_review"] == 1  # Completed OpenAI pass is reused.
    with database.connect() as connection:
        after = {
            record["id"]: tuple(record)
            for record in connection.execute(
                "SELECT id, attempts, executor_model FROM semantic_jobs WHERE status='completed'"
            )
        }
        assert all(after[record["id"]] == tuple(record) for record in completed)
        assert (
            connection.execute("SELECT COUNT(*) FROM semantic_taxonomy_reviews").fetchone()[0] == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM semantic_jobs WHERE status='failed'"
            ).fetchone()[0]
            == 0
        )


def _mock_executors(monkeypatch, calls, limits):
    monkeypatch.delenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS", raising=False)

    class Provider(_DeterministicLifecycleProvider):
        def analyze(self, request):
            calls[request["analysis_kind"]] += 1
            return super().analyze(request)

    monkeypatch.setattr(
        "anaxigraph.semantic_runner.create_semantic_provider",
        lambda semantic: (
            ClaudeSemanticProvider(semantic) if semantic.provider == "claude" else Provider()
        ),
    )

    def run(command, **options):
        assert command[0] == "claude", "No real executor should run during this test"
        request = json.loads(options["input"].split("ANAXIGRAPH_PAYLOAD\n", 1)[1])
        limit = options["env"].get("CLAUDE_CODE_MAX_OUTPUT_TOKENS")
        limits.append(limit)
        if limit is not None:
            value = {
                "is_error": True,
                "result": f"API Error: Claude's response exceeded the {limit} output token maximum.",
            }
        else:
            assert "max_output_tokens" not in request
            value = {"structured_output": _agent_dossier(request)}
        value["usage"] = {"input_tokens": 100, "output_tokens": int(limit) if limit else 12_000}
        return SimpleNamespace(returncode=1 if limit else 0, stderr="", stdout=json.dumps(value))

    monkeypatch.setattr("anaxigraph.semantic.subprocess.run", run)
