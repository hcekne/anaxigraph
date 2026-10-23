"""Functional charter response shared by deterministic semantic providers."""


def _agent_charter() -> dict:
    def claim(statement: str) -> dict:
        return {
            "statement": statement,
            "evidence": ["supplied repository descriptions"],
            "counter_evidence": [],
            "confidence": 0.85,
        }

    def item(key: str, name: str, statement: str) -> dict:
        return {
            "key": key,
            "name": name,
            "statement": statement,
            "related": [],
            "entry_points": [],
            "evidence": ["supplied repository descriptions"],
            "counter_evidence": [],
            "confidence": 0.85,
        }

    return {
        "contract_version": "architecture-charter-v1",
        "purpose": claim("Help people understand and improve a software repository."),
        "actors": [item("developer", "Developer", "Uses the repository map to guide changes.")],
        "capabilities": [item("repository-map", "Repository map", "Explains saved code behavior.")],
        "responsibilities": [
            item("understanding", "Understanding", "Keeps code explanations current.")
        ],
        "execution_flows": [
            item("inspect", "Inspect", "A user requests and receives an explanation.")
        ],
        "public_contracts": [
            item(
                "saved-evidence",
                "Saved evidence",
                "Saved explanations remain tied to indexed evidence.",
            )
        ],
        "invariants": [
            item(
                "read-only-source",
                "Read-only source",
                "Repository source remains read-only during analysis.",
            )
        ],
        "extension_points": [],
        "patterns": [],
        "coherence_concerns": [],
        "unknowns": [],
        "conflicts": [],
        "capability_brief": {
            "contract_version": "capability-brief-v1",
            "purpose": "Help people understand and improve a software repository.",
            "actors": ["A person or coding agent planning a software change."],
            "observable_capabilities": [
                "Explain what the software does and how its parts cooperate."
            ],
            "user_journeys": ["Ask where a change belongs and receive evidence-backed guidance."],
            "external_interfaces": [
                "A dashboard, command line, and agent tool expose the same understanding."
            ],
            "non_functional_requirements": ["Analysis does not modify the inspected repository."],
            "compatibility_obligations": [],
            "non_goals": ["It does not edit source code by itself."],
            "unknowns": [],
            "evidence": ["indexed repository behavior"],
            "confidence": 0.85,
        },
        "confidence": 0.85,
        "evidence": ["supplied repository descriptions"],
    }
