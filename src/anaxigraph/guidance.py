"""Shared, plain-language product vocabulary for humans and coding agents."""

from __future__ import annotations

from typing import Any

FILE_MEASUREMENT_MEANINGS = {
    "lines_of_code": "The number of code lines AnaxiGraph counted in the selected saved scan.",
    "complexity": (
        "A file-wide branch score that combines decisions such as if-statements, loops, cases, "
        "and exception handlers across the file. It is not a code-quality grade."
    ),
    "fan_in": "How many indexed files directly use this file.",
    "fan_out": "How many indexed files this file directly uses.",
    "line_coverage": (
        "The share of this file's lines run by the imported test report. Missing means no matching "
        "test report, not zero coverage."
    ),
    "change_count": "How many indexed Git commits changed this file.",
    "attention_score": (
        "A sorting score that combines size, branches, direct file links, Git changes, and active "
        "findings. It only decides which files appear first; it is not a grade for the code."
    ),
    "raw_hash": "An identifier for the exact file contents in this saved scan, not a score.",
    "structural_hash": "An identifier for the parsed code structure, not a score.",
}

FINDING_STATUSES = {
    "new": {
        "label": "New",
        "meaning": "Detected by the latest complete scan and not yet reviewed.",
        "next": ["acknowledged", "planned", "accepted", "dismissed"],
    },
    "acknowledged": {
        "label": "Reviewed",
        "meaning": "A person or agent reviewed the finding; it remains active and monitored.",
        "next": ["planned", "accepted", "dismissed"],
    },
    "accepted": {
        "label": "Accepted risk",
        "meaning": "The condition is understood and intentionally retained for now.",
        "next": ["planned", "dismissed"],
    },
    "planned": {
        "label": "Planned for agent",
        "meaning": "This was selected as engineering work; agents can query the planned work list.",
        "next": ["acknowledged", "accepted", "dismissed"],
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
        "label": "Returned",
        "meaning": "A later scan stopped finding this condition, but a newer scan found it again.",
        "next": ["acknowledged", "planned", "dismissed"],
    },
}

FINDING_VIEWS = {
    "attention": (
        "A short list of findings worth checking first. It includes new findings, findings already "
        "selected for work, and problems that returned. Small informational notes about long "
        "functions stay out unless the project's settings ask to include them."
    ),
    "diagnostics": (
        "The complete saved list of findings. Filters narrow what you see, exact totals say how "
        "many match, and pages keep a large list manageable. Changing views does not create or "
        "delete a finding."
    ),
}

OVERLAYS = {
    "architecture": (
        "Color shows which repository area each file belongs to. A project setting can place files "
        "by path. When no setting matches, AnaxiGraph makes a best guess from the file path and "
        "how the code runs. The large faint boxes show broader areas."
    ),
    "coupling": (
        "Hotter-colored files have more direct code links: they use more files, more files use "
        "them, or both. A change there may affect more code, but many links are not automatically bad."
    ),
    "complexity": (
        "Hotter-colored files contain more decisions such as if, match, and loop branches. Use "
        "this to choose files to inspect; the number alone does not prove that a refactor would help."
    ),
    "coverage": (
        "Green files had more of their lines run by the imported test report; red files had fewer. "
        "Grey means no test report matched the file. It does not mean tests ran zero lines."
    ),
    "change": (
        "Hotter-colored files changed in more of the Git commits AnaxiGraph indexed. This can show "
        "where work happens often; it is not a quality grade."
    ),
    "dead-code": (
        "Amber files may be unused. AnaxiGraph found no other indexed file that clearly or possibly "
        "points to them, they have not changed recently, and they are not known starting files or "
        "registered handlers. Code can still reach them while the program runs, so inspect before deleting."
    ),
    "agent": (
        "After you describe a coding task, green files are useful to read, amber files are marked "
        "by project rules as needing extra care, and red files also changed on another branch. "
        "Before a task is described, every file uses a neutral color."
    ),
    "drift": (
        "Red means a project setting places the file in one area while its path and runtime style "
        "suggest another. Check whether the setting, file location, or file's job is out of date. "
        "The mismatch does not prove a defect."
    ),
}

AGENT_WORKFLOW = {
    "scope": (
        "Describe a coding goal to get a small list of likely implementation files, directly "
        "related files, tests, files that project rules mark for extra care, relevant rules, known "
        "findings, advice about where to start, and a saved before-change record for comparison."
    ),
    "impact": (
        "Name a file or symbol before changing it to find direct and indirect code that depends on "
        "it, relevant tests, possible database changes, files marked for extra care, and files also "
        "changed on another branch."
    ),
    "planned_queue": (
        "When a finding is selected for work, the coding agent calls ANAXIGRAPH_FINDINGS with "
        "status='planned', then ANAXIGRAPH_FINDING_CONTEXT before editing."
    ),
    "semantic_memory": (
        "Call ANAXIGRAPH_SEMANTIC_STATUS to see whether the AI-created code map is up to date. "
        "ANAXIGRAPH_SCOPE gives short pattern and file-placement advice for a coding goal. "
        "ANAXIGRAPH_FILE gives the full saved AI description, its evidence, and who or what created "
        "it. To build the complete map with a coding agent, run `anaxigraph understand "
        "<repository> --executor codex --background` and watch `semantic-status`. Direct SCHEMA, "
        "WORK, EVIDENCE, and SUBMIT calls are a fallback for processing one saved task at a time. "
        "Do not report completion until semantically_ready is true."
    ),
}

CODING_LOOP_CONTRACT = {
    "version": "coding-loop-contract-v1",
    "purpose": (
        "These are the existing names an agent can rely on to understand a repository, choose "
        "where a change belongs, inspect its likely effects, and compare the result after a new "
        "scan. The lists are required subsets, so AnaxiGraph may expose other operations too."
    ),
    "cli_commands": [
        "up",
        "scan",
        "update",
        "scope",
        "impact",
        "review",
        "finding",
        "patterns",
        "understand",
        "semantic-status",
    ],
    "rest_operations": [
        "GET /api/overview",
        "GET /api/modules",
        "GET /api/file",
        "GET /api/graph/overview",
        "GET /api/graph",
        "GET /api/findings",
        "GET /api/findings/{finding_id}/context",
        "GET /api/patterns",
        "GET /api/patterns/candidates",
        "GET /api/semantic",
        "GET /api/scan",
        "POST /api/scan",
        "POST /api/semantic/prepare",
        "POST /api/agent-scope",
        "POST /api/impact",
    ],
    "mcp_tools": [
        "ANAXIGRAPH_REPOSITORIES",
        "ANAXIGRAPH_OVERVIEW",
        "ANAXIGRAPH_MODULES",
        "ANAXIGRAPH_GRAPH",
        "ANAXIGRAPH_SEARCH",
        "ANAXIGRAPH_FILE",
        "ANAXIGRAPH_SCOPE",
        "ANAXIGRAPH_IMPACT",
        "ANAXIGRAPH_FINDINGS",
        "ANAXIGRAPH_FINDING_CONTEXT",
        "ANAXIGRAPH_PATTERNS",
        "ANAXIGRAPH_SEMANTIC_STATUS",
        "ANAXIGRAPH_TAXONOMY",
        "ANAXIGRAPH_SEMANTIC_SCHEMA",
        "ANAXIGRAPH_SEMANTIC_WORK",
        "ANAXIGRAPH_SEMANTIC_EVIDENCE",
        "ANAXIGRAPH_SEMANTIC_SUBMIT",
        "ANAXIGRAPH_SEMANTIC_RELEASE",
    ],
    "versioned_results": {
        "scope.architecture_decision.contract_version": "architecture-decision-v1",
        "scope.architecture_decision.verification.post_change_baseline.contract_version": (
            "architecture-verification-baseline-v2"
        ),
        "scope.architecture_decision.verification.post_change_comparison.contract_version": (
            "architecture-verification-comparison-v2"
        ),
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
    },
}


def product_glossary() -> dict[str, Any]:
    return {
        "product": _product_terms(),
        "architecture": _architecture_terms(),
        "findings": _finding_terms(),
        "overlays": OVERLAYS,
        "file_measurements": FILE_MEASUREMENT_MEANINGS,
        "agents": AGENT_WORKFLOW,
        "coding_loop": CODING_LOOP_CONTRACT,
        "coverage": {
            "missing": (
                "No configured coverage.xml or lcov.info matched this saved scan. Missing coverage "
                "input is kept distinct from measured 0% coverage."
            )
        },
    }


def _product_terms() -> dict[str, str]:
    return {
        "anaxigraph": "The dashboard, analysis engine, and overall open-source project.",
        "anaxi_index": (
            "The saved index that lets AnaxiGraph remember files, direct code links, what the "
            "code does, findings, and Git history between sessions."
        ),
        "anaxi_mcp": (
            "The tool server that lets coding agents read goal-specific facts from AnaxiIndex."
        ),
    }


def _architecture_terms() -> dict[str, Any]:
    return {
        "hierarchy": [
            "repository — the whole codebase",
            "area — a broad kind of work",
            "subsystem — a smaller group of related work inside an area",
            "module — the stable machine name for one file",
            (
                "symbol — the stable machine name for a named code part such as a function, "
                "method, or class"
            ),
        ],
        "declared_group": (
            "A project setting placed this file in a named area because its path matched a rule."
        ),
        "inferred_group": (
            "When no project setting matched, AnaxiGraph guessed the file's area from its path "
            "and how that kind of code normally runs."
        ),
        "group_rollup": (
            "Smaller groups stay separate when checking code-link rules, but the overview also "
            "adds their file and line counts under one broader area."
        ),
    }


def _finding_terms() -> dict[str, Any]:
    return {
        "definition": (
            "A saved observation produced by a repository rule. It explains what AnaxiGraph saw "
            "and why it may matter; it is not proof that code must change."
        ),
        "confidence": (
            "Confidence describes how directly the detector observed the condition; it does not "
            "measure severity or the chance that a refactor is worthwhile."
        ),
        "statuses": FINDING_STATUSES,
        "views": FINDING_VIEWS,
    }
