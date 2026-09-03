from __future__ import annotations

import json

import pytest

import anaxigraph.semantic_service as semantic_service
from anaxigraph.semantic_service import SemanticServiceTarget


def _target() -> SemanticServiceTarget:
    return SemanticServiceTarget("http://127.0.0.1:9999", 7, "Fixture", "/repo")


def test_service_agent_query_helpers_send_repository_identity(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return {"status": "ok"}

    monkeypatch.setattr(semantic_service, "_request_json", request)

    assert semantic_service.service_impact(_target(), requested_target="src/app.py") == {
        "status": "ok"
    }
    assert calls == [
        (
            "http://127.0.0.1:9999/api/impact",
            {
                "method": "POST",
                "timeout": 30,
                "body": {"target": "src/app.py", "repository_id": 7},
            },
        ),
    ]


def test_service_fresh_eyes_restart_posts_an_explicit_new_generation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        semantic_service,
        "_request_json",
        lambda url, **kwargs: calls.append((url, kwargs)) or {"status": "restarted"},
    )

    assert semantic_service.service_fresh_eyes_review(_target(), restart=True) == {
        "status": "restarted"
    }
    assert calls[0][1]["body"] == {
        "proposal_count": 2,
        "retry_failed": False,
        "restart": True,
        "repository_id": 7,
    }
    assert calls[0][1]["timeout"] == 120


def test_service_fresh_eyes_start_waits_longer_than_the_index_busy_window(database, monkeypatch):
    calls = []
    monkeypatch.setattr(
        semantic_service,
        "_request_json",
        lambda url, **kwargs: calls.append((url, kwargs)) or {"status": "ok"},
    )
    with database.connect() as connection:
        busy_seconds = connection.execute("PRAGMA busy_timeout").fetchone()[0] / 1_000

    semantic_service.service_fresh_eyes_review(_target(), start=True)
    semantic_service.service_fresh_eyes_review(_target())
    semantic_service.service_fresh_eyes_review(_target(), timeout=5)

    assert calls[0][1]["method"] == "POST"
    assert calls[0][1]["timeout"] == semantic_service.FRESH_EYES_START_TIMEOUT_SECONDS
    assert calls[0][1]["timeout"] > busy_seconds
    assert calls[1][1] == {"timeout": 30}
    assert calls[2][1] == {"timeout": 5}


def test_service_agent_queries_reject_non_object_results(monkeypatch):
    monkeypatch.setattr(semantic_service, "_request_json", lambda *_args, **_kwargs: [])

    with pytest.raises(ValueError, match="coding-context"):
        semantic_service.service_impact(_target(), requested_target="src/app.py")


def test_json_request_encodes_post_bodies_and_empty_posts(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"ok": True}).encode()

    def open_request(request, *, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(semantic_service.urllib.request, "urlopen", open_request)

    assert semantic_service._request_json(
        "http://test/body", method="POST", body={"repository_id": 7}
    ) == {"ok": True}
    assert semantic_service._request_json("http://test/empty", method="POST") == {"ok": True}
    assert requests[0][0].data == b'{"repository_id": 7}'
    assert requests[0][0].headers["Content-type"] == "application/json"
    assert requests[1][0].data == b""
    assert all(timeout == 10 for _, timeout in requests)
