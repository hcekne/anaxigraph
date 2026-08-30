import pytest

from anaxigraph.semantic_job_state import (
    FAILED_SEMANTIC_SCOPE_STATES,
    semantic_job_bulk_transition,
    semantic_job_transition,
    semantic_scope_status,
)


@pytest.mark.parametrize(
    ("current", "event", "target"),
    [
        ("pending", "claim", "running"),
        ("retry", "claim", "running"),
        ("running", "complete", "completed"),
        ("running", "retry", "retry"),
        ("running", "fail", "failed"),
        ("running", "release", "retry"),
        ("running", "lease_expired", "retry"),
        ("pending", "supersede", "superseded"),
        ("retry", "supersede", "superseded"),
        ("running", "supersede", "superseded"),
        ("failed", "reset_failed", "pending"),
    ],
)
def test_semantic_job_state_machine_accepts_only_declared_transitions(
    current: str, event: str, target: str
) -> None:
    assert semantic_job_transition(current, event) == target


@pytest.mark.parametrize(
    ("current", "event"),
    [
        ("pending", "complete"),
        ("completed", "claim"),
        ("failed", "retry"),
        ("unknown", "claim"),
        ("pending", "unknown"),
    ],
)
def test_semantic_job_state_machine_rejects_implicit_transitions(current: str, event: str) -> None:
    with pytest.raises(ValueError, match="semantic job transition"):
        semantic_job_transition(current, event)


def test_bulk_transition_requires_one_shared_target() -> None:
    assert (
        semantic_job_bulk_transition(("pending", "retry", "running"), "supersede") == "superseded"
    )
    with pytest.raises(ValueError, match="at least one source"):
        semantic_job_bulk_transition((), "supersede")


@pytest.mark.parametrize(
    ("job_kind", "pending", "failed"),
    [
        ("intrinsic", "pending_intrinsic", "failed_intrinsic"),
        ("context", "pending_context", "failed_context"),
        ("synthesis", "pending_synthesis", "failed_synthesis"),
        ("taxonomy_proposal", "pending_taxonomy_proposal", "failed_taxonomy"),
        ("taxonomy_review", "pending_taxonomy_review", "failed_taxonomy"),
        ("pattern_assessment", "pending_pattern_assessment", "failed_pattern"),
        ("pattern_review", "pending_pattern_review", "failed_pattern"),
    ],
)
def test_job_kinds_share_one_scope_state_vocabulary(
    job_kind: str, pending: str, failed: str
) -> None:
    assert semantic_scope_status(job_kind) == pending
    assert semantic_scope_status(job_kind, failed=True) == failed
    assert failed in FAILED_SEMANTIC_SCOPE_STATES


def test_scope_state_vocabulary_rejects_unknown_job_kinds() -> None:
    with pytest.raises(ValueError, match="Unknown semantic job kind"):
        semantic_scope_status("unknown")
