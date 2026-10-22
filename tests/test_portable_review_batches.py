"""A cloud review checkpoint resumes in a different clone and local index namespace."""

import json
from collections import Counter
from dataclasses import replace
from hashlib import sha256

import pytest
from semantic_support import (
    _agent_dossier,
    _DeterministicLifecycleProvider,
    _enable_agent_semantics,
)
from test_portable_record import publish_and_clone
from test_workflows import prepare

from anaxigraph.api_workflows import WorkflowRequest
from anaxigraph.config import load_config
from anaxigraph.portable_record import save_record
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_freshness import TAXONOMY_REVIEW_CONTRACT, semantic_input_hash
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine
from anaxigraph.workflow_execution import WorkflowExecution
from anaxigraph.workflow_settings import WorkflowSettings


@pytest.mark.parametrize("producer", ["current", "legacy_export", "legacy_resume"])
def test_completed_review_batch_survives_clone_with_different_ids(
    repository, database, tmp_path, monkeypatch, producer
):
    prepare(repository, database, monkeypatch)
    config = load_config(repository)
    owner = database.repository(repository)
    settings = WorkflowSettings(database.path).read(owner["id"], 2)["steps"]

    def run(db, row, policy, choices, step, max_jobs=None):
        return WorkflowExecution(
            db,
            row,
            policy,
            WorkflowRequest(workflow="mapping", step=step, max_jobs=max_jobs),
            choices,
        ).run()

    assert run(database, owner, config, settings, "taxonomy_proposal")["status"] == "complete"
    small = replace(
        config, semantic=replace(config.semantic, max_output_tokens=360, max_source_chars=5_000)
    )
    run(database, owner, small, settings, "taxonomy_review", max_jobs=1)
    with database.connect() as connection:
        batch = connection.execute(
            "SELECT metadata_json FROM semantic_jobs WHERE job_kind='taxonomy_review' AND status='completed' AND json_extract(metadata_json,'$.review_phase')='batch'"
        ).fetchone()
    assert batch is not None
    if producer != "current":
        _legacy_batch(database, owner["id"], config.semantic.prompt_version)
        if producer == "legacy_resume":
            SemanticEngine(database).plan(owner["id"], repository, config)
    save_record(database, owner["id"])
    clone = publish_and_clone(repository, tmp_path / "other-machine")

    local = AnaxiIndex(tmp_path / "local.db")
    other = tmp_path / "another-project"
    other.mkdir()
    (other / "service.py").write_text("VALUE=1\n")
    (other / ".anaxigraph.yml").write_text("{}\n")
    _enable_agent_semantics(other)
    first = RepositoryScanner(local).scan(other)
    engine = SemanticEngine(local)
    other_config = load_config(other)
    work = engine.claim_agent_work(first.repository_id, other, other_config, agent_id="local")
    engine.submit_agent_work(
        first.repository_id,
        other,
        other_config,
        job_id=work["job"]["id"],
        lease_token=work["lease"]["token"],
        dossier=_agent_dossier(work["analysis_request"]),
    )
    restored = RepositoryScanner(local).scan(clone)
    assert restored.repository_id != owner["id"]
    with local.connect() as connection:
        checkpoints = [
            dict(row)
            for row in connection.execute(
                "SELECT id,input_hash,attempts FROM semantic_jobs WHERE repository_id=? AND job_kind='taxonomy_review' AND status='completed'",
                (restored.repository_id,),
            )
        ]
    calls = Counter()

    class Tracking(_DeterministicLifecycleProvider):
        def analyze(self, request):
            if request.get("analysis_kind") == "taxonomy_review":
                calls[(request["review_pass"], request.get("chunk", {}).get("index", 0))] += 1
            return super().analyze(request)

    monkeypatch.setattr("anaxigraph.semantic_runner.create_semantic_provider", lambda _: Tracking())
    result = run(
        local,
        local.repository(clone),
        load_config(clone),
        WorkflowSettings(local.path).read(restored.repository_id, 2)["steps"],
        "taxonomy_review",
    )
    assert result["status"] == "complete", result
    with local.connect() as connection:
        for item in checkpoints:
            row = connection.execute(
                "SELECT input_hash,attempts FROM semantic_jobs WHERE id=?", (item["id"],)
            ).fetchone()
            assert row["input_hash"] == item["input_hash"]
            assert row["attempts"] == item["attempts"]
    assert calls[(1, 1)] == 0


def _legacy_batch(database, repository_id, prompt):
    """Persist the exact numeric-candidate cache identity used before 0.8.4."""
    with database.transaction() as connection:
        job = connection.execute(
            "SELECT * FROM semantic_jobs WHERE repository_id=? AND job_kind='taxonomy_review' AND status='completed' AND json_extract(metadata_json,'$.review_phase')='batch' LIMIT 1",
            (repository_id,),
        ).fetchone()
        metadata = json.loads(job["metadata_json"])
        taxonomy = connection.execute(
            "SELECT * FROM semantic_taxonomies WHERE snapshot_id=? AND input_hash=?",
            (job["snapshot_id"], metadata["taxonomy_input_hash"]),
        ).fetchone()
        evidence = {
            "taxonomy_input_hash": taxonomy["input_hash"],
            "candidate_document_id": taxonomy["candidate_document_id"],
            "review_pass": metadata["review_pass"],
            "validation": json.loads(taxonomy["validation_json"]),
        }
        group = semantic_input_hash(TAXONOMY_REVIEW_CONTRACT, prompt, evidence)
        paths = [
            connection.execute(
                "SELECT scope_key FROM semantic_documents WHERE id=?", (identifier,)
            ).fetchone()[0]
            for identifier in metadata["document_ids"]
        ]
        digest = sha256(
            json.dumps({"review": group, "paths": paths}, sort_keys=True).encode()
        ).hexdigest()
        scope = f"{repository_id}:review:{group}:batch:{metadata['batch_index']}"
        metadata["review_group_hash"] = group
        connection.execute(
            "UPDATE semantic_documents SET scope_key=?,input_hash=? WHERE snapshot_id=? AND scope_key=? AND input_hash=? AND document_kind='taxonomy_review'",
            (scope, digest, job["snapshot_id"], job["scope_key"], job["input_hash"]),
        )
        connection.execute(
            "UPDATE semantic_jobs SET scope_key=?,input_hash=?,metadata_json=? WHERE id=?",
            (scope, digest, json.dumps(metadata), job["id"]),
        )
