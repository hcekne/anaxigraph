from __future__ import annotations

import json
import subprocess
from collections import Counter

from anaxigraph import scan_snapshot
from anaxigraph.analyzers.python import PythonAnalyzer
from anaxigraph.architecture import _dead_code_findings
from anaxigraph.config import RuleConfig
from anaxigraph.ir import analysis_from_stored
from anaxigraph.ir_conformance import validate_analysis
from anaxigraph.persistence.architecture_evidence import architecture_evidence
from anaxigraph.persistence.temporal_reads import snapshot_files, symbols_for_files
from anaxigraph.scanner import RepositoryScanner


def test_scan_persists_graph_metrics_coverage_and_findings(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    assert stats.discovered == 8
    assert stats.analyzed == 8
    assert stats.relationships >= 6
    overview = database.overview(stats.repository_id)
    assert overview["files"] == 8
    assert overview["symbols"] >= 7
    assert overview["coverage"]["line_coverage"] == 0.5
    assert overview["coverage"]["measured_files"] == 1
    assert overview["graph_quality"]["resolution_rate"] == 1.0
    assert overview["graph_quality"]["resolved_internal"] >= 6
    graph_language = overview["graph_quality"]["plain_language"]
    assert graph_language["version"] == "graph-quality-explanation-v1"
    assert graph_language["what_was_checked"].startswith("AnaxiGraph checked")
    assert any("while the program runs" in item for item in graph_language["what_this_limits"])
    assert database.file_details(stats.repository_id, ".anaxigraph.yml") is None
    snapshot = database.snapshots(stats.repository_id)[0]
    assert snapshot["file_count"] == overview["files"]
    assert snapshot["lines_of_code"] == overview["lines_of_code"]
    assert snapshot["relationship_count"] == stats.relationships

    graph = database.graph(stats.repository_id)
    nodes = {item["path"]: item for item in graph["nodes"]}
    assert "ignored/secret.py" not in nodes
    assert nodes["pkg/core.py"]["declared_group"] == "domain"
    modules = {item["path"]: item for item in database.modules(stats.repository_id)}
    assert modules["pkg/core.py"]["architecture_area"] == "domain"
    assert modules["pkg/core.py"]["summary"] == "Public calculation service."
    assert modules["pkg/core.py"]["evaluation"]["attention_score"] >= 0
    assert (
        "not a grade for the code"
        in modules["pkg/core.py"]["evaluation"]["attention_score_meaning"]
    )
    assert modules["pkg/core.py"]["evaluation"]["attention_guidance"]
    assert modules["pkg/core.py"]["evaluation"]["monitored_by_default"] is True
    assert modules["pkg/core.py"]["evaluation"]["suitability_score"] is None
    documentation = modules["docs/architecture.md"]["evaluation"]
    assert documentation["monitored_by_default"] is False
    assert documentation["attention_score"] is None
    assert documentation["attention_label"] == "Reference"
    assert "does not give reference files" in documentation["attention_score_meaning"]
    internal = {
        (
            next(item["path"] for item in graph["nodes"] if item["id"] == edge["source"]),
            next(item["path"] for item in graph["nodes"] if item["id"] == edge["target"]),
        )
        for edge in graph["edges"]
    }
    assert ("pkg/core.py", "pkg/util.py") in internal
    assert ("web/App.tsx", "web/helper.ts") in internal
    findings = database.findings(stats.repository_id)
    assert findings
    assert [item["priority_score"] for item in findings] == sorted(
        (item["priority_score"] for item in findings), reverse=True
    )
    assert all(item["priority_reasons"] for item in findings)
    assert all(item["priority_version"] == "risk-churn-blast-v1" for item in findings)
    assert not any(
        item["finding_type"] == "module_complexity"
        and "docs/architecture.md" in item["affected_artifacts"]
        for item in findings
    )
    with database.connect() as connection:
        files = snapshot_files(connection, stats.snapshot_id)
        stored = dict(next(file for file in files if file["path"] == "pkg/core.py"))
        stored["id"] = stored["file_fact_id"]
        stored["symbols"] = [
            item
            for item in symbols_for_files(connection, [stored])
            if item["artifact_id"] == stored["artifact_id"]
        ]
    metadata = json.loads(stored["metadata_json"])
    assert metadata["analysis_version"] == 4
    assert metadata["ir"]["schema_version"] == "anaxigraph-ir-v1"
    assert metadata["ir"]["analyzer_version"] == "1"
    assert metadata["ir"]["analyzer_capabilities"] == PythonAnalyzer.capabilities.as_dict()
    assert metadata["ir"]["module_identity"]["canonical_name"] == "pkg.core"
    assert metadata["ir"]["resolver_context"]["configured_aliases"] == [["@/", "web/"]]
    assert stored["symbols"][0]["visibility"] == "public"
    restored = analysis_from_stored(stored)
    assert validate_analysis(PythonAnalyzer(), "pkg/core.py", restored) == ()
    assert restored.resolver_context.configured_aliases == (("@/", "web/"),)


def test_scan_evaluates_architecture_without_legacy_staging_rows(repository, database, monkeypatch):
    real_evidence = scan_snapshot.architecture_evidence
    observed: list[list[str]] = []

    def capture_staging_rows(connection, snapshot_id):
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        observed.append(
            sorted(tables & {"file_versions", "symbols", "relationships", "group_memberships"})
        )
        return real_evidence(connection, snapshot_id)

    monkeypatch.setattr(scan_snapshot, "architecture_evidence", capture_staging_rows)

    stats = RepositoryScanner(database).scan(repository)

    assert stats.findings
    assert observed == [[]]


def test_untracked_root_control_file_is_not_an_application_module(repository, database):
    subprocess.run(
        ["git", "-C", str(repository), "rm", "--cached", "-q", ".anaxigraph.yml"],
        check=True,
    )

    stats = RepositoryScanner(database).scan(repository)

    assert stats.discovered == 8
    assert database.file_details(stats.repository_id, ".anaxigraph.yml") is None


def test_scan_retains_ambiguous_unresolved_and_external_relationship_evidence(repository, database):
    (repository / "src").mkdir()
    (repository / "shared.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "src" / "shared.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repository / "pkg" / "evidence.py").write_text(
        "import shared\nfrom .missing import value\nimport requests\n",
        encoding="utf-8",
    )

    stats = RepositoryScanner(database).scan(repository)
    detail = database.file_details(stats.repository_id, "pkg/evidence.py")
    assert detail is not None
    assert "saved facts and AI descriptions" in detail["plain_language"]["what"]
    assert (
        "not a code-quality grade" in detail["plain_language"]["measurement_meanings"]["complexity"]
    )
    by_target = {item["target_external"]: item for item in detail["relationships"]}

    assert by_target["shared"]["resolution_status"] == "ambiguous_internal"
    assert by_target["shared"]["candidate_paths"] == ["shared.py", "src/shared.py"]
    assert by_target[".missing"]["resolution_status"] == "unresolved_internal"
    assert by_target["requests"]["resolution_status"] == "external"
    quality = database.overview(stats.repository_id)["graph_quality"]
    assert quality["status"] == "partial"
    assert quality["ambiguous_internal"] >= 1
    assert quality["unresolved_internal"] >= 1
    assert quality["resolution_rate"] < 1
    language = quality["plain_language"]
    assert language["conclusion"].startswith("The map may miss connections because")
    assert "could point to more than one file" in language["what_was_checked"]
    assert any("will not recommend deleting code" in item for item in language["what_this_limits"])
    assert any("before acting" in item for item in language["what_to_do"])

    graph = database.graph(stats.repository_id, include_external=True)
    evidence_edges = [
        item
        for item in graph["edges"]
        if item["target_external"] in {"shared", ".missing", "requests"}
    ]
    assert {item["resolution_status"] for item in evidence_edges} == {
        "ambiguous_internal",
        "unresolved_internal",
        "external",
    }


def test_dead_code_advice_is_suppressed_when_relationship_resolution_is_weak(repository, database):
    (repository / "pkg" / "orphan.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "pkg" / "registered.py").write_text(
        "REGISTRY = object()\nREGISTRY.register('plugin')\n", encoding="utf-8"
    )
    (repository / "pkg" / "legacy.go").write_text("package pkg\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "add",
            "pkg/orphan.py",
            "pkg/registered.py",
            "pkg/legacy.go",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "Add old orphan"], check=True)
    stats = RepositoryScanner(database).scan(repository)
    rule = RuleConfig(
        rule_id="dead-test",
        rule_type="dead_code",
        severity="info",
        params={"minimum_age_days": 90, "minimum_resolution_rate": 0.8},
    )

    with database.transaction() as connection:
        connection.execute(
            "UPDATE git_changes SET committed_at = '2000-01-01T00:00:00+00:00' "
            "WHERE repository_id = ? AND path IN "
            "('pkg/orphan.py', 'pkg/registered.py', 'pkg/legacy.go')",
            (stats.repository_id,),
        )
        files, _symbols, relationships = architecture_evidence(connection, stats.snapshot_id)
        internal = [item for item in relationships if item["target_artifact_id"] is not None]
        fan_in = Counter(int(row["target_artifact_id"]) for row in internal)
        unresolved = [
            item | {"metadata_json": '{"resolution_status":"unresolved_internal"}'}
            for item in relationships
        ]
        suppressed = _dead_code_findings(
            connection,
            rule=rule,
            repository_id=stats.repository_id,
            files=files,
            fan_in=fan_in,
            relationship_evidence=unresolved,
        )
        assert not any(item.affected_artifacts == ("pkg/orphan.py",) for item in suppressed)

        resolved = [
            item | {"metadata_json": '{"resolution_status":"resolved_internal"}'}
            for item in relationships
        ]
        trusted = _dead_code_findings(
            connection,
            rule=rule,
            repository_id=stats.repository_id,
            files=files,
            fan_in=fan_in,
            relationship_evidence=resolved,
        )
        orphan = next(item for item in trusted if item.affected_artifacts == ("pkg/orphan.py",))
        assert "entry_point_capability=structural" in orphan.evidence
        assert "registration_capability=structural" in orphan.evidence
        assert not any(item.affected_artifacts == ("pkg/registered.py",) for item in trusted)
        assert not any(item.affected_artifacts == ("pkg/legacy.go",) for item in trusted)

        configured_entrypoint_rule = RuleConfig(
            rule_id="dead-test",
            rule_type="dead_code",
            severity="info",
            params={
                "minimum_age_days": 90,
                "minimum_resolution_rate": 0.8,
                "entry_points": ["pkg/orphan.py"],
            },
        )
        configured = _dead_code_findings(
            connection,
            rule=configured_entrypoint_rule,
            repository_id=stats.repository_id,
            files=files,
            fan_in=fan_in,
            relationship_evidence=resolved,
        )
        assert not any(item.affected_artifacts == ("pkg/orphan.py",) for item in configured)


def test_unchanged_scan_refreshes_ignored_coverage_report(repository, database):
    scanner = RepositoryScanner(database)
    first = scanner.scan(repository)
    report = repository / "coverage.xml"
    report_content = report.read_text(encoding="utf-8")
    assert database.overview(first.repository_id)["coverage"]["line_coverage"] == 0.5

    report.unlink()
    missing = scanner.scan(repository, run_type="update")
    assert missing.snapshot_id == first.snapshot_id
    assert missing.analyzed == 0
    assert database.overview(first.repository_id)["coverage"]["line_coverage"] is None

    report.write_text(report_content, encoding="utf-8")
    restored = scanner.scan(repository, run_type="update")
    assert restored.snapshot_id == first.snapshot_id
    assert restored.analyzed == 0
    assert database.overview(first.repository_id)["coverage"]["line_coverage"] == 0.5


def test_incremental_decision_tree_reuses_raw_and_metadata_only_changes(repository, database):
    scanner = RepositoryScanner(database)
    first = scanner.scan(repository)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE snapshots SET metadata_json = '{}' WHERE id = ?", (first.snapshot_id,)
        )
    unchanged = scanner.scan(repository, run_type="update")
    assert unchanged.snapshot_id == first.snapshot_id
    assert unchanged.analyzed == 0
    assert unchanged.reused == first.discovered
    with database.connect() as connection:
        metadata = json.loads(
            connection.execute(
                "SELECT metadata_json FROM snapshots WHERE id = ?", (first.snapshot_id,)
            ).fetchone()[0]
        )
    assert metadata["analysis_signature"]

    core = repository / "pkg" / "core.py"
    core.write_text(
        core.read_text(encoding="utf-8") + "\n# Documentation only.\n", encoding="utf-8"
    )
    metadata = scanner.scan(repository, run_type="update")
    detail = database.file_details(metadata.repository_id, "pkg/core.py")
    assert detail["file"]["analysis_status"] == "metadata_only"

    core.write_text(
        core.read_text(encoding="utf-8").replace(
            "return double(value)", "return double(value) if value >= 0 else 0"
        ),
        encoding="utf-8",
    )
    structural = scanner.scan(repository, run_type="update")
    detail = database.file_details(structural.repository_id, "pkg/core.py")
    assert detail["file"]["analysis_status"] == "structural_changed"
    assert structural.analyzed == 1
    assert structural.reused == structural.discovered - 1


def test_deleted_artifact_is_temporal_not_silently_removed(repository, database):
    scanner = RepositoryScanner(database)
    first = scanner.scan(repository)
    (repository / "web" / "helper.ts").unlink()
    second = scanner.scan(repository, run_type="update")

    assert second.deleted == 1
    assert database.file_details(second.repository_id, "web/helper.ts") is None
    assert (
        database.file_details(first.repository_id, "web/helper.ts", first.snapshot_id) is not None
    )
    with database.connect() as connection:
        row = connection.execute(
            "SELECT deleted_commit FROM artifacts WHERE canonical_path = 'web/helper.ts'"
        ).fetchone()
    assert row["deleted_commit"]


def test_commit_revision_scan_reads_git_without_checkout(repository, database):
    scanner = RepositoryScanner(database)
    revision = (
        __import__("subprocess")
        .check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True)
        .strip()
    )
    stats = scanner.scan(repository, revision=revision, run_type="history")

    snapshot = database.latest_snapshot(stats.repository_id)
    assert snapshot["snapshot_kind"] == "commit"
    assert snapshot["dirty"] == 0
    assert snapshot["commit_sha"] == revision


def test_historical_scan_does_not_replace_current_snapshot(repository, database):
    scanner = RepositoryScanner(database)
    old_revision = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    core = repository / "pkg" / "core.py"
    core.write_text(core.read_text(encoding="utf-8") + "\nNEW_VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "pkg/core.py"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "Add current value"], check=True)
    current = scanner.scan(repository)

    historical = scanner.scan(repository, revision=old_revision, run_type="history")

    assert historical.snapshot_id != current.snapshot_id
    assert database.latest_snapshot(current.repository_id)["id"] == current.snapshot_id


def test_group_hierarchy_rolls_declared_subsystem_into_parent(repository, database):
    config = repository / ".anaxigraph.yml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "groups:\n  domain:\n    paths: [pkg/**]",
            """groups:
  domain-core:
    level: subsystem
    parent: domain
    description: Core domain behavior.
    paths: [pkg/core.py]
  retired-domain:
    level: subsystem
    parent: domain
    description: A subsystem with no files in this snapshot.
    paths: [retired/**]
  domain:
    level: area
    description: Domain implementation.
    paths: [pkg/**]""",
        ),
        encoding="utf-8",
    )

    stats = RepositoryScanner(database).scan(repository)
    hierarchy = database.overview(stats.repository_id)["group_hierarchy"]
    domain = next(item for item in hierarchy if item["name"] == "domain")
    core = next(item for item in domain["children"] if item["name"] == "domain-core")

    assert domain["files"] >= core["files"] == 1
    assert domain["lines_of_code"] >= core["lines_of_code"]
    assert core["description"] == "Core domain behavior."
    assert all(item["name"] != "retired-domain" for item in domain["children"])
