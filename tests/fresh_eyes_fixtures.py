"""Deterministic fresh-eyes stage responses shared by semantic tests."""

from __future__ import annotations


def agent_fresh_eyes(request: dict, kind: str) -> dict:
    design = _reference_design()
    if kind == "fresh_proposal":
        return _proposal(design)
    if kind == "fresh_adjudication":
        return _adjudication(request, design)
    if kind == "fresh_comparison":
        return _comparison()
    return _review(request)


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


def _review(request: dict) -> dict:
    """Vary the review by generation so two reruns can be compared, as two models would differ."""

    generation = _review_generation(request)
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
            },
            *_rerun_recommendations(generation),
        ],
        "rejected_ideas": [_rejected_idea(generation)],
        "sequence": ["Verify behavior", "Consolidate one path", "Run lifecycle tests"],
        "caveats": ["The recommendation remains optional."],
        "confidence": 0.74,
        "evidence": ["mission-filtered-comparison"],
    }


def _review_generation(request: dict) -> int:
    return int((request.get("input_manifest") or {}).get("review_generation") or 1)


def _rerun_recommendations(generation: int) -> list[dict]:
    """A rerun proposes two more changes: one the first review rejected, and one only it names."""

    if generation < 2:
        return []
    return [
        _rerun_recommendation(
            2,
            "Add a general workflow engine",
            "split",
            "Run every reasoning stage on one durable engine.",
            "semantic_runner.py drives every reasoning stage",
        ),
        _rerun_recommendation(
            3,
            "Bound the working tree drift window",
            "move",
            "Report trustworthy evidence for a live checkout.",
            "scan_persistence.py records the working tree fingerprint",
        ),
    ]


def _rerun_recommendation(
    rank: int, title: str, action: str, capability: str, contract: str
) -> dict:
    return {
        "rank": rank,
        "title": title,
        "action": action,
        "mission_capability": capability,
        "current_evidence": ["comparison:duplicate-flow"],
        "reference_insight": "A rerun reads the same evidence with different words.",
        "smallest_change": "Make the smallest change that keeps the behavior.",
        "expected_benefit": "One fewer way for the same behavior to differ.",
        "expected_deletions": [],
        "protected_behavior": ["Read-only repository analysis"],
        "affected_contracts": [contract],
        "risks": ["The rerun may weigh the same evidence differently."],
        "counter_evidence": [],
        "reasons_not_to_proceed": [],
        "dependencies": [],
        "verification": ["Run semantic lifecycle tests."],
        "reversible": True,
        "confidence": 0.6,
    }


def _rejected_idea(generation: int) -> dict:
    """The first review rejects exactly what a rerun goes on to recommend."""

    if generation < 2:
        return {
            "idea": "Add a general workflow engine to run every reasoning stage",
            "reason": "The fixed sequence does not justify one.",
            "evidence": ["capability:bounded-review"],
        }
    return {
        "idea": "Cache every reasoning stage result in memory",
        "reason": "Durable documents already answer a repeated read.",
        "evidence": ["capability:bounded-review"],
    }
