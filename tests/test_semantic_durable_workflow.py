"""Cheap orchestration: reuse active workers, wait out prepare, and read bounded progress."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import anaxigraph.cli_semantic_commands as commands
import anaxigraph.semantic_mcp as semantic_mcp
import anaxigraph.semantic_remote_recovery as recovery
import anaxigraph.semantic_service as service
from anaxigraph.mcp_server import create_anaxi_mcp_server
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_reporting import compact_semantic_status


def _target():
    return service.SemanticServiceTarget("http://127.0.0.1:8765", 7, "Example", "/repo")


def _args(**changes):
    values = dict(executor="claude", force=False, retry_failed=False, plan_only=False)
    return SimpleNamespace(**{**values, **changes})


@pytest.mark.parametrize(
    "error",
    [
        "HTTP 409: semantic_prepare is already running",
        "HTTP 429: semantic_prepare is rate limited",
    ],
)
def test_prepare_contention_returns_a_wait_state_without_rapid_retries(monkeypatch, error):
    requests = []

    def request(url, **options):
        requests.append(url)
        raise ValueError(error)

    monkeypatch.setattr(service, "_request_json", request)
    result = service.prepare_semantic_service(_target(), force=False, retry_failed=False)
    assert result == {"status": "preparing", "retry_after_seconds": 5}
    assert len(requests) == 1


def test_unrelated_prepare_conflicts_remain_visible(monkeypatch):
    monkeypatch.setattr(
        service,
        "_request_json",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("HTTP 409: different conflict")),
    )
    with pytest.raises(ValueError, match="different conflict"):
        service.prepare_semantic_service(_target(), force=False, retry_failed=False)


def test_starting_an_executor_joins_thirty_two_active_jobs_without_preparing(monkeypatch):
    status = {"map_status": {"state": "current"}, "jobs": {"running": 32, "pending": 1_000}}
    monkeypatch.setattr(commands, "service_semantic_status", lambda *_a: status)
    monkeypatch.setattr(
        commands, "prepare_semantic_service", lambda *a, **k: pytest.fail("duplicate preparation")
    )
    result = commands._prepare_service(_args(), _target())
    assert result == {"status": "joined", "semantic": status}


def test_startup_waits_for_active_preparation_without_reposting_or_relaunching(monkeypatch):
    statuses = iter([{"jobs": {}}, {"preparing": True}, {"preparing": False}])
    preparations, sleeps = [], []

    def prepare(*_a, **_k):
        preparations.append(1)
        return {"status": "preparing" if len(preparations) == 1 else "prepared"}

    monkeypatch.setattr(commands, "service_semantic_status", lambda *_a: next(statuses))
    monkeypatch.setattr(commands, "prepare_semantic_service", prepare)
    monkeypatch.setattr(commands.time, "sleep", sleeps.append)
    assert commands._prepare_service(_args(), _target())["status"] == "prepared"
    assert len(preparations) == 2
    assert sleeps == [5, 10]


def test_a_stuck_preparation_has_a_bounded_wait_and_clear_error(monkeypatch):
    times = iter([0, 601])
    monkeypatch.setattr(commands.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(commands, "service_semantic_status", lambda *_a: {"jobs": {}})
    monkeypatch.setattr(
        commands, "prepare_semantic_service", lambda *a, **k: {"status": "preparing"}
    )
    with pytest.raises(RuntimeError, match="stayed busy for 10 minutes"):
        commands._prepare_service(_args(), _target())


def test_existing_jobs_do_not_bypass_a_required_structural_scan(monkeypatch):
    monkeypatch.setattr(
        commands,
        "service_semantic_status",
        lambda *_a: {"map_status": {"state": "stale"}, "jobs": {"running": 32}},
    )
    monkeypatch.setattr(
        commands, "prepare_semantic_service", lambda *a, **k: {"status": "scan_required"}
    )
    assert commands._prepare_service(_args(), _target())["status"] == "scan_required"


@pytest.mark.anyio
async def test_busy_prepare_does_not_consume_the_stranded_queue_repair(monkeypatch):
    instance = recovery.IdleRecovery(_target(), retry_failed=False)
    results = iter([{"status": "preparing"}, {"status": "prepared", "enqueued": 1}])
    monkeypatch.setattr(recovery, "prepare_semantic_service", lambda *a, **k: next(results))
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(recovery.asyncio, "sleep", sleep)
    status = {"snapshot_id": 2, "pending": 1, "jobs": {}}
    for _ in range(3):
        assert await instance.recover("waiting", status) is None
    assert instance.refreshed == set()
    for _ in range(2):
        assert await instance.recover("waiting", status) is None
    assert (await instance.recover("waiting", status))["enqueued"] == 1
    assert sleeps == [5]


@pytest.mark.anyio
async def test_mcp_progress_and_schema_default_to_small_responses(
    repository, database, monkeypatch
):
    scan = RepositoryScanner(database).scan(repository)
    full = {
        "snapshot_id": scan.snapshot_id,
        "current": 2_700,
        "semantically_ready": False,
        "jobs": {"running": 32, "pending": 1_000, "failed": 0},
        "usage": {"output_tokens": 200_000},
        "architecture_charter": {"value": {"summary": "Long saved description. " * 5_000}},
    }
    monkeypatch.setattr(semantic_mcp, "current_semantic_status", lambda *a: dict(full))
    server = create_anaxi_mcp_server(
        database=database, repository=repository, config_path=None, profile="executor"
    )
    compact = (await server.call_tool("ANAXIGRAPH_SEMANTIC_STATUS", {}))[1]
    detailed = (await server.call_tool("ANAXIGRAPH_SEMANTIC_STATUS", {"details": True}))[1]
    assert compact["jobs"]["running"] == 32
    assert compact["poll_after_seconds"] == 300
    assert "architecture_charter" not in compact
    assert len(json.dumps(compact)) < 4_000
    assert detailed["architecture_charter"] == full["architecture_charter"]
    schema = (await server.call_tool("ANAXIGRAPH_SEMANTIC_SCHEMA", {}))[1]
    all_schemas = (await server.call_tool("ANAXIGRAPH_SEMANTIC_SCHEMA", {"artifact": "all"}))[1]
    assert len(schema["dossier_schema"]["required"]) == 5
    assert "review_dossier_schema" not in schema
    assert len(json.dumps(schema)) < len(json.dumps(all_schemas)) / 10
    assert "no more often" in server.instructions
    assert "30+ concurrent" in server.instructions


def test_compact_status_preserves_run_identity_and_global_concurrency():
    status = {
        "semantically_ready": False,
        "jobs": {"running_live": 32},
        "semantic_policy": {"max_parallel_jobs": 48},
        "execution_runs": [
            {
                "run_id": "one-run",
                "executor": "claude",
                "active": True,
                "status": "running",
                "last_error": None,
            }
        ],
    }
    compact = compact_semantic_status(status)
    assert compact_semantic_status(compact) == compact
    assert compact["parallel_jobs_limit"] == 48
    assert compact["execution_runs"][0]["run_id"] == "one-run"


def test_cli_compact_progress_selects_small_service_reply_and_keeps_host_run(tmp_path, monkeypatch):
    requests = []
    monkeypatch.setattr(commands, "discover_semantic_service", lambda *a, **k: _target())
    monkeypatch.setattr(
        service,
        "_request_json",
        lambda url, **kwargs: (
            requests.append(url)
            or {"jobs": {"running": 32}, "semantic_policy": {"max_parallel_jobs": 48}}
        ),
    )
    monkeypatch.setattr(
        commands,
        "semantic_background_runs",
        lambda _: [{"run_id": "existing-run", "active": True, "executor": "claude"}],
    )
    result = commands._semantic_status(
        SimpleNamespace(repository=tmp_path, db=None, service_url=_target().base_url, compact=True)
    )
    assert requests == ["http://127.0.0.1:8765/api/semantic?repository_id=7&compact=true"]
    assert result["index"]["authority"] == "service"
    assert result["execution_runs"][0]["run_id"] == "existing-run"
    assert result["jobs"]["running"] == 32
    assert result["parallel_jobs_limit"] == 48
