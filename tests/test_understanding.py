from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from anaxigraph.agent import agent_scope
from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_graph import _intent_fingerprint
from anaxigraph.understanding import SemanticEngine


def _semantic_config(repository: Path, provider: Path, log: Path, **overrides) -> None:
    config_path = repository / ".anaxigraph.yml"
    value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    value["semantic"] = {
        "enabled": True,
        "provider": "command",
        "command": [sys.executable, str(provider), str(log)],
        "prompt_version": "test-v1",
        "max_jobs_per_run": 100,
        "max_parallel_jobs": 2,
        "max_attempts": 1,
        **overrides,
    }
    config_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _fake_provider(tmp_path: Path, *, fail_path: str = "") -> Path:
    provider = tmp_path / "semantic_provider.py"
    provider.write_text(
        """from __future__ import annotations
import json
import sys

request = json.load(sys.stdin)
path = str(request.get("path") or request.get("scope_key") or "scope")
kind = str(request.get("analysis_kind") or "unknown")
with open(sys.argv[1], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"path": path, "kind": kind}) + "\\n")
if FAIL_PATH and path == FAIL_PATH and kind == "intrinsic":
    raise SystemExit(7)
value = {
    "summary": f"{kind} understanding for {path}",
    "detailed_summary": f"Evidence-grounded {kind} dossier for {path}.",
    "responsibilities": [f"Own {path}"],
    "inputs": [],
    "outputs": [],
    "side_effects": [],
    "public_contracts": [],
    "invariants": [],
    "architecture_role": "test role",
    "domain_concepts": [],
    "collaborators": [],
    "overlaps": [],
    "extension_points": [],
    "similar_modules": [],
    "pattern_opportunities": [] if kind == "intrinsic" else [{
        "name": "Repository-local adapter",
        "scope": "module",
        "score": 84,
        "confidence": 0.8,
        "rationale": "The supplied neighboring dossiers share a stable boundary.",
        "evidence": [f"{path}:1"],
        "counter_evidence": [],
        "migration_cost": "low",
        "preconditions": ["Verify the shared contract"],
    }],
    "consolidation_assessment": {
        "recommendation": "insufficient_evidence",
        "score": 0,
        "rationale": "",
        "candidates": [],
        "evidence": [],
        "counter_evidence": [],
    },
    "dead_code_candidates": [],
    "placement_guidance": "",
    "testing_guidance": [],
    "change_summary": "",
    "risks": [],
    "evidence": [f"{path}:1"],
    "confidence": 0.9,
}
json.dump({"dossier": value, "usage": {"input_tokens": 100, "output_tokens": 40}}, sys.stdout)
""".replace("FAIL_PATH", repr(fail_path)),
        encoding="utf-8",
    )
    return provider


def _calls(log: Path) -> list[dict[str, str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _agent_dossier(request: dict) -> dict:
    scope = str(request.get("path") or request.get("scope_key") or "repository")
    kind = str(request.get("analysis_kind") or "semantic")
    return {
        "summary": f"{kind} understanding for {scope}",
        "detailed_summary": f"Evidence-grounded {kind} dossier for {scope}.",
        "responsibilities": [f"Own {scope}"],
        "inputs": [],
        "outputs": [],
        "side_effects": [],
        "public_contracts": [],
        "invariants": [],
        "architecture_role": "agent-funded test role",
        "domain_concepts": [],
        "collaborators": [],
        "overlaps": [],
        "extension_points": [],
        "similar_modules": [],
        "pattern_opportunities": [],
        "consolidation_assessment": {
            "recommendation": "insufficient_evidence",
            "score": 0,
            "rationale": "No consolidation claim without contextual evidence.",
            "candidates": [],
            "evidence": [],
            "counter_evidence": [],
        },
        "dead_code_candidates": [],
        "placement_guidance": "",
        "testing_guidance": [],
        "change_summary": "",
        "risks": [],
        "evidence": [scope],
        "confidence": 0.9,
    }


def test_full_semantic_bootstrap_is_resumable_and_incremental(repository, database, tmp_path):
    log = tmp_path / "semantic.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)

    stats = RepositoryScanner(database).scan(repository)
    queued = SemanticEngine(database).status(stats.repository_id, config.semantic)
    assert queued["total_modules"] == 9
    assert queued["pending"] == 9
    assert queued["current"] == 0

    result = SemanticEngine(database).bootstrap(stats.repository_id, repository, config)
    status = result["semantic"]
    assert status["semantically_ready"] is True
    assert status["baseline_complete"] is True
    assert status["current"] == status["eligible_modules"] == 9
    assert status["repository_dossier"]["value"]["summary"]
    assert {"intrinsic", "context", "synthesis"} <= {item["kind"] for item in _calls(log)}
    modules = database.modules(stats.repository_id)
    core_module = next(item for item in modules if item["path"] == "pkg/core.py")
    assert core_module["summary_source"] == "command contextual interpretation"
    scope = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change Calculator behavior",
        branch=None,
        config=config,
    )
    assert scope["primary_files"][0]["semantic"]["status"] == "current"
    assert scope["primary_files"][0]["semantic"]["pattern_opportunities"][0]["score"] == 84

    first_call_count = len(_calls(log))
    unchanged = SemanticEngine(database).bootstrap(stats.repository_id, repository, config)
    assert unchanged["processed"] == 0
    assert len(_calls(log)) == first_call_count

    core = repository / "pkg" / "core.py"
    core.write_text(
        core.read_text(encoding="utf-8").replace(
            "return double(value)", "return double(value) + 1"
        ),
        encoding="utf-8",
    )
    changed = RepositoryScanner(database).scan(repository, run_type="update")
    refreshed = SemanticEngine(database).bootstrap(changed.repository_id, repository, config)
    assert refreshed["processed"] == 1
    new_calls = _calls(log)[first_call_count:]
    assert new_calls == [{"path": "pkg/core.py", "kind": "intrinsic"}]
    dossier = SemanticEngine(database).dossier(changed.repository_id, "pkg/core.py")
    assert dossier["status"] == "current"
    assert dossier["intrinsic"]["input_tokens"] == 100
    assert dossier["intrinsic"]["previous_document_id"] is not None


def test_semantic_failure_and_exclusion_are_visible_terminal_states(repository, database, tmp_path):
    log = tmp_path / "semantic-failure.log"
    provider = _fake_provider(tmp_path, fail_path="pkg/core.py")
    _semantic_config(repository, provider, log, exclude=["docs/**"])
    config = load_config(repository)

    stats = RepositoryScanner(database).scan(repository)
    result = SemanticEngine(database).bootstrap(stats.repository_id, repository, config)
    status = result["semantic"]

    assert status["baseline_complete"] is True
    assert status["semantically_ready"] is False
    assert status["failed"] == 1
    assert status["excluded"] == 1
    assert status["pending"] == 0
    core = SemanticEngine(database).dossier(stats.repository_id, "pkg/core.py")
    documentation = SemanticEngine(database).dossier(stats.repository_id, "docs/architecture.md")
    assert core["status"] == "failed_intrinsic"
    assert "exited with 7" in core["reason"]
    assert documentation["status"] == "excluded"


def test_expired_worker_lease_is_requeued_and_resumed(repository, database, tmp_path):
    log = tmp_path / "semantic-recovery.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log, timeout_seconds=1)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    plan = engine.plan(stats.repository_id, repository, config)
    assert plan.active_jobs

    with database.transaction() as connection:
        job = connection.execute(
            "SELECT id FROM semantic_jobs ORDER BY priority DESC, id LIMIT 1"
        ).fetchone()
        connection.execute(
            """
            UPDATE semantic_jobs SET status = 'running', attempts = 1,
                worker_id = 'interrupted-worker', started_at = '2000-01-01T00:00:00+00:00',
                lease_expires_at = '2000-01-01T00:01:00+00:00'
            WHERE id = ?
            """,
            (job["id"],),
        )

    recovered = engine.plan(stats.repository_id, repository, config)
    assert recovered.active_jobs == plan.active_jobs
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, worker_id, lease_expires_at, error FROM semantic_jobs WHERE id = ?",
            (job["id"],),
        ).fetchone()
    assert row["status"] == "retry"
    assert row["worker_id"] is None
    assert row["lease_expires_at"] is None
    assert "lease expired" in row["error"]
    assert (
        engine.bootstrap(stats.repository_id, repository, config)["semantic"]["semantically_ready"]
        is True
    )


def test_daily_budget_pauses_before_claiming_an_estimated_job(repository, database, tmp_path):
    log = tmp_path / "semantic-budget.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(
        repository,
        provider,
        log,
        daily_budget_usd=0.000001,
        input_cost_per_million=10.0,
        output_cost_per_million=10.0,
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    result = SemanticEngine(database).bootstrap(stats.repository_id, repository, config)

    assert result["processed"] == 0
    assert result["semantic"]["pending"] == 9
    assert result["semantic"]["budget"]["paused"] is True
    assert _calls(log) == []


def test_parallel_claims_reserve_budget_before_provider_usage_arrives(
    repository, database, tmp_path
):
    log = tmp_path / "semantic-reservation.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(
        repository,
        provider,
        log,
        max_parallel_jobs=2,
        input_cost_per_million=10.0,
        output_cost_per_million=10.0,
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    with database.connect() as connection:
        estimates = [
            float(row[0])
            for row in connection.execute(
                """
                SELECT estimated_cost_usd FROM semantic_jobs
                WHERE repository_id = ? AND status = 'pending'
                ORDER BY priority DESC, id LIMIT 2
                """,
                (stats.repository_id,),
            ).fetchall()
        ]
    budget = max(estimates) + min(estimates) / 2
    semantic = replace(config.semantic, daily_budget_usd=budget)

    assert engine._claim_job(stats.repository_id, semantic) is not None
    assert engine._claim_job(stats.repository_id, semantic) is None


def test_forced_plan_survives_until_a_later_worker_run(repository, database, tmp_path):
    log = tmp_path / "semantic-force.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert (
        engine.bootstrap(stats.repository_id, repository, config)["semantic"]["semantically_ready"]
        is True
    )
    initial_calls = len(_calls(log))

    planned = engine.bootstrap(
        stats.repository_id,
        repository,
        config,
        force=True,
        plan_only=True,
    )
    assert planned["processed"] == 0
    assert planned["planned"] == 9
    assert planned["semantic"]["pending"] == 9

    resumed = engine.bootstrap(stats.repository_id, repository, config)
    assert resumed["processed"] == 9
    assert resumed["semantic"]["semantically_ready"] is True
    assert len(_calls(log)) == initial_calls + 9
    assert {item["kind"] for item in _calls(log)[initial_calls:]} == {"intrinsic"}


def test_age_expired_dossiers_are_rebuilt_instead_of_left_pending(repository, database, tmp_path):
    log = tmp_path / "semantic-age.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log, max_age_days=1)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert (
        engine.bootstrap(stats.repository_id, repository, config)["semantic"]["semantically_ready"]
        is True
    )
    initial_calls = len(_calls(log))

    with database.transaction() as connection:
        connection.execute("UPDATE semantic_documents SET created_at = '2000-01-01T00:00:00+00:00'")
    rebuilt = engine.bootstrap(stats.repository_id, repository, config)

    assert rebuilt["processed"] > 9
    assert rebuilt["semantic"]["semantically_ready"] is True
    new_calls = _calls(log)[initial_calls:]
    assert len(new_calls) == rebuilt["processed"]
    assert {item["kind"] for item in new_calls} == {"intrinsic", "context", "synthesis"}


def test_large_scope_synthesis_is_chunked_and_reduced(database):
    calls = []

    class Provider:
        def analyze(self, request):
            calls.append(request["analysis_kind"])
            return SemanticResult(
                value={
                    "summary": f"Summary for {request['analysis_kind']}",
                    "responsibilities": ["Synthesize child responsibilities"],
                    "architecture_role": "Test synthesis",
                },
                confidence=0.9,
                evidence=(),
                input_tokens=10,
                output_tokens=5,
            )

    request = {
        "contract": "Synthesize every child.",
        "schema_version": "module-dossier-v4",
        "analysis_kind": "synthesis",
        "scope_type": "group",
        "scope_key": "large-group",
        "child_dossiers": [
            {"scope": f"module-{index}", "value": {"summary": "x" * 1_000}} for index in range(80)
        ],
    }
    result = SemanticEngine(database)._analyze_request(
        Provider(), request, SemanticConfig(max_source_chars=4_000, max_context_modules=4)
    )

    assert calls[-1] == "synthesis"
    assert "synthesis_chunk" in calls
    assert "synthesis_reduction" in calls
    assert result.input_tokens == len(calls) * 10
    assert result.output_tokens == len(calls) * 5


def test_intent_fingerprint_ignores_summary_wording_and_list_order():
    first = {
        "summary": "Owns repository enrollment.",
        "responsibilities": ["Plan semantic work", "Persist dossiers"],
        "public_contracts": ["SemanticEngine.bootstrap"],
        "architecture_role": "Repository Intelligence Service",
    }
    rephrased = {
        "summary": "Bootstraps repository understanding.",
        "responsibilities": ["  persist DOSSIERS ", "plan semantic work"],
        "public_contracts": ["semanticengine.bootstrap"],
        "architecture_role": "repository  intelligence service",
    }

    assert _intent_fingerprint(first) == _intent_fingerprint(rephrased)
    rephrased["responsibilities"] = ["Delete repository data"]
    assert _intent_fingerprint(first) != _intent_fingerprint(rephrased)


def test_coding_agent_can_build_the_entire_semantic_baseline_with_its_own_tokens(
    repository, database
):
    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "prompt_version": "agent-test-v1",
        "max_source_chars": 4_000,
        "max_parallel_jobs": 1,
        "agent_lease_seconds": 120,
    }
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    prepared = engine.bootstrap(stats.repository_id, repository, config)
    assert prepared["processed"] == 0
    assert prepared["semantic"]["pending"] == 9

    last_packet = None
    last_dossier = None
    for _ in range(100):
        packet = engine.claim_agent_work(
            stats.repository_id,
            repository,
            config,
            agent_id="codex-test",
            agent_model="test-model",
        )
        if packet["status"] == "complete":
            break
        assert packet["status"] == "work"
        assert packet["response_contract"]["schema_version"] == "module-dossier-v4"
        manifest = packet["evidence_manifest"]
        if manifest:
            pages = [
                engine.agent_evidence_page(
                    stats.repository_id,
                    repository,
                    config,
                    job_id=packet["job"]["id"],
                    lease_token=packet["lease"]["token"],
                    page=page,
                )
                for page in range(1, manifest["page_count"] + 1)
            ]
            assert all(item["status"] == "evidence" for item in pages)
        dossier = _agent_dossier(packet["analysis_request"])
        submitted = engine.submit_agent_work(
            stats.repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=dossier,
        )
        assert submitted["status"] == "completed"
        last_packet = packet
        last_dossier = dossier
    else:
        raise AssertionError("Agent-funded semantic bootstrap did not converge")

    status = engine.status(stats.repository_id, config.semantic)
    assert status["semantically_ready"] is True
    assert status["execution_mode"] == "coding_agent"
    assert status["usage"] == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    assert status["repository_dossier"]["executor_id"] == "codex-test"
    assert status["repository_dossier"]["executor_model"] == "test-model"
    with database.connect() as connection:
        provenance = connection.execute(
            """
            SELECT DISTINCT source, provider, executor_id, executor_model
            FROM semantic_documents
            """
        ).fetchall()
    assert [tuple(row) for row in provenance] == [
        ("coding_agent", "agent", "codex-test", "test-model")
    ]
    repeated = engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=last_packet["job"]["id"],
        lease_token=last_packet["lease"]["token"],
        dossier=last_dossier,
    )
    assert repeated["status"] == "already_completed"


def test_agent_semantic_writeback_rejects_bad_tokens_and_invalid_dossiers(repository, database):
    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    packet = engine.claim_agent_work(
        stats.repository_id,
        repository,
        config,
        agent_id="codex-test",
    )

    with pytest.raises(ValueError, match="lease token is invalid"):
        engine.submit_agent_work(
            stats.repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token="wrong-token",
            dossier=_agent_dossier(packet["analysis_request"]),
        )
    with pytest.raises(ValueError, match="missing required fields"):
        engine.submit_agent_work(
            stats.repository_id,
            repository,
            config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier={"summary": "incomplete"},
        )
    released = engine.release_agent_work(
        stats.repository_id,
        config,
        job_id=packet["job"]["id"],
        lease_token=packet["lease"]["token"],
        reason="test release",
    )
    assert released["status"] == "released"
