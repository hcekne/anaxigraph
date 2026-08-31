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
        "After you describe a coding task, green files are useful to read and amber files are "
        "marked by project rules as needing extra care. "
        "Before a task is described, every file uses a neutral color."
    ),
    "drift": (
        "Red means a project setting places the file in one area while its path and runtime style "
        "suggest another. Check whether the setting, file location, or file's job is out of date. "
        "The mismatch does not prove a defect."
    ),
}


def product_glossary() -> dict[str, Any]:
    return {
        "product": _product_terms(),
        "architecture": _architecture_terms(),
        "findings": _finding_terms(),
        "overlays": OVERLAYS,
        "file_measurements": FILE_MEASUREMENT_MEANINGS,
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
        "current_view": (
            "The default map: declared repository intent where present, then a current inferred "
            "responsibility, then deterministic path fallback. It is a view, not another fact."
        ),
        "declared_map": (
            "Optional repository policy supplied or corrected by a person or team. Unmatched "
            "files remain visibly unconfigured in this view."
        ),
        "responsibility_map": (
            "An AI-reviewed interpretation of file responsibilities and relationships. Stable "
            "group keys, display labels, confidence, and evidence remain separate."
        ),
        "path_map": (
            "A deterministic directory and package grouping used without AI. It is a reliable "
            "fallback, not a claim about what the code means."
        ),
        "fallback_vocabulary": (
            "A deterministic set of ordinary architecture roles: application, testing, "
            "documentation, infrastructure, and developer tooling, each with narrower "
            "subsystems. Declared intent and a current inferred responsibility take precedence."
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
