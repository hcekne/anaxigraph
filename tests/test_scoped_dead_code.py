"""Unused-code uncertainty is visible and local to the assessed source scope."""

from collections import Counter

from anaxigraph.architecture import _dead_code_findings
from anaxigraph.config import RuleConfig
from anaxigraph.persistence.architecture_evidence import architecture_evidence
from anaxigraph.scanner import RepositoryScanner


def test_runtime_and_resolution_gaps_do_not_silence_other_scopes(repository, database):
    paths = (
        "stable/orphan.py",
        "plugins/loader.py",
        "broken/client.py",
        "unknown/no_age.py",
        "unknown/unsupported.go",
    )
    for path in paths:
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("package unknown\n" if path.endswith(".go") else "VALUE = 1\n")
    stats = RepositoryScanner(database).scan(repository)
    rule = RuleConfig(
        rule_id="scoped-dead-code",
        rule_type="dead_code",
        severity="info",
        params={"paths": ["stable/*", "plugins/*", "broken/*", "unknown/*"]},
    )
    with database.transaction() as connection:
        for path in paths:
            connection.execute(
                "INSERT OR REPLACE INTO git_path_metrics(repository_id,path,change_count,last_changed_at,additions,deletions) "
                "VALUES (?,?,1,'2000-01-01T00:00:00+00:00',0,0)",
                (stats.repository_id, path),
            )
        connection.execute("DELETE FROM git_path_metrics WHERE path='unknown/no_age.py'")
        files, _, _ = architecture_evidence(connection, stats.snapshot_id)
        by_path = {file["path"]: file for file in files}
        relationships = [
            {
                "source_artifact_id": by_path[path]["artifact_id"],
                "target_artifact_id": None,
                "resolution_status": status,
            }
            for path, status in (
                ("plugins/loader.py", "dynamic"),
                ("broken/client.py", "unresolved_internal"),
            )
        ]
        findings = _dead_code_findings(
            connection,
            rule=rule,
            repository_id=stats.repository_id,
            files=files,
            fan_in=Counter(),
            relationship_evidence=relationships,
        )
    candidates = [item for item in findings if item.finding_type == "possible_dead_code"]
    assert [item.affected_artifacts for item in candidates] == [("stable/orphan.py",)]
    assert "scope_internal_resolution_rate=no_internal_references" in candidates[0].evidence
    gaps = [item for item in findings if item.finding_type == "dead_code_unassessed"]
    reasons = {value for item in gaps for value in item.evidence}
    assert "dynamic_links_in_scope=1" in reasons
    assert "insufficient_scope_resolution=1" in reasons
    assert "change_age_unavailable=1" in reasons
    assert "dynamic_wiring_unavailable=1" in reasons
    assert all(not item.affected_artifacts for item in gaps)
    assert all(
        "No candidate does not mean no unused code" in item.recommended_action for item in gaps
    )


def test_overview_records_scoped_assessment_and_diagnostic_findings(repository, database):
    path = repository / "isolated.py"
    path.write_text("VALUE = 1\n")
    stats = RepositoryScanner(database).scan(repository)
    overview = database.overview(stats.repository_id)
    coverage = overview["dead_code_assessment"]
    assert coverage["version"] == "scoped-unused-code-v1"
    assert coverage["state"] == "partial"
    assert coverage["unassessed_file_count"] >= 1
    assert coverage["scope_gap_count"] >= 1
    assert any(
        item["finding_type"] == "dead_code_unassessed"
        for item in database.findings(stats.repository_id)
    )
