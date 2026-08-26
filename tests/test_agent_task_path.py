from __future__ import annotations

from anaxigraph.agent_task_path import compact_task_path, task_path


def _module(source="AI-created map checked by a separate AI pass"):
    return {
        "path": "src/calculator.py",
        "summary": "Calculate invoice totals.",
        "declared_group": "billing-calculation",
        "incoming_paths": ["src/checkout.py"],
        "outgoing_paths": ["src/money.py"],
        "architecture_placement": {
            "area": "billing",
            "area_name": "Billing",
            "subsystem": "billing-calculation",
            "subsystem_name": "Billing calculations",
            "source": source,
            "why_here": "This file owns the calculation behavior used by checkout.",
        },
        "semantic": {
            "status": "current",
            "summary": "Calculate invoice totals.",
            "architecture_role": "Own invoice total calculations.",
            "responsibilities": ["Calculate invoice totals."],
            "public_contracts": ["Calculator.total returns money in the invoice currency."],
            "extension_points": ["Calculator.total"],
            "plain_language": {"what_this_file_does": "This file calculates invoice totals."},
        },
    }


def _hierarchy():
    return [
        {
            "name": "billing",
            "label": "Billing",
            "plain_language": {
                "display_name": "Billing",
                "what_this_group_does": "Own customer charges and invoices.",
                "why_these_files_are_together": "They all change how customers are charged.",
            },
            "children": [
                {
                    "name": "billing-calculation",
                    "label": "Billing calculations",
                    "plain_language": {
                        "display_name": "Billing calculations",
                        "what_this_group_does": "Calculate invoice amounts.",
                        "why_these_files_are_together": (
                            "They implement the same calculation rules."
                        ),
                    },
                    "children": [],
                }
            ],
        }
    ]


def _symbols():
    return [
        {
            "path": "src/calculator.py",
            "name": "Calculator",
            "symbol_type": "class",
            "signature": "class Calculator",
            "summary": "Invoice calculator",
            "start_line": 10,
            "end_line": 50,
        },
        {
            "path": "src/calculator.py",
            "name": "format_receipt",
            "symbol_type": "function",
            "signature": "format_receipt(value)",
            "summary": "Format output",
            "start_line": 55,
            "end_line": 65,
        },
    ]


def test_task_path_connects_goal_to_map_file_symbol_and_boundaries():
    module = _module()
    result = task_path(
        "Change Calculator behavior",
        module,
        [module, {"path": "src/tax.py"}],
        _symbols(),
        ["tests/test_calculator.py"],
        _hierarchy(),
    )

    assert result["contract_version"] == "task-path-v1"
    assert result["status"] == "semantic_with_symbols"
    assert result["area"]["responsibility"] == "Own customer charges and invoices."
    assert result["subsystem"]["responsibility"] == "Calculate invoice amounts."
    assert result["module"]["contracts_to_preserve"] == [
        "Calculator.total returns money in the invoice currency."
    ]
    assert result["module"]["callers_to_check"] == ["src/checkout.py"]
    assert result["module"]["dependencies_to_check"] == ["src/money.py"]
    assert result["module"]["focused_tests"] == ["tests/test_calculator.py"]
    assert [item["name"] for item in result["symbols"]] == ["Calculator"]
    assert {item["path"] for item in result["nearby_files"]} == {
        "src/tax.py",
        "src/checkout.py",
        "src/money.py",
    }
    assert "Billing → Billing calculations" in result["plain_language"]["conclusion"]

    compact = compact_task_path(result)
    assert compact["module"]["path"] == "src/calculator.py"
    assert compact["symbols"][0]["name"] == "Calculator"


def test_project_rule_path_does_not_invent_a_matching_symbol():
    module = _module(source="project path rule")

    result = task_path(
        "Change unrelated behavior",
        module,
        [module],
        _symbols(),
        [],
        _hierarchy(),
    )

    assert result["status"] == "policy_module_only"
    assert result["symbols"] == []
    assert result["module"]["path"] in result["plain_language"]["conclusion"]


def test_task_path_does_not_replace_a_matching_preferred_file_with_a_signature_heavy_file():
    preferred = _module()
    preferred["path"] = "src/architecture_verification.py"
    alternative = _module()
    alternative["path"] = "src/architecture_rules.py"
    symbols = [
        {
            "path": preferred["path"],
            "name": "compare_verification_baselines",
            "symbol_type": "function",
            "signature": "compare_verification_baselines(before, after)",
            "start_line": 10,
        },
        {
            "path": alternative["path"],
            "name": "build_architecture_decision",
            "symbol_type": "function",
            "signature": (
                "build_architecture_decision(verification_baseline, structural_dependency_cycle)"
            ),
            "start_line": 10,
        },
        {
            "path": alternative["path"],
            "name": "missing_change_coupling",
            "symbol_type": "function",
            "signature": "missing_change_coupling(verification_baseline)",
            "start_line": 20,
        },
    ]

    result = task_path(
        ("Verify whether a change improved structure without making dependencies more tangled"),
        preferred,
        [preferred, alternative],
        symbols,
        [],
        _hierarchy(),
    )

    assert result["module"]["path"] == preferred["path"]
    assert [item["name"] for item in result["symbols"]] == ["compare_verification_baselines"]


def test_task_path_refuses_to_invent_a_route_without_a_starting_file():
    result = task_path("Add invoice behavior", {}, [], [], [], [])

    assert result["status"] == "no_starting_file"
    assert result["module"] == {}
    assert "could not tie" in result["plain_language"]["conclusion"]
