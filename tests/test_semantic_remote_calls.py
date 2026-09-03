"""Shared AnaxiMCP call helpers: result parsing and bounded lock retries."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import anaxigraph.semantic_remote_calls as remote_calls


def _response(*, error=None, structured=None, text=None):
    content = [SimpleNamespace(text=error or text)] if (error or text) else []
    return SimpleNamespace(isError=error is not None, content=content, structuredContent=structured)


class _Session:
    def __init__(self, *responses):
        self._responses = iter(responses)
        self.calls = []

    async def call_tool(self, name, *, arguments, read_timeout_seconds):
        self.calls.append((name, arguments))
        return next(self._responses)


def test_tool_value_reads_structured_or_text_results():
    structured = remote_calls.tool_value(_response(structured={"status": "work"}), "claim")
    parsed = remote_calls.tool_value(_response(text=json.dumps({"status": "released"})), "release")

    assert structured == {"status": "work"}
    assert parsed == {"status": "released"}


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (_response(error="lease expired"), "could not claim semantic work: lease expired"),
        (_response(text=json.dumps([1, 2])), "no structured result while trying to claim"),
        (_response(), "no structured result"),
    ],
)
def test_tool_value_raises_error_text(response, match):
    with pytest.raises(RuntimeError, match=match):
        remote_calls.tool_value(response, "claim semantic work")


@pytest.mark.anyio
async def test_lock_retries_are_bounded_and_end_with_the_lock_error(monkeypatch):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(remote_calls.asyncio, "sleep", sleep)
    session = _Session(*(_response(error="database is locked") for _ in range(3)))

    with pytest.raises(RuntimeError, match="submit semantic work: database is locked"):
        await remote_calls.call_tool_retrying_locks(
            session,
            "ANAXIGRAPH_SEMANTIC_SUBMIT",
            {"job_id": 7},
            action="submit semantic work",
            attempts=3,
        )

    assert [name for name, _arguments in session.calls] == ["ANAXIGRAPH_SEMANTIC_SUBMIT"] * 3
    assert sleeps == [1, 2]
