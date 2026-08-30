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
