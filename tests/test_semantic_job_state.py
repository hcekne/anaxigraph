import pytest

from anaxigraph.semantic_job_state import (
    semantic_job_bulk_transition,
    semantic_job_transition,
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
