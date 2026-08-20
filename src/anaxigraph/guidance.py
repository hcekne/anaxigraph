"""Shared, plain-language product vocabulary for humans and coding agents."""

from __future__ import annotations

from typing import Any

FINDING_STATUSES = {
    "new": {
        "label": "New",
        "meaning": "Detected by the latest complete scan and not yet reviewed.",
        "next": ["acknowledged", "planned", "dismissed"],
    },
    "acknowledged": {
        "label": "Reviewed",
        "meaning": "A person reviewed the signal; it remains active and monitored.",
        "next": ["planned", "dismissed"],
    },
    "accepted": {
        "label": "Accepted risk",
        "meaning": "The condition is understood and intentionally retained for now.",
        "next": ["planned", "dismissed"],
    },
    "planned": {
        "label": "Planned for agent",
        "meaning": "A person approved this as engineering work; agents can query the planned queue.",
        "next": ["acknowledged", "dismissed"],
    },
    "dismissed": {
        "label": "Not actionable",
        "meaning": "The signal is a false positive, irrelevant, or an intentional exception.",
        "next": ["acknowledged", "planned"],
    },
    "resolved": {
        "label": "Verified resolved",
        "meaning": "A later scan no longer detected the condition.",
        "next": [],
    },
    "regressed": {
        "label": "Regressed",
        "meaning": "A condition that had resolved was detected again.",
        "next": ["acknowledged", "planned", "dismissed"],
    },
}

OVERLAYS = {
    "architecture": (
        "Color shows the effective architecture group. Configured path rules win; path/runtime "
        "inference is used only as a fallback. Translucent regions are parent architecture areas "
        "and can stay visible beneath any metric overlay."
    ),
    "coupling": (
        "Hotter modules have more incoming and outgoing dependencies. High coupling means a "
        "change may reach more of the repository; it is not automatically bad."
    ),
    "complexity": (
        "Hotter modules contain more detected decision branches. Use this to find inspection "
        "targets, then judge cohesion and tests before refactoring."
    ),
    "coverage": (
        "Green modules have higher imported line coverage; red modules have lower coverage. Grey "
        "means no matching coverage artifact was imported, not zero coverage."
    ),
    "change": (
        "Hotter modules appear in more recent Git history records and may be active change "
        "hotspots."
    ),
    "dead-code": (
        "Amber modules have no detected incoming static dependency and are old enough to inspect. "
        "Dynamic runtime use has not been ruled out."
    ),
    "agent": (
        "After planning a task, green is recommended context, amber is a protected boundary, and "
        "red is also changed by another branch. Before a task is planned this overlay is neutral."
    ),
    "drift": (
        "Red means the configured architecture group differs from the path/runtime fallback. It "
        "asks whether policy, placement, or responsibility is stale; it does not prove a defect."
    ),
}

AGENT_WORKFLOW = {
    "scope": (
        "Describe a coding goal to find a bounded set of likely implementation files, connected "
        "modules, tests, protected boundaries, applicable rules, and known findings."
    ),
    "impact": (
        "Name a file or symbol before changing it to find direct and indirect code that depends on "
        "it, relevant tests, migrations, protected paths, and branch collisions."
    ),
    "planned_queue": (
        "A human plans a finding in the dashboard. An agent calls ANAXIGRAPH_FINDINGS with "
        "status='planned', then ANAXIGRAPH_FINDING_CONTEXT for the selected finding before editing."
    ),
    "semantic_memory": (
        "Call ANAXIGRAPH_SEMANTIC_STATUS to see whether model-backed repository understanding is "
        "current. ANAXIGRAPH_SCOPE includes compact pattern and placement advice for a coding "
        "goal; ANAXIGRAPH_FILE exposes the complete versioned dossier and its provenance. When "
        "the repository explicitly uses semantic.provider: agent, call "
        "ANAXIGRAPH_SEMANTIC_SCHEMA once and repeat WORK, optional EVIDENCE pages, and SUBMIT to "
        "build that memory with the connected coding agent's own model and tokens."
    ),
}


def product_glossary() -> dict[str, Any]:
    return {
        "product": {
            "anaxigraph": "The dashboard, analysis engine, and overall open-source project.",
            "anaxi_index": (
                "The persistent repository knowledge store for modules, relationships, intent, "
                "findings, and history."
            ),
            "anaxi_mcp": "The MCP interface that gives coding agents scoped access to AnaxiIndex.",
        },
        "architecture": {
            "hierarchy": ["repository", "area", "subsystem", "module", "symbol"],
            "declared_group": (
                "A repository-policy path rule assigned this module to a named responsibility."
            ),
            "inferred_group": (
                "A lower-confidence fallback derived from path and runtime conventions when no "
                "configured group matched."
            ),
            "group_rollup": (
                "Child groups remain separate for dependency rules but are totalled under their "
                "parent area in the overview."
            ),
        },
        "findings": {
            "definition": (
                "A persistent, evidence-backed condition produced by a rule. It is an inspection "
                "signal rather than proof that code must change."
            ),
            "confidence": (
                "Confidence describes how directly the detector observed the condition; it does "
                "not measure severity or the chance that a refactor is worthwhile."
            ),
            "statuses": FINDING_STATUSES,
        },
        "overlays": OVERLAYS,
        "agents": AGENT_WORKFLOW,
        "coverage": {
            "missing": (
                "No configured coverage.xml or lcov.info matched this snapshot. Missing coverage "
                "input is kept distinct from measured 0% coverage."
            )
        },
    }
