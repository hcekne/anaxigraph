from __future__ import annotations

from anaxigraph.agent_decision import build_architecture_decision
from anaxigraph.agent_decomposition import compact_decomposition, decomposition_advice


def _module(*, recommendation="split", status="current", responsibilities=None, lines_of_code=620):
    return {
        "path": "src/config.py",
        "lines_of_code": lines_of_code,
        "incoming_paths": ["src/cli.py", "tests/test_config.py"],
        "outgoing_paths": ["src/models.py"],
        "semantic": {
            "status": status,
            "responsibilities": responsibilities
            or [
                "Load and validate configuration through load_config and parse_config",
                "Match paths through path_matches and normalize_path",
            ],
            "public_contracts": [
                "load_config returns validated settings",
                "path_matches keeps project path rules stable",
            ],
            "similar_modules": ["src/config_loader.py", "src/path_rules.py"],
            "consolidation_assessment": {
                "recommendation": recommendation,
                "score": 84,
                "rationale": "Configuration loading and path rules change for different reasons.",
                "candidates": ["src/config_loader.py", "src/path_rules.py"],
                "evidence": ["The file owns two separately named jobs."],
                "counter_evidence": ["Both jobs share the same settings format."],
            },
        },
    }


def _symbols():
    return [
        _symbol("load_config", 10, 45),
        _symbol("parse_config", 47, 75),
        _symbol("path_matches", 80, 110),
        _symbol("normalize_path", 112, 130),
    ]


def _symbol(name, start, end):
    return {
        "path": "src/config.py",
        "name": name,
        "qualified_name": f"config.{name}",
        "symbol_type": "function",
        "signature": f"{name}(value)",
        "summary": "",
        "start_line": start,
        "end_line": end,
    }


def _finding():
    return {
        "finding_type": "module_complexity",
        "affected_artifacts": ["src/config.py"],
        "summary": "src/config.py has 620 lines; this project reviews files above 500 lines",
        "plain_language": {"what": "src/config.py has 620 lines of code."},
    }


def _rules():
    return [
        {
            "type": "max_module_loc",
            "parameters": {"max": 500, "paths": ["src/**"]},
        }
    ]


def test_mixed_responsibility_file_gets_a_bounded_extraction_map():
    result = decomposition_advice(
        [_module()],
        _symbols(),
        ["tests/test_config.py"],
        [_finding()],
        [{"target": "src/config.py", "key": "god-module"}],
    )

    assert result["contract_version"] == "large-file-decomposition-v1"
    assert result["candidate_count"] == 1
    item = result["items"][0]
    assert item["status"] == "candidate"
    assert len(item["slices"]) == 2
    assert item["slices"][0]["destination"] == {
        "status": "existing_module",
        "path": "src/path_rules.py",
        "reason": "Its file name matches words in this responsibility.",
    }
    assert item["slices"][1]["destination"]["status"] == "remain_in_file"
    assert {symbol["name"] for part in item["slices"] for symbol in part["symbols"]} == {
        "load_config",
        "parse_config",
        "path_matches",
        "normalize_path",
    }
    assert item["callers_to_protect"] == ["src/cli.py", "tests/test_config.py"]
    assert item["focused_tests"] == ["tests/test_config.py"]
    assert item["evidence_against_split"]
    assert item["reviewed_patterns"] == ["god-module"]
    assert item["plain_language"]["version"] == "large-file-decomposition-v1"
    assert item["plain_language"]["reasons_not_to_split"]

    compact = compact_decomposition(result)
    assert compact["items"][0]["slices"][0]["symbol_names"] == [
        "path_matches",
        "normalize_path",
    ]


def test_decomposition_permits_a_new_sibling_only_without_an_existing_home():
    module = _module(
        responsibilities=[
            "Load and validate configuration through load_config and parse_config",
            "Publish audit events through publish_audit_event",
        ]
    )
    module["semantic"]["public_contracts"] = ["load_config returns validated settings"]
    symbols = [
        _symbol("load_config", 10, 45),
        _symbol("parse_config", 47, 75),
        _symbol("publish_audit_event", 80, 105),
    ]

    result = decomposition_advice([module], symbols, [], [_finding()], [])

    item = result["items"][0]
    candidate = item["slices"][0]
    assert [symbol["name"] for symbol in candidate["symbols"]] == ["publish_audit_event"]
    assert candidate["destination"] == {
        "status": "new_file_candidate",
        "path": "",
        "reason": (
            "No supplied existing module matches this job. Create a focused sibling file only "
            "after checking the architecture map for an honest extension point."
        ),
    }
    assert item["slices"][1]["destination"]["status"] == "remain_in_file"


def test_near_limit_mixed_file_gets_a_plan_before_it_breaks_the_rule():
    result = decomposition_advice(
        [_module(lines_of_code=445)],
        _symbols(),
        ["tests/test_config.py"],
        [],
        [],
        _rules(),
    )

    assert result["candidate_count"] == 1
    assert result["items"][0]["trigger"]["size_rule_active"] is False
    assert result["items"][0]["trigger"]["review_starts_at_lines"] == 400


def test_large_cohesive_file_is_explicitly_kept_together():
    module = _module(
        recommendation="keep",
        lines_of_code=445,
        responsibilities=["Load and validate all configuration through load_config"],
    )

    result = decomposition_advice([module], _symbols(), [], [], [], _rules())

    item = result["items"][0]
    assert item["status"] == "keep_together"
    assert item["slices"] == []
    assert "size alone" in item["plain_language"]["conclusion"]
    assert item["trigger"]["configured_maximum_lines"] == 500
    assert item["trigger"]["review_starts_at_lines"] == 400


def test_small_semantic_split_does_not_create_large_file_fragments():
    result = decomposition_advice(
        [_module(lines_of_code=169)],
        _symbols(),
        [],
        [],
        [],
        _rules(),
    )

    assert result["items"] == []
    assert result["candidate_count"] == 0


def test_stale_or_unmapped_semantic_evidence_cannot_invent_a_split():
    stale = decomposition_advice(
        [_module(status="pending_context")], _symbols(), [], [_finding()], []
    )["items"][0]
    unmapped = decomposition_advice(
        [_module()],
        [_symbol("unrelated_name", 1, 5)],
        [],
        [_finding()],
        [],
    )["items"][0]

    assert stale["status"] == "insufficient_evidence"
    assert "up-to-date AI description" in stale["reason"]
    assert unmapped["status"] == "insufficient_evidence"
    assert unmapped["slices"] == []
    assert unmapped["unassigned_symbols"] == ["unrelated_name"]


def test_symbol_that_matches_two_jobs_is_left_unassigned():
    ambiguous = _symbol("load", 1, 5)
    module = _module(
        responsibilities=[
            "Load configuration paths through load_config",
            "Load project paths through path_matches",
        ]
    )

    item = decomposition_advice([module], [ambiguous], [], [_finding()], [])["items"][0]

    assert item["status"] == "insufficient_evidence"
    assert item["unassigned_symbols"] == ["load"]


def test_architecture_decision_surfaces_decomposition_without_another_workflow():
    result = build_architecture_decision(
        snapshot_id=7,
        primary_files=[_module()],
        interfaces=[],
        symbols=_symbols(),
        tests=["tests/test_config.py"],
        findings=[_finding()],
        pattern_items=[],
    )

    assert result["decomposition"]["candidate_count"] == 1
    assert result["decomposition"]["items"][0]["path"] == "src/config.py"
