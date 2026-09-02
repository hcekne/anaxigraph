from __future__ import annotations

from semantic_support import _calls, _fake_provider, _semantic_config

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_local_interface_change_keeps_validated_taxonomy_and_limits_the_cascade(
    repository, database, tmp_path
):
    log = tmp_path / "semantic-incremental-taxonomy.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    scanner = RepositoryScanner(database)
    engine = SemanticEngine(database)
    baseline = scanner.scan(repository)
    baseline_run = engine.bootstrap(baseline.repository_id, repository, config)
    assert baseline_run["semantic"]["semantically_ready"]
    assert baseline_run["work_plan"]["mode"] == "full"

    core = repository / "pkg" / "core.py"
    core.write_text(
        core.read_text(encoding="utf-8")
        .replace(
            "def calculate(self, value: int) -> int:",
            "def calculate(self, value: int, offset: int = 0) -> int:",
        )
        .replace("return double(value)", "return double(value) + offset"),
        encoding="utf-8",
    )
    changed = scanner.scan(repository, run_type="update")
    before = len(_calls(log))
    planned = engine.bootstrap(
        changed.repository_id,
        repository,
        config,
        plan_only=True,
    )

    assert planned["work_plan"]["mode"] == "incremental"
    assert planned["work_plan"]["modules"]["reread"] == 1
    refreshed = engine.bootstrap(changed.repository_id, repository, config)
    calls = _calls(log)[before:]
    assert refreshed["semantic"]["semantically_ready"] is True
    assert {item["kind"] for item in calls}.isdisjoint({"taxonomy_proposal", "taxonomy_review"})
    assert any(item["kind"] == "context" for item in calls)
    taxonomy = database.semantic_taxonomy(changed.repository_id)
    assert refreshed["work_plan"]["mode"] == "incremental"
    assert refreshed["work_plan"]["modules"]["reread"] == 1
    assert taxonomy["source"] == "incrementally_validated_taxonomy"
    current = refreshed["semantic"]["taxonomy"]["current"]
    assert current["source"] == "incrementally_validated_taxonomy"
    assert "8 of 8 intrinsic module roles remain stable" in current["refresh_reason"]


def test_new_module_triggers_a_new_taxonomy_instead_of_forcing_it_into_an_old_map(
    repository, database, tmp_path
):
    log = tmp_path / "semantic-new-module-taxonomy.log"
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    scanner = RepositoryScanner(database)
    engine = SemanticEngine(database)
    baseline = scanner.scan(repository)
    assert engine.bootstrap(baseline.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]

    (repository / "pkg" / "new_service.py").write_text(
        "def new_service() -> str:\n    return 'ready'\n",
        encoding="utf-8",
    )
    changed = scanner.scan(repository, run_type="update")
    before = len(_calls(log))
    refreshed = engine.bootstrap(changed.repository_id, repository, config)
    calls = _calls(log)[before:]

    assert refreshed["semantic"]["semantically_ready"] is True
    assert any(item["kind"] == "taxonomy_proposal" for item in calls)
    assert sum(item["kind"] == "taxonomy_review" for item in calls) == 2
    assert database.semantic_taxonomy(changed.repository_id)["source"] != (
        "incrementally_validated_taxonomy"
    )


def test_responsibility_drift_beyond_stability_policy_triggers_taxonomy_review(
    repository, database, tmp_path
):
    log = tmp_path / "semantic-responsibility-drift.log"
    provider = _fake_provider(tmp_path, intent_marker="SHIFTED_PURPOSE")
    _semantic_config(
        repository,
        provider,
        log,
        taxonomy={"enabled": True, "review_passes": 2, "stability_bias": 0.9},
    )
    config = load_config(repository)
    scanner = RepositoryScanner(database)
    engine = SemanticEngine(database)
    baseline = scanner.scan(repository)
    assert engine.bootstrap(baseline.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]

    core = repository / "pkg" / "core.py"
    core.write_text(
        core.read_text(encoding="utf-8") + "\nSHIFTED_PURPOSE = True\n",
        encoding="utf-8",
    )
    changed = scanner.scan(repository, run_type="update")
    before = len(_calls(log))
    refreshed = engine.bootstrap(changed.repository_id, repository, config)
    calls = _calls(log)[before:]

    assert refreshed["semantic"]["semantically_ready"] is True
    assert any(item["kind"] == "taxonomy_proposal" for item in calls)
    assert sum(item["kind"] == "taxonomy_review" for item in calls) == 2
