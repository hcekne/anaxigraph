from __future__ import annotations

import json

from anaxigraph.semantic_file_language import semantic_file_explanation
from anaxigraph.semantic_taxonomy_language import (
    semantic_taxonomy_assignment_explanation,
    semantic_taxonomy_explanation,
)


def test_legacy_ai_templates_are_rewritten_as_the_main_explanation():
    result = semantic_file_explanation(
        "Dockerfile",
        {
            "status": "current",
            "summary": "Builds the container used to run AnaxiGraph.",
            "architecture_role": (
                "Container distribution and runtime-security boundary for deploying the service. "
                "Contextually connected to 2 sampled dependencies and 1 sampled consumers."
            ),
            "placement_guidance": (
                "Keep work matching this role here: Container distribution and runtime-security "
                "boundary for deploying the service.. Place unrelated behavior in its owning "
                "focused layer."
            ),
            "change_summary": (
                "Contextual synthesis from the intrinsic dossier, 3 resolved relationship "
                "records, 2 unique neighbour dossiers, and 1 evidence pages."
            ),
            "responsibilities": ["Own release orchestration."],
            "extension_points": ["Add a new runtime behind the architectural boundary."],
            "risks": ["The intrinsic dossier may be old."],
            "confidence": 0.9,
        },
    )

    assert result["version"] == "semantic-file-explanation-v4"
    assert result["what_this_file_does"] == "Builds the container used to run AnaxiGraph."
    assert result["role_in_repository"] == (
        "Container build and release file that controls how the running service is isolated and "
        "protected for deploying the service."
    )
    assert result["related_file_evidence"] == (
        "The AI description compared 2 related files this file uses and 1 related file that uses "
        "this file."
    )
    assert result["where_related_work_belongs"].startswith("Add work here when it has the same job")
    assert result["what_changed_in_description"] == (
        "The AI updated this description by combining the file's own description with 3 direct "
        "code links, 2 descriptions of related files, and 1 additional page of code facts."
    )
    assert result["jobs"] == ["Own release coordination."]
    assert result["places_for_adding_behavior"] == [
        "Add a new runtime behind the intended separation between repository areas."
    ]
    assert result["risks_and_uncertainty"] == [
        "The description based only on this file may be old."
    ]

    rendered = json.dumps(result).lower()
    for unexplained in (
        "contextual synthesis",
        "intrinsic dossier",
        "sampled dependencies",
        "sampled consumers",
        "owning focused layer",
        "orchestration",
        "architectural boundary",
    ):
        assert unexplained not in rendered


def test_missing_or_newer_semantic_copy_stays_honest():
    pending = semantic_file_explanation("src/app.py", {"status": "pending_intrinsic"})
    assert "incomplete or waiting" in pending["conclusion"]
    assert pending["jobs"] == []
    assert pending["evidence_strength"]["value"] == 0.0

    current = semantic_file_explanation(
        "src/app.py",
        {
            "status": "current",
            "architecture_role": "Runs the command-line application.",
            "placement_guidance": "Add command behavior here.",
            "change_summary": "The command gained a readable error message.",
            "confidence": 0.8,
        },
    )
    assert current["role_in_repository"] == "Runs the command-line application."
    assert current["where_related_work_belongs"] == "Add command behavior here."
    assert current["what_changed_in_description"] == (
        "The command gained a readable error message."
    )
    assert "not state how many" in current["related_file_evidence"]

    named_code = semantic_file_explanation(
        "src/dossier.py",
        {"status": "current", "architecture_role": "Runs DossierService."},
    )
    assert named_code["role_in_repository"] == "Runs DossierService."

    technical = semantic_file_explanation(
        "src/http_bridge.py",
        {
            "status": "current",
            "summary": "Connects HTTP requests to saved repository information.",
            "architecture_role": (
                "HTTP adapter at the persistence contract boundary and semantic service facade."
            ),
        },
    )
    role = technical["role_in_repository"]
    assert "“adapter” means code that translates between two parts" in role
    assert "“persistence” means saving and loading data" in role
    assert "“contract” means behavior or data that other code relies on" in role
    assert "“boundary” means the place where one part hands work or data to another" in role
    assert "“semantic” means based on saved descriptions of what code means and does" in role
    assert "“facade” means a small public entry point that hides internal details" in role
    projected_again = semantic_file_explanation(
        "src/http_bridge.py",
        {"status": "current", "architecture_role": role},
    )
    assert projected_again["role_in_repository"] == role

    already_defined = semantic_file_explanation(
        "src/format.py",
        {
            "status": "current",
            "architecture_role": (
                "Owns the schema, meaning the rules for the shape of exchanged data."
            ),
        },
    )
    assert already_defined["role_in_repository"].count("“schema” means") == 0

    marketplace = semantic_file_explanation(
        ".agents/plugins/marketplace.json",
        {
            "status": "current",
            "architecture_role": (
                "Distribution metadata at the agent-integration boundary, connecting the "
                "packaged plugin to local marketplace discovery."
            ),
        },
    )
    assert "Distribution metadata" in marketplace["role_in_repository"]
    assert (
        "“boundary” means the place where one part hands work or data to another"
        in marketplace["role_in_repository"]
    )
    assert (
        "“metadata” means information that describes other data"
        in marketplace["role_in_repository"]
    )

    hosted_checks = semantic_file_explanation(
        ".github/workflows/ci.yml",
        {
            "status": "current",
            "architecture_role": (
                "Hosted verification pipeline defining repository and release-readiness contracts."
            ),
        },
    )
    assert "Hosted verification pipeline" in hosted_checks["role_in_repository"]
    assert (
        "“contract” means behavior or data that other code relies on"
        in hosted_checks["role_in_repository"]
    )
    assert (
        "“pipeline” means an ordered sequence of automated steps"
        in hosted_checks["role_in_repository"]
    )

    group_language = semantic_taxonomy_explanation(
        {
            "label": "Persistence & Repository Projections",
            "level": "area",
            "description": "Persistence adapters and schema contracts.",
            "responsibility": "Save and load repository facts.",
            "rationale": "Cluster-5 is centered on one persistence lifecycle.",
            "confidence": 0.8,
        }
    )
    assert group_language["version"] == "semantic-taxonomy-explanation-v2"
    assert group_language["display_name"] == "Saved data and repository views"
    assert (
        "“adapter” means code that translates between two parts"
        in group_language["what_belongs_here"]
    )
    assert "“schema” means rules for the shape" in group_language["what_belongs_here"]
    assert "Cluster-5" not in group_language["why_these_files_are_together"]
    assert (
        "“lifecycle” means the steps from creation"
        in group_language["why_these_files_are_together"]
    )
    assert "not a grade for the files" in group_language["evidence_strength"]["meaning"]

    placement = semantic_taxonomy_assignment_explanation(
        {
            "area_name": "Repository Intelligence Core",
            "subsystem_name": "Persistence & Repository Projections",
            "confidence": 0.8,
            "locked": False,
        }
    )
    assert placement["conclusion"] == (
        "The AI-created map places this file in Saved data and repository views, inside "
        "Repository Intelligence Core."
    )
    assert "saved description and direct code links" in placement["why_this_file_is_here"]

    generic_name = semantic_taxonomy_explanation({"label": "Persistence Boundary"})
    assert generic_name["display_name"] == "Saved data handoff"
    assert "In this description" not in generic_name["conclusion"]
