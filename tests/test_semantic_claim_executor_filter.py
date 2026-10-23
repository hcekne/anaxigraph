"""Claim admission by executor family for pinned fresh-eyes proposal slots."""

from __future__ import annotations

import json

import pytest
from fresh_eyes_support import (
    CLAUDE_EXECUTOR,
    CODEX_EXECUTOR,
    TwoExecutorReview,
    prepared_review,
)

from anaxigraph.semantic_lease_claim import claimable_by, claimant_family, required_executor

_PENDING_SQL = (
    "SELECT scope_key, status, metadata_json FROM semantic_jobs "
    "WHERE job_kind = 'fresh_proposal' AND status IN ('pending', 'retry') ORDER BY scope_key"
)


def _row(pin: object) -> dict:
    return {"metadata_json": json.dumps({"stage": "proposal", "required_executor": pin})}


def _pinned_review(repository, database) -> TwoExecutorReview:
    """Build the functional brief, then pin a=codex and b/c=claude for every scope."""

    review = prepared_review(
        repository, database, proposal_count=3, proposal_executors=("codex", "claude", "claude")
    )
    _finish_hierarchy(review)
    return review


def _finish_hierarchy(review):
    packet = review.claim(CODEX_EXECUTOR)
    assert packet["job"]["scope_key"] == "functional:brief"
    assert packet["analysis_request"]["functional_stage"] == "hierarchy"
    review.submit(packet)
    review.engine.plan(review.repository_id, review.repository, review.config)


def _pending_proposals(database) -> dict[str, str]:
    with database.connect() as connection:
        rows = [dict(row) for row in connection.execute(_PENDING_SQL)]
    return {
        str(row["scope_key"]): str(json.loads(row["metadata_json"])["required_executor"] or "")
        for row in rows
    }


def test_a_claimant_family_comes_from_the_declared_name_or_the_host_identity():
    assert claimant_family("cli:codex:4242") == "codex"
    assert claimant_family("cli:claude") == "claude"
    assert claimant_family("some-opaque-agent") == "unspecified"
    assert claimant_family(None) == "unspecified"
    assert claimant_family("some-opaque-agent", "Claude ") == "claude"
    assert claimant_family("cli:codex:1", "") == "codex"


@pytest.mark.parametrize(
    ("pin", "family", "eligible"),
    [
        ("codex", "codex", True),
        ("codex", "claude", False),
        ("codex", "unspecified", False),
        ("any", "unspecified", True),
        ("any", "codex", True),
        (None, "claude", True),
        ("", "unspecified", True),
        ("CODEX", "codex", True),
    ],
)
def test_only_unpinned_or_matching_work_is_claimable(pin, family, eligible):
    assert claimable_by(_row(pin), family) is eligible


def test_unreadable_job_metadata_is_treated_as_unpinned():
    assert required_executor({"metadata_json": "not json"}) == ""
    assert required_executor({"metadata_json": None}) == ""
    assert claimable_by({"metadata_json": "not json"}, "codex") is True


def test_each_host_executor_claims_only_the_slot_pinned_to_its_family(repository, database):
    review = _pinned_review(repository, database)

    codex = review.claim(CODEX_EXECUTOR)

    assert codex["job"]["scope_key"] == "functional:product:proposal:a"
    blocked = review.claim(CODEX_EXECUTOR)
    assert blocked["status"] != "work"
    assert _pending_proposals(database) == {
        "functional:product:proposal:b": "claude",
        "functional:product:proposal:c": "claude",
    }
    claude = review.claim(CLAUDE_EXECUTOR)
    assert claude["job"]["scope_key"] == "functional:product:proposal:b"
    third = review.claim(CLAUDE_EXECUTOR)
    assert third["job"]["scope_key"] == "functional:product:proposal:c"
    review.submit(codex)
    review.submit(claude)
    review.submit(third)
    review.run_until_complete()
    result = review.engine.fresh_eyes_status(review.repository_id, review.config.semantic)
    proposals = {
        item["key"]: item["provenance"]["executor_id"]
        for item in result["stages"]
        if ":proposal:" in item["key"]
    }
    assert proposals == {
        f"functional:{scope}:proposal:{slot}": executor
        for scope in ("product", "understanding", "retrieval")
        for slot, executor in (
            ("a", CODEX_EXECUTOR),
            ("b", CLAUDE_EXECUTOR),
            ("c", CLAUDE_EXECUTOR),
        )
    }


def test_a_claimant_without_a_host_family_takes_only_unpinned_work(repository, database):
    review = _pinned_review(repository, database)

    opaque = review.claim("some-editor-session")

    assert opaque["status"] != "work"
    assert _pending_proposals(database) == {
        "functional:product:proposal:a": "codex",
        "functional:product:proposal:b": "claude",
        "functional:product:proposal:c": "claude",
    }
    declared = review.engine.claim_agent_work(
        review.repository_id,
        review.repository,
        review.config,
        agent_id="some-editor-session",
        agent_model="fixture-model",
        executor_family="claude",
    )
    assert declared["job"]["scope_key"] == "functional:product:proposal:b"


def test_an_expired_pinned_lease_is_requeued_and_still_refused_to_the_wrong_family(
    repository, database
):
    review = _pinned_review(repository, database)
    claimed = review.claim(CLAUDE_EXECUTOR)
    assert claimed["job"]["scope_key"] == "functional:product:proposal:b"
    third = review.claim(CLAUDE_EXECUTOR)
    assert third["job"]["scope_key"] == "functional:product:proposal:c"

    with database.transaction() as connection:
        connection.execute(
            "UPDATE semantic_jobs SET started_at = '2000-01-01T00:00:00+00:00', "
            "lease_expires_at = '2000-01-01T00:01:00+00:00' WHERE id = ?",
            (claimed["job"]["id"],),
        )

    codex = review.claim(CODEX_EXECUTOR)
    assert codex["job"]["scope_key"] == "functional:product:proposal:a"
    assert _pending_proposals(database) == {"functional:product:proposal:b": "claude"}
    again = review.claim(CLAUDE_EXECUTOR)
    assert again["job"]["scope_key"] == "functional:product:proposal:b"
    assert again["job"]["id"] == claimed["job"]["id"]
    assert again["lease"]["token"] != claimed["lease"]["token"]
    with pytest.raises(ValueError, match="lease"):
        review.submit(claimed)
    for packet in (codex, again, third):
        review.submit(packet)


def test_an_unpinned_review_is_claimed_by_whoever_asks_first(repository, database):
    review = prepared_review(repository, database, proposal_count=3)
    _finish_hierarchy(review)

    held = review.hold_one_each("fresh_proposal")

    assert {packet["job"]["scope_key"] for packet in held.values()} == {
        "functional:product:proposal:a",
        "functional:product:proposal:b",
    }
    third = review.claim("some-editor-session")
    assert third["job"]["scope_key"] == "functional:product:proposal:c"
    assert len({packet["job"]["id"] for packet in [*held.values(), third]}) == 3
