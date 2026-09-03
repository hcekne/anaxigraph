"""Remote worker failures name their leaf cause, never the task-group header."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import anyio
import pytest

import anaxigraph.semantic_remote_errors as remote_errors
import anaxigraph.semantic_remote_worker as remote_worker
from anaxigraph.config import SemanticConfig
from anaxigraph.semantic_background_progress import PROGRESS_PATH_ENV
from anaxigraph.semantic_service import SemanticServiceTarget

_LEAF_MESSAGE = "AnaxiMCP could not claim semantic work: database is locked"
_HEADER = "unhandled errors in a TaskGroup"


def test_failure_summary_flattens_nested_exception_groups():
    grouped = ExceptionGroup("g", [ValueError("a"), ExceptionGroup("n", [OSError("b")])])

    leaves = remote_errors.leaf_exceptions(grouped)

    assert [type(leaf) for leaf in leaves] == [ValueError, OSError]
    assert remote_errors.failure_summary(grouped) == "ValueError: a; OSError: b"
    assert remote_errors.failure_summary(RuntimeError("plain")) == "RuntimeError: plain"


@pytest.mark.parametrize(
    ("environment", "expects_traceback"),
    [
        ({}, False),
        ({PROGRESS_PATH_ENV: "progress.json"}, True),
        ({remote_errors.DEBUG_ENV: "1"}, True),
        ({remote_errors.DEBUG_ENV: "false"}, False),
    ],
)
def test_log_failure_writes_traceback_only_for_detached_or_debug_runs(
    monkeypatch, capsys, environment, expects_traceback
):
    monkeypatch.delenv(PROGRESS_PATH_ENV, raising=False)
    monkeypatch.delenv(remote_errors.DEBUG_ENV, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    try:
        raise ExceptionGroup("g", [RuntimeError(_LEAF_MESSAGE)])
    except ExceptionGroup as exc:
        remote_errors.log_failure(exc)

    stderr = capsys.readouterr().err
    assert ("Traceback" in stderr) is expects_traceback
    assert (f"RuntimeError: {_LEAF_MESSAGE}" in stderr) is expects_traceback


def test_single_operational_leaf_is_raised_in_place_of_its_group(monkeypatch):
    monkeypatch.delenv(PROGRESS_PATH_ENV, raising=False)
    grouped = ExceptionGroup("outer", [ExceptionGroup("inner", [OSError(_LEAF_MESSAGE)])])

    with pytest.raises(OSError) as failure:
        remote_errors.raise_remote_failure(grouped)

    assert str(failure.value) == _LEAF_MESSAGE
    assert failure.value.__cause__ is grouped


def test_plain_operational_errors_are_reraised_unchanged(monkeypatch):
    monkeypatch.delenv(PROGRESS_PATH_ENV, raising=False)
    error = ValueError("Semantic job limit must be at least one")

    with pytest.raises(ValueError) as failure:
        remote_errors.raise_remote_failure(error)

    assert failure.value is error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            ExceptionGroup("g", [ValueError("a"), OSError("b")]),
            "Remote semantic execution failed: ValueError: a; OSError: b",
        ),
        (KeyError("job"), "Remote semantic execution failed: KeyError: 'job'"),
        (
            ExceptionGroup("g", [RuntimeError("")]),
            "Remote semantic execution failed: RuntimeError: ",
        ),
    ],
)
def test_other_failures_are_summarised_by_their_leaves(monkeypatch, error, expected):
    monkeypatch.delenv(PROGRESS_PATH_ENV, raising=False)

    with pytest.raises(RuntimeError) as failure:
        remote_errors.raise_remote_failure(error)

    assert str(failure.value) == expected
    assert failure.value.__cause__ is error


def test_remote_execution_reports_the_task_group_leaf_not_the_header(tmp_path, monkeypatch, capsys):
    progress_path = tmp_path / "progress.json"
    monkeypatch.setenv(PROGRESS_PATH_ENV, str(progress_path))

    @asynccontextmanager
    async def failing_client(*_args, **_kwargs):
        async with anyio.create_task_group():
            async with anyio.create_task_group():
                raise RuntimeError(_LEAF_MESSAGE)
        yield  # the nested task groups above always raise before this point

    monkeypatch.setattr(remote_worker, "streamable_http_client", failing_client)

    with pytest.raises(RuntimeError) as failure:
        remote_worker.execute_remote_semantics(
            SemanticServiceTarget("http://127.0.0.1:8765", 1, "AnaxiGraph", "/anaxigraph"),
            SemanticConfig(provider="agent"),
            SemanticConfig(provider="codex"),
            limit=1,
            until_complete=False,
            retry_failed=False,
        )

    assert str(failure.value) == _LEAF_MESSAGE
    assert _HEADER not in str(failure.value)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["stage"] == "failed"
    assert progress["last_error"] == f"RuntimeError: {_LEAF_MESSAGE}"
    stderr = capsys.readouterr().err
    assert "Traceback" in stderr
    assert f"RuntimeError: {_LEAF_MESSAGE}" in stderr
