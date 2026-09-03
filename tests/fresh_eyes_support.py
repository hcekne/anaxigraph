"""Deterministic fresh-eyes responses and a two-executor harness shared by semantic tests."""

from __future__ import annotations

from typing import Any

CODEX_EXECUTOR = "cli:codex:1"
CLAUDE_EXECUTOR = "cli:claude:2"
TWO_EXECUTORS = (CODEX_EXECUTOR, CLAUDE_EXECUTOR)
_IDLE_STATES = {"complete", "busy", "waiting"}


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
        executors: tuple[str, ...] = TWO_EXECUTORS,
        agent_model: str = "fixture-model",
    ) -> None:
        self.engine = engine
        self.repository_id = repository_id
        self.repository = repository
        self.config = config
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
        # semantic_support imports this module, so the dossier factory is resolved lazily.
        from semantic_support import _agent_dossier

        return self.engine.submit_agent_work(
            self.repository_id,
            self.repository,
            self.config,
            job_id=packet["job"]["id"],
            lease_token=packet["lease"]["token"],
            dossier=_agent_dossier(packet["analysis_request"]),
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


def agent_fresh_eyes(request: dict, kind: str) -> dict:
    design = _reference_design()
    if kind == "fresh_proposal":
        return _proposal(design)
    if kind == "fresh_adjudication":
        return _adjudication(request, design)
    if kind == "fresh_comparison":
        return _comparison()
    return _review()


def _reference_design() -> dict:
    return {
        "summary": "A small responsibility-led design for the supplied capabilities.",
        "components": [
            {
                "key": "repository-understanding",
                "name": "Repository understanding",
                "responsibility": "Explain the software and preserve evidence for guidance.",
                "collaborators": ["architecture guidance"],
                "extension_points": ["additional evidence readers"],
            },
            {
                "key": "architecture-guidance",
                "name": "Architecture guidance",
                "responsibility": "Turn understanding into bounded improvement advice.",
                "collaborators": ["repository understanding"],
                "extension_points": ["additional recommendation checks"],
            },
        ],
        "information_flows": [
            {
                "name": "Understand then guide",
                "steps": ["Read evidence", "Explain capabilities", "Recommend a small change"],
                "rationale": "Advice should follow evidence-backed understanding.",
            }
        ],
        "boundary_rules": ["Guidance consumes saved understanding and does not edit source."],
        "operating_model": ["A principal requests work and an external agent supplies reasoning."],
        "extension_strategy": ["Add evidence readers behind the existing understanding boundary."],
        "patterns": [
            {
                "name": "Ports and adapters",
                "purpose": "Keep external agent execution separate from durable knowledge.",
                "tradeoffs": ["Adds a small boundary but avoids provider lock-in."],
            }
        ],
        "simplifications": ["Use one durable task mechanism for every reasoning stage."],
        "tradeoffs": ["Sequential evidence checks favor trust over minimum latency."],
        "assumptions": ["Repository evidence is available before guidance is requested."],
        "unknowns": ["The largest intended repository size is not stated."],
    }


def _proposal(design: dict) -> dict:
    return {
        "contract_version": "fresh-eyes-proposal-v1",
        "design": design,
        "isolation": {
            "requested": "fresh_context",
            "status": "self_reported",
            "note": "The fixture treats each work claim as a fresh session.",
        },
        "confidence": 0.8,
        "evidence": ["capability:repository-map"],
    }


def _adjudication(request: dict, design: dict) -> dict:
    return {
        "contract_version": "fresh-eyes-adjudication-v1",
        "summary": "The proposals agree on a small evidence-to-guidance flow.",
        "shared_ground": ["Keep reasoning separate from stored evidence."],
        "disagreements": [
            {
                "topic": "Extension mechanism",
                "positions": ["Explicit adapters", "A smaller direct boundary"],
                "adjudication": "Start with the direct boundary and extract only with evidence.",
                "preserved_alternative": "Adapters remain appropriate for multiple providers.",
            }
        ],
        "common_blind_spots": ["Neither proposal knows current migration constraints."],
        "proposal_assessments": [
            {
                "proposal": item["proposal"],
                "strengths": ["Small responsibility set"],
                "weaknesses": ["Migration cost is unknown"],
            }
            for item in request["proposals"]
        ],
        "reference_design": design,
        "confidence": 0.82,
        "evidence": ["proposal:shared-ground"],
    }


def _comparison() -> dict:
    return {
        "contract_version": "fresh-eyes-comparison-v1",
        "summary": "The current system already has the core boundary but can simplify one area.",
        "mappings": [
            {
                "reference_responsibility": "Repository understanding",
                "current_responsibilities": ["Understanding"],
                "classification": "already_satisfies",
                "explanation": "The current Charter shows the same responsibility.",
                "evidence": ["charter:understanding"],
                "counter_evidence": [],
                "migration_cost": "none",
            }
        ],
        "current_strengths": ["Source remains read-only during analysis."],
        "candidate_changes": [
            {
                "title": "Consolidate duplicate orchestration",
                "classification": "useful_simplification",
                "explanation": "One durable path can serve the same capability.",
                "affected_responsibilities": ["Understanding"],
                "evidence": ["comparison:duplicate-flow"],
                "counter_evidence": ["Separate paths may isolate failures."],
                "migration_cost": "low",
            }
        ],
        "unknowns": ["Runtime behavior still needs verification."],
        "confidence": 0.76,
        "evidence": ["reference-to-current-map"],
    }


def _review() -> dict:
    return {
        "contract_version": "fresh-eyes-review-v1",
        "summary": "Keep the sound boundary and test one small consolidation.",
        "mission_alignment": "The change makes architecture guidance simpler without new concepts.",
        "recommendations": [
            {
                "rank": 1,
                "title": "Consolidate duplicate orchestration",
                "action": "consolidate",
                "mission_capability": "Explain and guide repository changes.",
                "current_evidence": ["comparison:duplicate-flow"],
                "reference_insight": "One durable reasoning path is sufficient.",
                "smallest_change": "Route both callers through the existing durable path.",
                "expected_benefit": "Less code and one behavior to verify.",
                "expected_deletions": ["The redundant orchestration branch"],
                "protected_behavior": ["Read-only repository analysis"],
                "affected_contracts": ["Semantic work execution"],
                "risks": ["A caller may rely on different retry behavior."],
                "counter_evidence": ["Separate paths may isolate failures."],
                "reasons_not_to_proceed": ["Do not proceed if retry behavior differs."],
                "dependencies": [],
                "verification": ["Run semantic lifecycle tests."],
                "reversible": True,
                "confidence": 0.74,
            }
        ],
        "rejected_ideas": [
            {
                "idea": "Add a general workflow engine",
                "reason": "The fixed sequence does not justify one.",
                "evidence": ["capability:bounded-review"],
            }
        ],
        "sequence": ["Verify behavior", "Consolidate one path", "Run lifecycle tests"],
        "caveats": ["The recommendation remains optional."],
        "confidence": 0.74,
        "evidence": ["mission-filtered-comparison"],
    }
