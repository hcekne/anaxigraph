from __future__ import annotations

import argparse

from anaxigraph.api import create_app
from anaxigraph.cli_parser import create_parser
from anaxigraph.guidance import FINDING_VIEWS, OVERLAYS, product_glossary


def test_graph_help_explains_measurements_without_old_metric_jargon():
    copy = " ".join(OVERLAYS.values()).lower()

    for unexplained_label in (
        "modules",
        "high coupling",
        "metric overlay",
        "path/runtime inference",
        "static reachability",
        "architecture drift",
    ):
        assert unexplained_label not in copy
    assert "direct code links" in OVERLAYS["coupling"]
    assert "does not prove a defect" in OVERLAYS["drift"]


def test_public_glossary_defines_the_saved_index_and_finding_views_concretely():
    glossary = product_glossary()

    assert glossary["product"]["anaxi_index"].startswith("The saved index")
    assert "between sessions" in glossary["product"]["anaxi_index"]
    assert FINDING_VIEWS["attention"].startswith("A short list")
    assert "pages keep a large list manageable" in FINDING_VIEWS["diagnostics"]
    assert "not a code-quality grade" in glossary["file_measurements"]["complexity"]
    assert "not a grade for the code" in glossary["file_measurements"]["attention_score"]


def test_coding_loop_contract_freezes_required_cli_rest_and_result_versions(repository, database):
    contract = product_glossary()["coding_loop"]
    parser = create_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    app = create_app(database=database, repository=repository, enable_mcp=False)
    operations = {
        f"{method.upper()} {path}"
        for path, path_item in app.openapi()["paths"].items()
        for method in path_item
    }

    assert contract["version"] == "coding-loop-contract-v3"
    assert (
        "Do not rebuild the AI map after every save"
        in contract["development_cadence"]["during_edits"]
    )
    assert "only changed AI scopes" in contract["development_cadence"]["after_a_coherent_change"][2]
    assert set(contract["cli_commands"]) <= set(subparsers.choices)
    assert set(contract["rest_operations"]) <= operations
    assert contract["versioned_results"] == {
        "scope.architecture_decision.contract_version": "architecture-decision-v1",
        "scope.architecture_decision.decomposition.contract_version": (
            "large-file-decomposition-v1"
        ),
        "patterns.contract_version": "pattern-query-v1",
        "pattern_candidates.contract_version": "pattern-candidate-query-v1",
        "graph_overview.contract_version": "graph-overview-v1",
        "graph_page.contract_version": "graph-query-v1",
        "finding_context.finding_history.contract_version": "finding-history-v1",
        "semantic_schema.schema_version": "repository-understanding-v5",
        "semantic_schema.writing_contract_version": "plain-language-v2",
        "scope.telemetry.contract_version": "action-telemetry-v1",
        "impact.telemetry.contract_version": "action-telemetry-v1",
        "semantic_status.telemetry.contract_version": "action-telemetry-v1",
    }
