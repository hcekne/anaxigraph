"""Plain-language projection for one AI-created repository group."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from anaxigraph.semantic_file_language import explain_specialist_terms

SEMANTIC_TAXONOMY_LANGUAGE_VERSION = "semantic-taxonomy-explanation-v1"

_PLAIN_NAMES = {
    "benchmark fixtures & oracles": "Benchmark examples and expected answers",
    "dashboard client": "Browser dashboard",
    "distribution & release": "Packaging and releases",
    "product regression tests": "Tests that catch broken behavior",
    "repository intelligence core": "Core code for understanding repositories",
    "semantic & pattern intelligence": "AI code descriptions and pattern checks",
    "analysis & scan support": "Reading source code and saving scan results",
    "benchmark execution & evidence": "Running benchmarks and recording results",
    "cli, mcp & local operations": "Commands, coding-agent connections, and local operation",
    "interfaces": "Ways people and tools use AnaxiGraph",
    "operations & agent guidance": "Guides for running AnaxiGraph and connecting agents",
    "operations & persistence tests": "Tests for safe operation and saved data",
    "architecture & product policy": "Rules for code organization and product changes",
    "http runtime composition": "Creating and connecting the web service",
    "persistence & repository projections": "Saving repository facts and building useful views",
    "quality tooling": "Automated repository checks",
    "validation & quality": "Tests and code-quality checks",
    "benchmarks": "Repeatable measurements",
    "delivery & governance": "Packaging, releases, and operating rules",
}

_PLAIN_NAME_TERMS = (
    ("composition root", "startup code that connects the main parts"),
    ("persistence", "saved data"),
    ("semantic", "AI code descriptions"),
    ("projections", "useful views"),
    ("projection", "useful view"),
    ("boundaries", "handoff points"),
    ("boundary", "handoff point"),
    ("adapters", "translators"),
    ("adapter", "translator"),
    ("facades", "simple entry points"),
    ("facade", "simple entry point"),
    ("transport", "request delivery"),
    ("deterministic", "rule-based"),
    ("canonical", "official"),
    ("schemas", "data-shape rules"),
    ("schema", "data-shape rules"),
    ("lifecycle", "start-to-finish steps"),
    ("pipeline", "automated steps"),
    ("provenance", "source history"),
    ("cohesion", "focus"),
    ("topology", "connection layout"),
    ("oracles", "expected answers"),
    ("oracle", "expected answer"),
    ("protocols", "communication rules"),
    ("protocol", "communication rules"),
    ("governance", "operating rules"),
    ("regression", "broken-behavior"),
    ("fixtures", "test inputs"),
)

_PLAIN_PHRASES = (
    (
        "Browser shell, views, controls, assets, and client-side state",
        "Page structure, screens, controls, images, styles, and information kept in the browser "
        "while it is open",
    ),
    (
        "Packaging, plugin manifests, automation, and release controls",
        "Package settings, files that describe plugins, automated release steps, and checks used "
        "when publishing",
    ),
    (
        "History, recovery, index, migration, onboarding, and local-runtime acceptance tests",
        "Tests for saved history, recovery from problems, index upgrades, initial setup, and "
        "whether the locally running service works for a user",
    ),
    (
        "FastAPI application assembly, lifecycle, dashboard hosting, limits, and route registration",
        "Code that creates the web service, handles startup and shutdown, serves the dashboard, "
        "applies limits, and connects web addresses to their handlers",
    ),
    (
        "Release automation, policy documentation, and runbooks",
        "Automated release steps, written rules, and step-by-step operating guides",
    ),
    (
        "Define supported external operation and connection procedures",
        "Explain the supported ways to run AnaxiGraph and connect other tools",
    ),
    (
        "Produce normalized analysis facts and findings",
        "Read source code, save the facts found in one consistent format, and record problems "
        "worth checking",
    ),
    (
        "The clusters are local-facing adapters and composition roots",
        "These files accept local requests and connect the parts needed to handle them",
    ),
    (
        "These groups are local-facing adapters and composition roots",
        "These files accept local requests and connect the parts needed to handle them",
    ),
    (
        "Specify durable boundaries and governed product evolution",
        "Set long-lived rules about where code belongs and control changes to the product",
    ),
    (
        "controlled corpora and expected outputs",
        "fixed collections of examples and expected answers",
    ),
    (
        "Temporal, graph, and domain projections share the protected persistence boundary; these "
        "files are placed here because its available samples and strongest dependencies are "
        "persistence/service oriented",
        "These files all save repository facts or turn them into useful views. The sampled files "
        "and their strongest direct code links support keeping them together",
    ),
    (
        "persistence adapters and schema contracts",
        "code that saves data, translates between storage and callers, and checks the shape of "
        "saved data",
    ),
    ("one persistence lifecycle", "one set of steps for saving and loading data"),
    ("controlled benchmark corpora", "fixed collections of benchmark examples"),
    ("controlled corpora", "fixed collections of examples"),
    ("reproducible benchmark inputs", "benchmark inputs that give repeatable results"),
    ("correctness expectations", "the expected correct results"),
    ("execution sequencing", "the order in which benchmark steps run"),
    ("browser shell", "browser page structure"),
    ("client-side state", "information kept in the browser while the page is open"),
    ("supported installable artifacts", "packages and plugins people can install"),
    ("installable artifacts", "packages people can install"),
    ("plugin manifests", "files that describe plugins to tools"),
    ("release controls", "checks and settings used when publishing a release"),
    ("release and distribution controls", "publishing packages and plugins"),
    (
        "integration, semantic, agent, package, migration, and analyzer contracts",
        "behavior across connected parts, AI code descriptions, coding-agent tools, package "
        "releases, saved-data upgrades, and source-code readers",
    ),
    ("shared fixtures", "shared test inputs and setup"),
    ("broad product regression suites", "tests that catch behavior broken by later changes"),
    (
        "shared test infrastructure and behavior coverage",
        "shared test setup and tests of important behavior",
    ),
    ("repository intelligence", "information about the repository's code and structure"),
    ("semantic interpretation", "AI descriptions of what code does"),
    ("repository services", "code that answers questions about the repository"),
    (
        "durable read and storage boundaries",
        "code that saves, loads, and exposes repository information",
    ),
    (
        "semantic outcomes and agent-ready context",
        "AI conclusions and focused repository information for coding agents",
    ),
    ("candidate interpretation", "deciding which code may match"),
    ("semantic execution", "running AI code-description work"),
    ("bounded agent context", "a limited amount of repository information sent to an agent"),
    (
        "semantic and pattern workflow contracts",
        "rules connecting AI descriptions and pattern checks",
    ),
    ("persisted evidence", "saved facts"),
    ("pattern definitions", "descriptions of coding patterns"),
    ("pattern knowledge", "descriptions of useful coding patterns"),
    (
        "repository’s internal analysis and intelligence lifecycle",
        "steps used to read, save, and explain the repository",
    ),
    (
        "internal analysis and intelligence lifecycle",
        "steps used to read, save, and explain the repository",
    ),
    ("normalized analysis facts", "code facts put into one consistent format"),
    ("extraction helpers", "code that reads facts from source files"),
    ("analyzer registration", "code that selects the correct source-code reader"),
    ("scan finalization", "code that finishes and saves a repository scan"),
    ("architecture evaluation", "checks of how the repository is organized"),
    ("analysis output and scanning", "reading source code and saving the facts found"),
    ("emit measurable evidence", "record results that can be compared"),
    ("workloads", "benchmark tasks"),
    ("benchmark orchestration", "code that starts and coordinates benchmarks"),
    ("runtime probes", "small checks made while a benchmark runs"),
    ("first-user trials", "tests of a new user's first experience"),
    ("fixture content", "benchmark inputs and expected results"),
    ("safe local repository operations", "safe ways to inspect or manage a local repository index"),
    (
        "MCP/local runtime setup",
        "setup for connecting coding agents and running AnaxiGraph locally",
    ),
    ("onboarding", "initial setup"),
    ("diagnostics", "checks that explain setup or running problems"),
    (
        "supported user and transport interactions",
        "requests from supported user tools and connections",
    ),
    ("repository-service calls", "calls to code that reads repository information"),
    (
        "browser, CLI, local-operation, MCP, and HTTP entry boundaries",
        "entry points for the browser, commands, local tools, coding agents, and web requests",
    ),
    ("external-facing adapters", "code used by outside tools to call the repository service"),
    ("runtime composition boundary", "place where the running parts are created and connected"),
    (
        "local-facing adapters and composition roots",
        "code that accepts local requests and connects the parts needed to handle them",
    ),
    (
        "external-facing adapter or place where the running parts are created and connected",
        "entry point used by an outside tool, or code that creates and connects running parts",
    ),
    (
        "external operation and connection procedures",
        "documented ways to run AnaxiGraph and connect other tools",
    ),
    ("runbooks", "step-by-step operating guides"),
    ("deployment guidance", "instructions for running the service"),
    ("agent integration", "instructions for connecting coding agents"),
    ("recovery documentation", "instructions for recovering from problems"),
    ("external operating lifecycle", "steps for running and recovering the tool"),
    (
        "Protect durable-state and safe-operation contracts",
        "Keep saved data correct and ensure operations remain safe",
    ),
    ("durable-state", "saved-data"),
    ("safe-operation contracts", "behavior needed to keep operations safe"),
    ("local-runtime acceptance tests", "tests that the locally running service works for a user"),
    (
        "operational and persistence behavior",
        "running the tool safely and saving or loading its data",
    ),
    ("governed product evolution", "controlled changes to the product"),
    ("durable boundaries", "long-lived rules about where different code belongs"),
    ("normative architecture", "authoritative rules for code organization"),
    (
        "persistence, extension, pattern",
        "saving data, adding supported behavior, use of coding patterns",
    ),
    ("roadmap policy", "rules for planned product work"),
    ("normative repository-wide policy", "authoritative rules for the whole repository"),
    ("process-wide HTTP behavior", "web-request behavior shared by the whole running service"),
    ("FastAPI application assembly", "code that creates the FastAPI web service"),
    ("dashboard hosting", "serving the dashboard files"),
    (
        "lifecycle, serving the dashboard files",
        "startup and shutdown handling, serving the dashboard files",
    ),
    ("route registration", "connecting web addresses to the code that handles them"),
    (
        "a focused HTTP composition root",
        "the focused code that creates and connects the web service",
    ),
    ("snapshot-accurate state", "saved facts from exactly one repository scan"),
    ("projected repository facts", "repository facts turned into views callers can use"),
    ("temporal storage", "storage that keeps facts from more than one repository scan"),
    ("integrity mechanisms", "checks that keep saved data consistent"),
    ("read models", "data views used to answer questions"),
    ("repository service facades", "small entry points for repository operations"),
    ("graph and intelligence data views", "graph views and other data views"),
    (
        "available samples and strongest dependencies",
        "sampled files and the strongest direct code links between them",
    ),
    (
        "deterministic repository validation scripts",
        "repository checks that always follow the same coded rules",
    ),
    ("observable behavior", "behavior a user or calling program can see"),
    ("quality policies", "written quality rules"),
    ("repeatable engineering policy", "engineering rules checked the same way each time"),
    ("regression coverage", "tests that catch behavior broken by later changes"),
    ("operational safety tests", "tests that safe operations keep working"),
    ("executable quality controls", "automated code-quality checks"),
    (
        "quality-policy definition and enforcement",
        "files that define and run the repository's quality rules",
    ),
    (
        "tests, fixtures, policies, or validation scripts",
        "tests, test inputs, written rules, or automated checks",
    ),
    ("measurement evidence", "saved benchmark results"),
    (
        "correctness and performance reproducibly",
        "whether results are correct and how fast the work runs, using repeatable inputs",
    ),
    (
        "expectations, workload runners",
        "expected answers, code that runs the benchmark tasks",
    ),
    (
        "Fixtures and runners have distinct but tightly related benchmark responsibilities",
        "The example inputs define what to test, while the benchmark code performs the tests. "
        "Both are needed for one benchmark",
    ),
    ("supported artifacts", "packages and plugins people can use"),
    (
        "govern safe product evolution and operation",
        "set rules for changing and running the product safely",
    ),
    ("distribution definitions", "files that describe packages and plugins"),
    (
        "normative and operational repository guidance",
        "authoritative rules and step-by-step operating guidance",
    ),
    ("external lifecycle", "steps for installing, running, updating, and recovering the tool"),
    ("wholly dashboard-package client code", "all code used by the browser dashboard"),
)


def semantic_taxonomy_explanation(node: Mapping[str, Any]) -> dict[str, Any]:
    """Explain a repository area without requiring architecture vocabulary."""

    label = str(node.get("label") or node.get("name") or "Unnamed code group")
    level = str(node.get("level") or "subsystem")
    responsibility = _plain_sentence(node.get("responsibility"))
    description = _plain_sentence(node.get("description"))
    rationale = _plain_sentence(_visible_group_words(node.get("rationale")))
    confidence = _confidence(node.get("confidence"))
    display_name = _plain_name(label)
    return {
        "version": SEMANTIC_TAXONOMY_LANGUAGE_VERSION,
        "conclusion": (f"The AI-created map uses {display_name} as {_level_meaning(level)}."),
        "display_name": display_name,
        "name_and_meaning": display_name,
        "what_this_group_does": responsibility
        or "The AI-created map did not state this group's concrete job.",
        "what_belongs_here": description
        or "The AI-created map did not explain which work belongs in this group.",
        "why_these_files_are_together": rationale
        or "The AI-created map did not record a reason for grouping these files.",
        "evidence_strength": {
            "value": confidence,
            "meaning": _confidence_meaning(confidence),
        },
    }


def semantic_taxonomy_assignment_explanation(assignment: Mapping[str, Any]) -> dict[str, Any]:
    """Explain one file's placement without repeating an AI-generated internal note."""

    area = _plain_name(str(assignment.get("area_name") or assignment.get("area") or "code area"))
    subsystem = _plain_name(
        str(assignment.get("subsystem_name") or assignment.get("subsystem") or "code group")
    )
    confidence = _confidence(assignment.get("confidence"))
    destination = subsystem if subsystem == area else f"{subsystem}, inside {area}"
    reason = (
        "Repository map configuration explicitly puts this file in this group."
        if assignment.get("locked")
        else (
            "The AI map compared the file's saved description and direct code links with the "
            "jobs of the other groups. This group was its strongest match."
        )
    )
    return {
        "version": SEMANTIC_TAXONOMY_LANGUAGE_VERSION,
        "conclusion": f"The AI-created map places this file in {destination}.",
        "area_name": area,
        "subsystem_name": subsystem,
        "why_this_file_is_here": reason,
        "evidence_strength": {
            "value": confidence,
            "meaning": _confidence_meaning(confidence),
        },
    }


def _level_meaning(level: str) -> str:
    if level == "area":
        return "a broad area containing smaller groups of related repository work"
    return "a smaller group of files that perform closely related work"


def _plain_name(label: str) -> str:
    if mapped := _PLAIN_NAMES.get(label.lower()):
        return mapped
    text = label.replace(" & ", " and ")
    for phrase, replacement in _PLAIN_NAME_TERMS:
        text = re.sub(
            rf"(?<![\w]){re.escape(phrase)}(?![\w])",
            lambda match: _matching_case(replacement, match.start()),
            text,
            flags=re.IGNORECASE,
        )
    return text


def _visible_group_words(value: Any) -> str:
    text = str(value or "").strip()
    replacements = (
        (r"\b(?:cluster|group)-\d+\s+is\b", "these files are"),
        (r"\b(?:cluster|group)-\d+\s+supplies\b", "these files supply"),
        (r"\b(?:cluster|group)-\d+\s+focuses\b", "these files focus"),
        (r"\b(?:cluster|group)-\d+\s+documents\b", "these files document"),
        (r"\b(?:cluster|group)-\d+\b", "this group"),
        (r"\bthe supplied cluster\s+is\b", "these files are"),
        (r"\bthe cluster\s+is\b", "these files are"),
        (r"\bthe cluster\s+defines\b", "these files define"),
        (r"\bthe cluster\s+performs\b", "these files perform"),
        (r"\bthe clusters\s+are\b", "these groups are"),
        (r"\bboth clusters\s+are\b", "these groups are"),
        (r"\beach cluster\s+is\b", "each group is"),
        (r"\bclusters\b", "groups"),
        (r"\bcluster\b", "group"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text[:1].upper() + text[1:] if text else ""


def _plain_sentence(value: Any) -> str:
    text = str(value or "").strip()
    for phrase, replacement in _PLAIN_PHRASES:
        text = re.sub(
            rf"(?<![\w]){re.escape(phrase)}(?![\w])",
            lambda match: _matching_case(replacement, match.start()),
            text,
            flags=re.IGNORECASE,
        )
    return _sentence(explain_specialist_terms(text))


def _matching_case(replacement: str, offset: int) -> str:
    if offset == 0:
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _confidence_meaning(confidence: float) -> str:
    strength = "strong" if confidence >= 0.7 else "mixed" if confidence >= 0.4 else "weak"
    return (
        f"Support for this grouping is {strength}. This describes the evidence behind the AI "
        "grouping; it is not a grade for the files."
    )


def _sentence(value: str) -> str:
    return value if not value or value.endswith((".", "?", "!")) else f"{value}."
