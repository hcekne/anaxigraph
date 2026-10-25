"""The transports dispatch consistently and expose usable packaged assets."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anaxigraph.interfaces.cli import dispatch, parser
from anaxigraph.interfaces.http import create_app
from anaxigraph.interfaces.mcp import create_mcp


class RecordingApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def __getattr__(self, name: str):
        def operation(*args):
            self.calls.append((name, args))
            return {"operation": name, "arguments": list(args)}

        return operation


@pytest.mark.parametrize("position", ("before", "after"))
def test_checkout_options_work_before_or_after_command(position: str, tmp_path: Path) -> None:
    location = ["--repo", str(tmp_path), "--database", str(tmp_path / "map.sqlite")]
    args = parser().parse_args(
        location + ["status"] if position == "before" else ["status"] + location
    )
    assert args.repo == tmp_path
    assert args.database == tmp_path / "map.sqlite"


@pytest.mark.parametrize(
    ("arguments", "operation", "expected"),
    [
        (["scan"], "scan", ()),
        (["status"], "status", ()),
        (["modules", "--sort", "loc", "--descending"], "modules", ("loc", True, 50, 0)),
        (["inspect", "module:x.py", "--limit", "7"], "inspect", ("module:x.py", 7)),
        (["prepare", "Add export"], "prepare_change", ("Add export", 12)),
        (
            ["assess", "Add export", "--files", "export.py"],
            "assess_plan",
            ("Add export", ["export.py"]),
        ),
        (["validate"], "validate_change", (None,)),
        (["request", "fresh-eyes"], "analysis_request", ("fresh-eyes", None)),
        (["reviews", "--kind", "patterns"], "reviews", ("patterns",)),
    ],
)
def test_cli_uses_application_contract(arguments, operation, expected) -> None:
    application = RecordingApplication()
    result = dispatch(application, parser().parse_args(arguments))
    assert application.calls == [(operation, expected)]
    assert result["operation"] == operation


def test_cli_reads_submission_and_receipts_without_reinterpreting_them(tmp_path: Path) -> None:
    application = RecordingApplication()
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps({"alternatives": [1, 2, 3]}))
    dispatch(application, parser().parse_args(["submit", "request-1", str(result_path)]))
    assert application.calls[-1] == ("submit_analysis", ("request-1", {"alternatives": [1, 2, 3]}))
    receipts_path = tmp_path / "checks.json"
    receipts = [{"command": "pytest", "exit_status": 0, "fingerprint": "current"}]
    receipts_path.write_text(json.dumps(receipts))
    dispatch(application, parser().parse_args(["validate", "--receipts", str(receipts_path)]))
    assert application.calls[-1] == ("validate_change", (receipts,))
    with pytest.raises(ValueError, match="JSON list"):
        dispatch(application, parser().parse_args(["validate", "--receipts", str(result_path)]))


def test_dashboard_assets_and_bounded_http_dispatch() -> None:
    application = RecordingApplication()
    client = TestClient(create_app(application))
    assert "Module map" in client.get("/").text
    assert "drawGraph" in client.get("/assets/app.js").text
    assert client.get("/assets/styles.css").status_code == 200
    assert client.get("/api/modules?sort=functions&descending=true&limit=8&offset=3").json() == {
        "operation": "modules",
        "arguments": ["functions", True, 8, 3],
    }
    assert client.get("/api/modules?limit=10000").status_code == 422
    assert client.get("/api/entity?entity_id=module:x.py&limit=4").json()["arguments"] == [
        "module:x.py",
        4,
    ]
    assert client.get("/api/status").json()["operation"] == "status"
    assert client.get("/api/reviews?kind=patterns").json()["arguments"] == ["patterns"]


@pytest.mark.parametrize(
    ("path", "body", "operation", "expected"),
    [
        ("scan", {}, "scan", []),
        ("prepare", {"task": "Add export"}, "prepare_change", ["Add export", 12]),
        (
            "assess",
            {"task": "Add export", "files": ["export.py"]},
            "assess_plan",
            ["Add export", ["export.py"]],
        ),
        ("validate", {}, "validate_change", [None]),
        (
            "analysis/request",
            {"kind": "patterns", "scope": ["module:x.py"]},
            "analysis_request",
            ["patterns", ["module:x.py"]],
        ),
        (
            "analysis/submit",
            {"request_id": "r", "result": {"done": True}},
            "submit_analysis",
            ["r", {"done": True}],
        ),
    ],
)
def test_http_actions_delegate(path, body, operation, expected) -> None:
    client = TestClient(create_app(RecordingApplication()))
    assert client.post(f"/api/{path}", json=body).json() == {
        "operation": operation,
        "arguments": expected,
    }


def test_http_reports_stale_analysis_as_a_client_error() -> None:
    class StaleApplication:
        def submit_analysis(self, *_args):
            raise ValueError("This request belongs to an older source fingerprint")

    client = TestClient(create_app(StaleApplication()))
    response = client.post("/api/analysis/submit", json={"request_id": "r", "result": {}})
    assert response.status_code == 400
    assert "older source fingerprint" in response.json()["detail"]
    assert client.post("/api/analysis/request", json={"kind": "imaginary"}).status_code == 422


def test_mcp_tools_dispatch_the_same_arguments() -> None:
    application = RecordingApplication()
    server = create_mcp(application)

    async def exercise() -> None:
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {
            "status",
            "scan",
            "modules",
            "inspect",
            "prepare_change",
            "assess_plan",
            "validate_change",
            "analysis_request",
            "submit_analysis",
            "reviews",
        }
        await server.call_tool("prepare_change", {"task": "Add export", "limit": 3})
        await server.call_tool("analysis_request", {"kind": "fresh-eyes"})
        await server.call_tool(
            "submit_analysis", {"request_id": "r", "result": {"alternatives": []}}
        )
        await server.call_tool("modules", {"sort": "functions", "limit": 7, "offset": 2})
        await server.call_tool("reviews", {"kind": "fresh-eyes"})

    asyncio.run(exercise())
    assert application.calls == [
        ("prepare_change", ("Add export", 3)),
        ("analysis_request", ("fresh-eyes", None)),
        ("submit_analysis", ("r", {"alternatives": []})),
        ("modules", ("functions", False, 7, 2)),
        ("reviews", ("fresh-eyes",)),
    ]


def test_http_real_application_keeps_snapshot_and_analysis_evidence_honest(tmp_path: Path) -> None:
    from anaxigraph.application import Application

    (tmp_path / "billing.py").write_text("def list_invoices():\n    return []\n")
    export = tmp_path / "export.py"
    export.write_text(
        "from billing import list_invoices\n\ndef export_invoices():\n    return list_invoices()\n"
    )
    client = TestClient(create_app(Application(tmp_path)))
    assert client.get("/api/status").json()["snapshot"] is None
    mapped = client.post("/api/scan").json()
    assert mapped["mapped_locally"] is True
    assert mapped["modules"] == 2
    modules = client.get("/api/modules?sort=loc&descending=true").json()
    entity = modules["items"][0]
    detail = client.get("/api/entity", params={"entity_id": entity["id"]}).json()
    assert detail["entity"]["id"] == entity["id"]
    assert detail["snapshot_id"] == mapped["snapshot"]["id"]
    brief = client.post("/api/prepare", json={"task": "export invoices"}).json()
    assert any(owner["path"] == "export.py" for owner in brief["likely_owners"])
    requested = client.post(
        "/api/analysis/request", json={"kind": "annotate", "scope": ["billing.py"]}
    )
    assert requested.status_code == 200
    packet = requested.json()
    assert packet["response_schema"]
    rejected = client.post(
        "/api/analysis/submit", json={"request_id": packet["request_id"], "result": {}}
    )
    assert rejected.status_code == 400
    assert client.get("/api/status").json()["annotations"]["current"] == 0
    export.write_text(export.read_text() + "\n# A changed candidate\n")
    client.post("/api/scan").raise_for_status()
    comparison = client.post("/api/validate", json={}).json()
    assert comparison["changed_paths"] == ["export.py"]
    assert comparison["behavioral_status"] == "unchecked"


def test_full_saved_review_is_an_explicit_expansion_and_keeps_staleness(tmp_path: Path) -> None:
    from anaxigraph.application import Application

    source = tmp_path / "service.py"
    source.write_text("def run():\n    return True\n")
    application = Application(tmp_path)
    snapshot = application.scan()["snapshot"]["id"]
    result = {
        "producer": "synthetic-interface-fixture",
        "alternatives": [
            {
                "name": name,
                "design": f"Deliver the behavior through {name}.",
                "requirements": ["R1"],
                "pros": ["Clear ownership"],
                "cons": ["Validate this boundary"],
                "diagram": "flowchart TB\n    User --> Capability",
            }
            for name in ("Local service", "Queued execution", "Functional operations")
        ],
    }
    application.store.save_review(
        str(tmp_path),
        snapshot,
        "fixture-review",
        "fresh-eyes",
        {"basis": "agent-reported-proposal", "result": result},
    )
    client = TestClient(create_app(application))
    listed = client.get("/api/reviews").json()["items"][0]
    assert listed["producer"] == "synthetic-interface-fixture"
    assert "result" not in listed
    expanded = client.get("/api/entity", params={"entity_id": "review:fixture-review"}).json()
    record = expanded["entity"]["data"]
    assert record["result"]["result"] == result
    assert record["status"] == "unknown"
    assert record["freshness_reason"] == "Analysis input identity not recorded"
    source.write_text(source.read_text() + "\n# Candidate changed\n")
    client.post("/api/scan").raise_for_status()
    stale = client.get("/api/entity", params={"entity_id": "review:fixture-review"}).json()
    assert stale["entity"]["data"]["status"] == "stale"
    assert stale["entity"]["data"]["snapshot_id"] == snapshot
    assert len(stale["entity"]["data"]["result"]["result"]["alternatives"]) == 3
