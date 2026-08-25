from __future__ import annotations

from dataclasses import replace

import pytest
import yaml
from semantic_support import _agent_dossier

from anaxigraph.config import load_config
from anaxigraph.persistence import rebuild_checkpoints
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic import SemanticResult
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine


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
    assert prepared["semantic"]["pending"] == 8

    last_packet = None
    last_dossier = None
    for _ in range(500):
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
        assert packet["response_contract"]["schema_version"] == "repository-understanding-v5"
        writing = packet["analysis_request"]["writing_requirements"]
        assert packet["analysis_request"]["writing_contract_version"] == "plain-language-v2"
        assert "smart twelve-year-old" in writing["audience"]
        assert "what the number can and cannot mean" in writing["score_rule"]
        terms = packet["analysis_request"]["input_term_meanings"]
        assert "one repository file" in terms["module"]
        assert "not a code-quality grade" in terms["complexity"]
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
    assert status["patterns"]["ready"] is True
    assert status["patterns"]["selected"] == status["patterns"]["finalized"] > 0
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
        pattern_counts = dict(
            connection.execute(
                """
                SELECT document_kind, COUNT(*) FROM semantic_documents
                WHERE document_kind LIKE 'pattern_%' GROUP BY document_kind
                """
            ).fetchall()
        )
    assert [tuple(row) for row in provenance] == [
        ("coding_agent", "agent", "codex-test", "test-model")
    ]
    assert pattern_counts == {
        "pattern_assessment": status["patterns"]["selected"],
        "pattern_review": status["patterns"]["selected"],
    }
    repeated = engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=last_packet["job"]["id"],
        lease_token=last_packet["lease"]["token"],
        dossier=last_dossier,
    )
    assert repeated["status"] == "already_completed"


def test_local_codex_executor_can_complete_an_agent_funded_queue(repository, database, monkeypatch):
    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {
        "enabled": True,
        "provider": "agent",
        "prompt_version": "agent-cli-test-v1",
        "max_parallel_jobs": 1,
    }
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    calls = []

    class Provider:
        name = "codex"

        def analyze(self, request):
            calls.append(request["analysis_kind"])
            value = _agent_dossier(request)
            return SemanticResult(
                value=value,
                confidence=float(value.get("confidence") or 0),
                evidence=tuple(value.get("evidence") or ()),
            )

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", lambda _: Provider())
    original_run_jobs = SemanticEngine.run_jobs
    attempts = 0

    def briefly_unclaimable(self, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {
                "processed": 0,
                "completed": 0,
                "failed": 0,
                "retry": 0,
                "semantic": self.status(stats.repository_id, config.semantic),
            }
        return original_run_jobs(self, *args, **kwargs)

    sleeps = []
    monkeypatch.setattr(SemanticEngine, "run_jobs", briefly_unclaimable)
    monkeypatch.setattr("anaxigraph.semantic_runner.time.sleep", sleeps.append)
    execution = replace(config.semantic, provider="codex", model="test-model")
    completed = SemanticEngine(database).bootstrap(
        stats.repository_id,
        repository,
        config,
        execution_semantic=execution,
        until_complete=True,
    )

    assert completed["semantic"]["semantically_ready"] is True
    assert sleeps == [2]
    assert {
        "intrinsic",
        "context",
        "taxonomy_proposal",
        "taxonomy_review",
        "synthesis",
        "pattern_assessment",
        "pattern_review",
    } <= set(calls)
    with database.connect() as connection:
        provenance = connection.execute(
            """
            SELECT DISTINCT source, provider, model, executor_id, executor_model
            FROM semantic_documents
            """
        ).fetchall()
    assert [tuple(row) for row in provenance] == [
        ("coding_agent", "agent", "", "cli:codex", "test-model")
    ]


def test_semantic_evidence_and_work_identity_survive_checkpoint_rebuild(repository, database):
    policy = yaml.safe_load((repository / ".anaxigraph.yml").read_text(encoding="utf-8"))
    policy["semantic"] = {"enabled": True, "provider": "agent"}
    (repository / ".anaxigraph.yml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    with database.connect() as connection:
        evidence_before = semantic_inventory(connection, stats.snapshot_id)
        jobs_before = [
            tuple(row)
            for row in connection.execute(
                "SELECT scope_key, input_hash, artifact_id, file_fact_id, status "
                "FROM semantic_jobs ORDER BY id"
            )
        ]
        assert jobs_before and all(row[3] is not None for row in jobs_before if row[2] is not None)

    with database.transaction() as connection:
        connection.execute("DELETE FROM snapshot_checkpoints")
        rebuilt = rebuild_checkpoints(connection)
    assert rebuilt == {"snapshots": 1, "checkpoints": 0}

    engine.plan(stats.repository_id, repository, config)
    with database.connect() as connection:
        evidence_after = semantic_inventory(connection, stats.snapshot_id)
        jobs_after = [
            tuple(row)
            for row in connection.execute(
                "SELECT scope_key, input_hash, artifact_id, file_fact_id, status "
                "FROM semantic_jobs ORDER BY id"
            )
        ]
    assert evidence_after == evidence_before
    assert jobs_after == jobs_before


def test_schema_ten_preserves_and_backfills_semantic_fact_references(repository, database):
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
        agent_id="migration-test",
    )
    engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=packet["job"]["id"],
        lease_token=packet["lease"]["token"],
        dossier=_agent_dossier(packet["analysis_request"]),
    )

    with database.transaction() as connection:
        expected = _semantic_fact_references(connection)
        assert all(value is not None for values in expected.values() for value in values)
        for table in (
            "semantic_claims",
            "semantic_documents",
            "semantic_jobs",
            "semantic_scope_states",
        ):
            if table == "semantic_claims":
                continue
            connection.execute(f"UPDATE {table} SET file_fact_id = NULL")
        connection.execute("UPDATE schema_meta SET value = '8' WHERE key = 'schema_version'")

    reopened = AnaxiIndex(database.path)
    with reopened.connect() as connection:
        assert _semantic_fact_references(connection) == expected


def _semantic_fact_references(connection) -> dict[str, list[int | None]]:
    return {
        table: [
            row["file_fact_id"]
            for row in connection.execute(
                f"SELECT file_fact_id FROM {table} "
                + ("" if table == "semantic_claims" else "WHERE artifact_id IS NOT NULL ")
                + (
                    "ORDER BY id"
                    if table != "semantic_scope_states"
                    else "ORDER BY snapshot_id, scope_type, scope_key"
                )
            )
        ]
        for table in (
            "semantic_claims",
            "semantic_documents",
            "semantic_jobs",
            "semantic_scope_states",
        )
    }


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
