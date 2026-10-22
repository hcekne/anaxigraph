"""Exercise the operator migration command against original verbose persisted AI data."""

import json
import sqlite3

import yaml
from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.cli import main
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_graph import _intent_fingerprint
from anaxigraph.understanding import SemanticEngine


def test_cli_compaction_preserves_original_and_reuses_shortened_description(
    repository, database, capsys
):
    _enable_agent_semantics(repository)
    file = repository / ".anaxigraph.yml"
    policy = yaml.safe_load(file.read_text())
    policy["semantic"]["detailed_reviews"] = False
    file.write_text(yaml.safe_dump(policy))
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    work = engine.claim_agent_work(stats.repository_id, repository, config, agent_id="fixture")
    path = work["analysis_request"]["path"]
    engine.submit_agent_work(
        stats.repository_id,
        repository,
        config,
        job_id=work["job"]["id"],
        lease_token=work["lease"]["token"],
        dossier=_agent_dossier(work["analysis_request"]),
    )
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT id,value_json FROM semantic_documents WHERE scope_key=?", (path,)
        ).fetchone()
        legacy = json.loads(row["value_json"])
        legacy["summary"] = "A verbose legacy description of unchanged code. " * 6_000
        connection.execute(
            "UPDATE semantic_documents SET value_json=?,intent_fingerprint=? WHERE id=?",
            (json.dumps(legacy), _intent_fingerprint(legacy), row["id"]),
        )
    main(["record", "compact", str(repository), "--db", str(database.path), "--json"])
    result = json.loads(capsys.readouterr().out)
    assert result["record"]["record_exported"]
    assert result["record"]["committed"] is None
    assert result["record"]["pushed"] is None
    assert result["storage"]["within_budget"]
    assert result["record"]["files"] <= 32
    with sqlite3.connect(result["recovery_backup"]) as recovery:
        preserved = json.loads(
            recovery.execute(
                "SELECT value_json FROM semantic_documents WHERE id=?", (row["id"],)
            ).fetchone()[0]
        )
        assert preserved == legacy
    with database.connect() as connection:
        compact = json.loads(
            connection.execute(
                "SELECT value_json FROM semantic_documents WHERE id=?", (row["id"],)
            ).fetchone()[0]
        )
        assert len(compact["summary"]) <= 600
        assert not connection.execute(
            "SELECT 1 FROM semantic_jobs WHERE scope_key=? AND job_kind='intrinsic' AND status='pending'",
            (path,),
        ).fetchone()
