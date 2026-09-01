"""Explicit state machine for durable semantic job transitions."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

PATTERN_METADATA_RETENTION = "pattern-evaluation-v1"
FRESH_EYES_METADATA_RETENTION = "fresh-eyes-input-v1"


class SemanticJobState(StrEnum):
    PENDING = "pending"
    RETRY = "retry"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class SemanticJobEvent(StrEnum):
    CLAIM = "claim"
    COMPLETE = "complete"
    RETRY = "retry"
    FAIL = "fail"
    RELEASE = "release"
    LEASE_EXPIRED = "lease_expired"
    SUPERSEDE = "supersede"
    RESET_FAILED = "reset_failed"


_TRANSITIONS = {
    (SemanticJobState.PENDING, SemanticJobEvent.CLAIM): SemanticJobState.RUNNING,
    (SemanticJobState.RETRY, SemanticJobEvent.CLAIM): SemanticJobState.RUNNING,
    (SemanticJobState.RUNNING, SemanticJobEvent.COMPLETE): SemanticJobState.COMPLETED,
    (SemanticJobState.RUNNING, SemanticJobEvent.RETRY): SemanticJobState.RETRY,
    (SemanticJobState.RUNNING, SemanticJobEvent.FAIL): SemanticJobState.FAILED,
    (SemanticJobState.RUNNING, SemanticJobEvent.RELEASE): SemanticJobState.RETRY,
    (SemanticJobState.RUNNING, SemanticJobEvent.LEASE_EXPIRED): SemanticJobState.RETRY,
    (SemanticJobState.PENDING, SemanticJobEvent.SUPERSEDE): SemanticJobState.SUPERSEDED,
    (SemanticJobState.RETRY, SemanticJobEvent.SUPERSEDE): SemanticJobState.SUPERSEDED,
    (SemanticJobState.RUNNING, SemanticJobEvent.SUPERSEDE): SemanticJobState.SUPERSEDED,
    (SemanticJobState.FAILED, SemanticJobEvent.RESET_FAILED): SemanticJobState.PENDING,
}

_JOB_KINDS = frozenset(
    "intrinsic context synthesis taxonomy_proposal taxonomy_review "
    "pattern_assessment pattern_review fresh_proposal fresh_adjudication "
    "fresh_comparison fresh_review".split()
)


def semantic_job_transition(current: str, event: str) -> str:
    """Return the only valid next state or fail before persistence changes."""

    try:
        state = SemanticJobState(current)
        transition_event = SemanticJobEvent(event)
    except ValueError as exc:
        raise ValueError(f"Unknown semantic job transition: {current} + {event}") from exc
    target = _TRANSITIONS.get((state, transition_event))
    if target is None:
        raise ValueError(
            f"Invalid semantic job transition: {state.value} + {transition_event.value}"
        )
    return target.value


def semantic_job_bulk_transition(currents: Iterable[str], event: str) -> str:
    """Return the shared target for a guarded multi-state persistence update."""

    targets = {semantic_job_transition(current, event) for current in currents}
    if not targets:
        raise ValueError("A semantic job bulk transition requires at least one source state")
    if len(targets) != 1:
        choices = ", ".join(sorted(targets))
        raise ValueError(f"Semantic job bulk transition has multiple targets: {choices}")
    return targets.pop()


def semantic_scope_status(job_kind: str, *, failed: bool = False) -> str:
    """Return the durable scope state associated with one semantic job kind."""

    if job_kind not in _JOB_KINDS:
        raise ValueError(f"Unknown semantic job kind: {job_kind}")
    family = job_kind.split("_", 1)[0] if failed else job_kind
    return f"{'failed' if failed else 'pending'}_{family}"


FAILED_SEMANTIC_SCOPE_STATES = frozenset(
    semantic_scope_status(kind, failed=True) for kind in _JOB_KINDS
)
