from __future__ import annotations

from dataclasses import replace

from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.agent import agent_scope
from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.semantic_graph import _intent_fingerprint
from anaxigraph.understanding import SemanticEngine


def test_full_semantic_bootstrap_is_resumable_and_incremental(repository, database, tmp_path):
    log = tmp_path / "semantic.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)

    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    queued = engine.status(stats.repository_id, config.semantic)
    assert queued["total_modules"] == 8
    assert queued["pending"] == 8
    assert queued["current"] == 0

    result = engine.bootstrap(stats.repository_id, repository, config)
    status = result["semantic"]
    assert status["semantically_ready"] is True
    assert status["baseline_complete"] is True
    assert status["current"] == status["eligible_modules"] == 8
    assert status["repository_dossier"]["value"]["summary"]
    assert status["repository_dossier"]["plain_language"]["version"] == (
        "semantic-file-explanation-v4"
    )
    assert (
        "how its parts work together"
        in status["repository_dossier"]["plain_language"]["conclusion"]
    )
    assert status["taxonomy"]["ready"] is True
    assert status["taxonomy"]["current"]["review_passes"] == 2
    assert status["patterns"]["ready"] is True
    assert status["patterns"]["selected"] == status["patterns"]["finalized"] > 0
    assert {"intrinsic", "context", "synthesis"} <= {item["kind"] for item in _calls(log)}
    modules = database.modules(stats.repository_id)
    core_module = next(item for item in modules if item["path"] == "pkg/core.py")
    assert core_module["summary_source"] == "command AI description using repository context"
    assert core_module["architecture_layer"] == "semantic"
    assert core_module["semantic_taxonomy"]["confidence"] == 0.85
    assert core_module["semantic_taxonomy"]["plain_language"]["why_this_file_is_here"]
    assert core_module["semantic_taxonomy"]["area_label"]
    assert core_module["semantic"]["plain_language"]["version"] == ("semantic-file-explanation-v4")
    assert (
        core_module["summary"] == core_module["semantic"]["plain_language"]["what_this_file_does"]
    )
    assert "role in this repository" in core_module["semantic"]["plain_language"]["conclusion"]
    core_detail = database.file_details(stats.repository_id, "pkg/core.py")
    assert core_detail["semantic_plain_language"]["version"] == "semantic-file-explanation-v4"
    assert core_detail["semantic_plain_language"]["what_this_file_does"]
    semantic_map = database.semantic_taxonomy(stats.repository_id)
    assert semantic_map["validation"]["assigned_modules"] == 8
    assert semantic_map["review_passes"] == 2
    assert len(semantic_map["reviews"]) == 2
    assert all("issues_json" not in review for review in semantic_map["reviews"])
    assert sum(group["files"] for group in semantic_map["hierarchy"]) == 8
    overview = database.overview(stats.repository_id)
    assert overview["map"]["default_layer"] == "semantic"
    assert overview["group_hierarchy"] == overview["group_hierarchies"]["semantic"]
    group_language = overview["group_hierarchy"][0]["plain_language"]
    assert group_language["version"] == "semantic-taxonomy-explanation-v1"
    assert group_language["what_this_group_does"]
    assert group_language["why_these_files_are_together"]
    scope = agent_scope(
        database,
        repository_id=stats.repository_id,
        goal="Change Calculator behavior",
        branch=None,
        config=config,
    )
    assert scope["primary_files"][0]["semantic"]["status"] == "current"
    assert scope["primary_files"][0]["semantic"]["pattern_opportunities"][0]["score"] == 84
    file_language = scope["primary_files"][0]["semantic"]["plain_language"]
    assert file_language["version"] == "semantic-file-explanation-v4"
    assert "early AI notes, not instructions" in file_language["how_to_use_the_raw_fields"]
    assert scope["primary_files"][0]["summary"] == file_language["what_this_file_does"]
    search_result = next(
        item
        for item in database.search(stats.repository_id, "core")
        if item["path"] == "pkg/core.py"
    )
    assert (
        search_result["summary"]
        == search_result["semantic"]["plain_language"]["what_this_file_does"]
    )

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
    assert refreshed["processed"] > 1
    new_calls = _calls(log)[first_call_count:]
    assert new_calls[0] == {"path": "pkg/core.py", "kind": "intrinsic"}
    assert {item["kind"] for item in new_calls[1:]} == {
        "pattern_assessment",
        "pattern_review",
    }
    assert {item["path"] for item in new_calls[1:]} <= {"pkg/core.py", "scope"}
    assert sum(item["kind"] == "pattern_assessment" for item in new_calls) == sum(
        item["kind"] == "pattern_review" for item in new_calls
    )
    carried_map = database.semantic_taxonomy(changed.repository_id)
    assert carried_map["source"] == "carried_semantic_taxonomy"
    assert [item["name"] for item in carried_map["hierarchy"]] == [
        item["name"] for item in semantic_map["hierarchy"]
    ]
    dossier = SemanticEngine(database).dossier(changed.repository_id, "pkg/core.py")
    assert dossier["status"] == "current"
    assert dossier["intrinsic"]["input_tokens"] == 100
    assert dossier["intrinsic"]["previous_document_id"] is not None


def test_package_version_change_reuses_unchanged_semantic_documents(
    repository, database, tmp_path, monkeypatch
):
    log = tmp_path / "semantic-release-change.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    first = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    baseline = engine.bootstrap(first.repository_id, repository, config)
    assert baseline["semantic"]["semantically_ready"] is True
    baseline_calls = len(_calls(log))

    monkeypatch.setattr("anaxigraph.scan_preparation.__version__", "next-release-test")
    next_release = RepositoryScanner(database).scan(repository, run_type="update")
    repeated = engine.bootstrap(next_release.repository_id, repository, config)

    assert next_release.snapshot_id != first.snapshot_id
    assert repeated["processed"] == 0
    assert repeated["semantic"]["current"] == repeated["semantic"]["eligible_modules"]
    assert repeated["semantic"]["semantically_ready"] is True
    assert len(_calls(log)) == baseline_calls


def test_unaffected_context_dossiers_remain_current_while_changed_modules_wait(
    repository, database, tmp_path
):
    log = tmp_path / "semantic-partial-carry.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.bootstrap(stats.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]

    core = repository / "pkg" / "core.py"
    core.write_text(
        core.read_text(encoding="utf-8").replace(
            "return double(value)", "return double(value) + 1"
        ),
        encoding="utf-8",
    )
    changed = RepositoryScanner(database).scan(repository, run_type="update")
    planned = engine.bootstrap(changed.repository_id, repository, config, plan_only=True)

    assert planned["semantic"]["counts"]["pending_intrinsic"] == 1
    assert planned["semantic"]["current"] > 0
    assert planned["semantic"]["coverage"] > 0


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
            "SELECT id, file_fact_id FROM semantic_jobs ORDER BY priority DESC, id LIMIT 1"
        ).fetchone()
        assert job["file_fact_id"] is not None
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
            "SELECT status, worker_id, lease_expires_at, error, file_fact_id "
            "FROM semantic_jobs WHERE id = ?",
            (job["id"],),
        ).fetchone()
    assert row["status"] == "retry"
    assert row["worker_id"] is None
    assert row["lease_expires_at"] is None
    assert "lease expired" in row["error"]
    assert row["file_fact_id"] == job["file_fact_id"]
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
    assert result["semantic"]["pending"] == 8
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
    assert planned["planned"] == 8
    assert planned["semantic"]["pending"] == 8

    resumed = engine.bootstrap(stats.repository_id, repository, config)
    assert resumed["processed"] == 8
    assert resumed["semantic"]["semantically_ready"] is True
    assert len(_calls(log)) == initial_calls + 8
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
    assert {item["kind"] for item in new_calls} == {
        "intrinsic",
        "context",
        "synthesis",
        "pattern_assessment",
        "pattern_review",
    }


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
        "schema_version": "repository-understanding-v5",
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
