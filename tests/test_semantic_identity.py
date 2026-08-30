from __future__ import annotations

from dataclasses import replace

from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_freshness import semantic_digest
from anaxigraph.semantic_graph import _interface_hash, _module_scope
from anaxigraph.semantic_taxonomy_plan import _taxonomy_evidence, _taxonomy_settings
from anaxigraph.understanding import SemanticEngine


def test_module_scope_identity_uses_current_fact_references():
    assert _module_scope(
        "pkg/core.py",
        {"artifact_id": "17", "file_fact_id": "29"},
    ) == {
        "scope_type": "module",
        "scope_key": "pkg/core.py",
        "artifact_id": 17,
        "artifact_version_id": None,
        "file_fact_id": 29,
    }


def test_executor_and_model_changes_do_not_invalidate_semantic_documents(
    repository, database, tmp_path
):
    log = tmp_path / "semantic-executor-change.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)

    baseline = engine.bootstrap(stats.repository_id, repository, config)
    assert baseline["semantic"]["semantically_ready"] is True
    baseline_calls = len(_calls(log))

    with database.transaction() as connection:
        inventory, relationships = semantic_inventory(connection, stats.snapshot_id)
        module = inventory["pkg/core.py"]
        legacy_evidence = {
            "path": "pkg/core.py",
            "language": module["language"],
            "analyzer": module["analyzer"],
            "structural_hash": module["structural_hash"],
            "interface_hash": _interface_hash(module),
        }
        legacy_hash = semantic_digest(
            {
                "schema": "module-dossier-v4",
                "prompt": config.semantic.prompt_version,
                "provider": "agent",
                "model": "",
                **legacy_evidence,
            }
        )
        connection.execute(
            """
            UPDATE semantic_documents SET input_hash = ?, provider = 'agent', model = '',
                schema_version = 'module-dossier-v4'
            WHERE repository_id = ? AND scope_type = 'module' AND scope_key = 'pkg/core.py'
              AND document_kind = 'intrinsic'
            """,
            (legacy_hash, stats.repository_id),
        )
        documents = [
            dict(row)
            for row in connection.execute(
                """
                SELECT sd.scope_key, sd.intent_fingerprint, sd.input_hash
                FROM semantic_scope_states ss
                JOIN semantic_documents sd
                  ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
                WHERE ss.repository_id = ? AND ss.snapshot_id = ?
                  AND ss.scope_type = 'module' AND ss.status = 'current'
                ORDER BY ss.scope_key
                """,
                (stats.repository_id, stats.snapshot_id),
            )
        ]
        taxonomy_evidence = _taxonomy_evidence(
            settings=_taxonomy_settings(config.semantic),
            documents=documents,
            missing=[],
            relationships=relationships,
            hints=config.map.hints,
            locks=config.map.locked_memberships,
        )
        legacy_taxonomy_hash = semantic_digest(
            {
                "schema": "repository-understanding-v5",
                "prompt": config.semantic.prompt_version,
                "provider": "agent",
                "model": "",
                **taxonomy_evidence,
            }
        )
        connection.execute(
            """
            UPDATE semantic_taxonomies SET input_hash = ?, provider = 'agent', model = '',
                schema_version = 'repository-understanding-v5'
            WHERE repository_id = ? AND snapshot_id = ? AND status = 'current'
            """,
            (legacy_taxonomy_hash, stats.repository_id, stats.snapshot_id),
        )

    changed_executor = replace(
        config,
        semantic=replace(
            config.semantic,
            provider="agent",
            command=(),
            model="gpt-next-model",
        ),
    )
    repeated = engine.bootstrap(stats.repository_id, repository, changed_executor)

    assert repeated["processed"] == 0
    assert engine.plan(stats.repository_id, repository, changed_executor).active_jobs == 0
    assert repeated["semantic"]["current"] == repeated["semantic"]["eligible_modules"]
    assert repeated["semantic"]["semantically_ready"] is True
    assert len(_calls(log)) == baseline_calls
