"""Deterministic fresh-eyes responses and a two-executor harness shared by semantic tests."""

from __future__ import annotations

from typing import Any

from semantic_support import _agent_dossier, _enable_agent_semantics

from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine

CODEX_EXECUTOR = "cli:codex:1"
CLAUDE_EXECUTOR = "cli:claude:2"
TWO_EXECUTORS = (CODEX_EXECUTOR, CLAUDE_EXECUTOR)
_IDLE_STATES = {"complete", "busy", "waiting", "waiting_for_executor"}


class TwoExecutorReview:
    """Drive one semantic queue with two host-worker identities and independent claim loops.

    Every claim uses a ``cli:<family>:<pid>`` identity exactly as two concurrent
    ``anaxigraph understand`` processes would, so a test can hold one executor's lease while the
    other claims, submit both, or alternate the two loops until each is told the queue is complete.
    """

    def __init__(
        self,
        engine: Any,
        repository_id: int,
        repository: Any,
        config: Any,
        *,
        dossier_factory: Any = _agent_dossier,
        executors: tuple[str, ...] = TWO_EXECUTORS,
        agent_model: str = "fixture-model",
    ) -> None:
        self.engine = engine
        self.repository_id = repository_id
        self.repository = repository
        self.config = config
        self.dossier_factory = dossier_factory
        self.executors = tuple(executors)
        self.agent_model = agent_model
        self.claims: list[dict[str, Any]] = []

    def claim(self, executor: str) -> dict[str, Any]:
        """Claim once as ``executor`` and record what the queue answered."""
        packet = self.engine.claim_agent_work(
            self.repository_id,
            self.repository,
            self.config,
            agent_id=executor,
            agent_model=self.agent_model,
        )
        self.claims.append(
            {
                "executor": executor,
                "status": packet["status"],
                "kind": (packet.get("job") or {}).get("kind"),
                "request": packet.get("analysis_request"),
            }
        )
        return packet

    def submit(self, packet: dict[str, Any]) -> dict[str, Any]:
        """Submit the deterministic fixture result for a claimed work packet."""

        return self.engine.submit_agent_work(
            self.repository_id,
            self.repository,
            self.config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=self.dossier_factory(packet["analysis_request"]),
        )

    def hold_one_each(self, kind: str) -> dict[str, dict[str, Any]]:
        """Let every executor claim one ``kind`` job and keep all of those leases open."""
        held = {}
        for executor in self.executors:
            packet = self.claim(executor)
            assert packet["status"] == "work", packet
            assert packet["job"]["kind"] == kind, packet["job"]
            held[executor] = packet
        return held

    def submit_all(self, held: dict[str, dict[str, Any]]) -> None:
        for packet in held.values():
            self.submit(packet)

    def run_until_complete(self, *, limit: int = 500) -> list[tuple[str, str]]:
        """Alternate the executors' claim loops until each is told the queue is complete."""
        kinds: list[tuple[str, str]] = []
        finished: set[str] = set()
        for index in range(limit):
            executor = self.executors[index % len(self.executors)]
            packet = self.claim(executor)
            if packet["status"] == "work":
                finished.clear()
                kinds.append((executor, packet["job"]["kind"]))
                self.submit(packet)
                continue
            assert packet["status"] in _IDLE_STATES, packet
            if packet["status"] == "complete":
                finished.add(executor)
                if finished == set(self.executors):
                    return kinds
        raise AssertionError("Semantic work did not converge for the two executors")


def baseline_review(repository: Any, database: Any) -> TwoExecutorReview:
    """Complete the baseline understanding with both host executors, ready for one review."""

    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    review = TwoExecutorReview(SemanticEngine(database), stats.repository_id, repository, config)
    baseline = review.run_until_complete()
    assert {executor for executor, _ in baseline} == set(TWO_EXECUTORS)
    return review


def prepared_review(repository: Any, database: Any, **start: Any) -> TwoExecutorReview:
    """Finish the baseline, then start one fresh-eyes review for both executors to share."""

    review = baseline_review(repository, database)
    started = review.engine.start_fresh_eyes_review(
        review.repository_id, review.repository, review.config, **start
    )
    assert started["status"] == "started", started
    return review
