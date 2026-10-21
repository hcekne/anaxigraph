"""Architecture plan responses for real queue, transport and portability tests."""

from semantic_support import _agent_dossier


def planning_dossier(request):
    if request.get("analysis_kind") != "architecture_plan":
        return _agent_dossier(request)
    current = {
        "nodes": [
            {
                "key": "domain",
                "label": "Calculation domain",
                "responsibility": "Calculate values",
                "paths": ["pkg/core.py"],
                "evidence": ["pkg/core.py"],
            }
        ],
        "edges": [],
        "unknowns": ["Deployment topology is not established."],
    }
    milestone = {
        "key": "reuse-owner",
        "title": "Extend the existing owner",
        "outcome": "Keep arithmetic in the domain service",
        "owners": ["pkg/core.py"],
        "affected_contracts": ["Calculator.calculate"],
        "depends_on": [],
        "verification": ["Run tests/test_core.py"],
        "rollback": "Revert the focused domain change",
        "evidence": ["pkg/core.py", "tests/test_core.py"],
    }
    return {
        "contract_version": "architecture-plan-v1",
        "summary": "Evolve the existing domain boundary",
        "direction": request["direction"],
        "assumptions": [],
        "current": current,
        "options": [
            {
                "key": "preserve",
                "strategy": "preserve",
                "title": "Preserve current architecture",
                "summary": "Keep the supported domain boundary",
                "benefits": ["No migration"],
                "costs": [],
                "risks": [],
                "evidence": ["pkg/core.py"],
                "target": current,
                "milestones": [],
            },
            {
                "key": "evolve",
                "strategy": "evolve",
                "title": "Evolve the existing owner",
                "summary": "Reuse the current service with focused verification",
                "benefits": ["One owner for arithmetic"],
                "costs": ["Focused implementation and tests"],
                "risks": ["Callers may depend on current behavior"],
                "evidence": ["pkg/core.py"],
                "target": current,
                "milestones": [milestone],
            },
        ],
        "selected_option": "evolve",
        "selection_rationale": "The existing owner and tests provide a small reversible path",
        "disagreements": [],
        "evidence": ["pkg/core.py"],
        "confidence": 0.8,
    }
