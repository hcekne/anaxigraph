from __future__ import annotations

import json

import pytest

from anaxigraph.config import load_config
from anaxigraph.finding_transport import collect_finding_ledger, query_findings
from anaxigraph.scanner import RepositoryScanner


def test_attention_is_bounded_while_diagnostics_remain_lossless(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    _insert_findings(database, stats.repository_id, stats.snapshot_id, count=27)
    _insert_findings(
        database,
        stats.repository_id,
        stats.snapshot_id,
        count=12,
        prefix="long",
        finding_type="long_function",
        severity="info",
    )
    _insert_findings(
        database,
        stats.repository_id,
        stats.snapshot_id,
        count=1,
        prefix="planned-long",
        finding_type="long_function",
        severity="info",
        status="planned",
    )
    config = load_config(repository)

    first = query_findings(database, stats.repository_id, config)

    assert first["view"] == "attention"
    assert first["shown"] == 20
    assert first["total_matching"] == 28
    assert first["next_cursor"]
    assert all(
        item["finding_type"] != "long_function" or item["status"] == "planned"
        for item in first["items"]
    )
    assert first["omitted"] == {
        "before_cursor": 0,
        "after_page": 8,
        "due_to_payload_budget": 0,
        "diagnostic_groups": 0,
    }

    second = query_findings(
        database,
        stats.repository_id,
        config,
        cursor=first["next_cursor"],
    )
    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert second["shown"] == 8
    assert second["next_cursor"] is None
    assert second["omitted"]["before_cursor"] == 20

    diagnostics = query_findings(
        database,
        stats.repository_id,
        config,
        view="diagnostics",
        finding_types=("long_function",),
        module="core.py",
        architecture_area="domain",
        page_size=50,
    )
    assert diagnostics["total_matching"] == 13
    assert diagnostics["shown"] == 13
    assert diagnostics["total_by_type"] == {"long_function": 13}
    assert diagnostics["groups"][0]["count"] == 13
    assert diagnostics["groups"][0]["architecture_area"] == "domain"

    exported = collect_finding_ledger(database, stats.repository_id, config)
    assert exported["shown"] == exported["total_matching"] == 41
    assert exported["omitted"]["after_page"] == 0


def test_finding_pages_explain_actionability_and_honor_agent_budget(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    _insert_findings(database, stats.repository_id, stats.snapshot_id, count=24)
    config = load_config(repository)

    page = query_findings(
        database,
        stats.repository_id,
        config,
        page_size=20,
        token_budget=1_500,
        compact=True,
    )

    assert 0 < page["shown"] < page["total_matching"]
    assert page["payload_budget"]["estimated_bytes"] <= 6_000
    assert page["payload_budget"]["truncated"] is True
    assert page["omitted"]["due_to_payload_budget"] == 20 - page["shown"]
    finding = page["items"][0]
    actionability = finding["actionability"]
    assert actionability["why_ranked"]
    assert actionability["evidence"]["semantic"]["status"] == "not_attached"
    assert actionability["false_positive_conditions"]
    assert actionability["affected"]["architecture_areas"] == ["domain"]
    assert actionability["smallest_next_action"]
    assert "marks this finding resolved" in actionability["verification"]
    language = finding["plain_language"]
    assert language["what"] == finding["summary"]
    assert language["why_it_matters"]
    assert language["next_step"] == finding["recommended_action"]
    assert language["how_to_check"]
    assert language["status"]["meaning"]
    assert language["priority"]["guidance"]
    assert "not a grade for the code" in language["priority"]["meaning"]
    assert "measurement confidence" not in " ".join(language["priority"]["reasons"])

    with pytest.raises(ValueError, match="does not match"):
        query_findings(
            database,
            stats.repository_id,
            config,
            cursor=page["next_cursor"],
            severities=("error",),
        )


def test_later_scans_resolve_and_regress_the_same_finding(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    original = next(
        item
        for item in database.findings(stats.repository_id)
        if item["finding_type"] == "module_complexity"
    )
    path = repository / original["affected_artifacts"][0]
    source = path.read_text(encoding="utf-8")
    database.update_finding_status(stats.repository_id, original["id"], "acknowledged")

    path.write_text("VALUE = 1\n", encoding="utf-8")
    RepositoryScanner(database).scan(repository)
    resolved = database.finding(stats.repository_id, original["id"])
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"]

    path.write_text(source, encoding="utf-8")
    RepositoryScanner(database).scan(repository)
    regressed = database.finding(stats.repository_id, original["id"])
    assert regressed["status"] == "regressed"
    assert regressed["resolved_at"] is None
    attention = query_findings(database, stats.repository_id, load_config(repository))
    assert original["id"] in {item["id"] for item in attention["items"]}


def _insert_findings(
    database,
    repository_id: int,
    snapshot_id: int,
    *,
    count: int,
    prefix: str = "warning",
    finding_type: str = "module_complexity",
    severity: str = "warning",
    status: str = "new",
) -> None:
    now = "2026-08-20T12:00:00+00:00"
    with database.transaction() as connection:
        for index in range(count):
            stable_key = f"test:{prefix}:{index}"
            connection.execute(
                """
                INSERT INTO findings(
                    repository_id, stable_key, finding_type, severity, confidence,
                    summary, explanation, affected_artifacts_json, evidence_json,
                    recommended_action, source, status, first_snapshot_id,
                    last_snapshot_id, first_detected_at, last_detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repository_id,
                    stable_key,
                    finding_type,
                    severity,
                    0.9,
                    f"Finding {prefix} {index}",
                    "Synthetic finding for deterministic query coverage.",
                    json.dumps(["pkg/core.py"]),
                    json.dumps([f"evidence-{index}"]),
                    "Inspect the module and make the smallest cohesive change.",
                    "deterministic",
                    status,
                    snapshot_id,
                    snapshot_id,
                    now,
                    now,
                ),
            )
