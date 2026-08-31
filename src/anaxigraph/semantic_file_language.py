"""Plain-language AI-map state for one file."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

SEMANTIC_FILE_LANGUAGE_VERSION = "semantic-file-explanation-v4"

_RELATED_FILES = re.compile(
    r"\s*Contextually connected to (\d+) sampled dependencies and "
    r"(\d+) sampled consumers\.?$",
    re.IGNORECASE,
)
_LEGACY_PLACEMENT = re.compile(
    r"^Keep work matching this role here:\s*.+?\.*\s*"
    r"Place unrelated behavior in its owning focused layer\.?$",
    re.IGNORECASE,
)
_LEGACY_CHANGE = re.compile(
    r"^Contextual synthesis from the intrinsic dossier, (\d+) resolved relationship records, "
    r"(\d+) unique neighbou?r dossiers, and (\d+) evidence pages\.?$",
    re.IGNORECASE,
)

_TERM_REWRITES = (
    (
        "scope and evidence proportionate",
        "amount of code checked and supporting evidence appropriate for the recommendation",
    ),
    (
        "configuration, frameworks, reflection, plugins, or generated code",
        "settings, framework hooks, code that looks up names while running, plugins, or generated code",
    ),
    (
        "configuration, runtime registration, and focused tests",
        "settings, code registered while the application starts or runs, and focused tests",
    ),
    ("deterministic reachability finding", "direct source-code link check"),
    ("deterministic reachability", "direct source-code link checking"),
    ("semantic analysis", "AI review of what the code does"),
    ("semantic review", "AI review of what the code does"),
    ("module boundary", "way the code is divided between files"),
    ("public contracts", "behavior and names that other code relies on"),
    ("public contract", "behavior and names that other code relies on"),
    ("public return types", "results returned to callers"),
    ("execution contract", "required caller-visible behavior"),
    ("provider boundary", "shared interface used to call providers"),
    ("selection policy", "rules for choosing an implementation"),
    ("behavior boundary", "caller-facing behavior"),
    ("through one boundary", "through one shared caller-facing interface"),
    ("another abstraction", "another shared layer of code"),
    ("structural change", "moving, merging, or splitting code"),
    ("static source links", "direct links found in source code"),
    ("incoming static link", "direct source-code link to this item"),
    ("runtime registration", "code registered while the application starts or runs"),
    ("architecture role", "job in the repository"),
    (
        "encapsulate interchangeable algorithms behind one stable operation contract",
        "put different ways of solving the same problem behind one caller-visible operation so callers can switch between them",
    ),
    (
        "container distribution and runtime-security boundary",
        "container build and release file that controls how the running service is isolated and protected",
    ),
    ("architectural boundary", "intended separation between repository areas"),
    ("intrinsic dossier", "description based only on this file"),
    ("contextual dossier", "description that also uses related files"),
    ("neighbour dossiers", "descriptions of related files"),
    ("neighbor dossiers", "descriptions of related files"),
    ("resolved relationship records", "direct code links"),
    ("contextual synthesis", "combined description using related files"),
    ("orchestration", "coordination"),
    ("dossier", "saved AI description"),
)

_TERM_DEFINITIONS = (
    (
        "composition root",
        r"\bcomposition roots?\b",
        "startup code that creates and connects the main parts",
    ),
    (
        "adapter",
        r"\badapters?\b",
        "code that translates between two parts",
    ),
    (
        "facade",
        r"\bfacades?\b",
        "a small public entry point that hides internal details",
    ),
    (
        "boundary",
        r"\bboundar(?:y|ies)\b",
        "the place where one part hands work or data to another",
    ),
    (
        "contract",
        r"\bcontracts?\b",
        "behavior or data that other code relies on",
    ),
    (
        "persistence",
        r"\bpersistence\b",
        "saving and loading data",
    ),
    (
        "semantic",
        r"\bsemantic\b",
        "based on saved descriptions of what code means and does",
    ),
    (
        "transport",
        r"\btransports?\b",
        "the way requests move between tools or processes",
    ),
    (
        "projection",
        r"\bprojections?\b",
        "a view derived from saved facts",
    ),
    (
        "deterministic",
        r"\bdeterministic\b",
        "produced by fixed code rules rather than an AI judgment",
    ),
    (
        "canonical",
        r"\bcanonical\b",
        "the authoritative version used by the system",
    ),
    (
        "metadata",
        r"\bmetadata\b",
        "information that describes other data",
    ),
    ("schema", r"\bschemas?\b", "rules for the shape of saved or exchanged data"),
    (
        "lifecycle",
        r"\blifecycles?\b",
        "the steps from creation or start through completion",
    ),
    ("pipeline", r"\bpipelines?\b", "an ordered sequence of automated steps"),
    (
        "provenance",
        r"\bprovenance\b",
        "a record of where information came from",
    ),
    ("cohesion", r"\bcohesion\b", "whether code is focused on one clear job"),
    ("topology", r"\btopolog(?:y|ies)\b", "the layout of connected parts"),
    ("oracle", r"\boracles?\b", "an expected answer used by a test"),
    ("seam", r"\bseams?\b", "a place where two parts connect"),
    ("surface", r"\bsurfaces?\b", "behavior visible to other code"),
    ("protocol", r"\bprotocols?\b", "rules two parts follow when communicating"),
)


def semantic_file_explanation(path: str, semantic: Mapping[str, Any]) -> dict[str, Any]:
    """Explain one file's saved AI description without workflow-state jargon."""

    status = str(semantic.get("status") or "not_started")
    subject_kind = "repository" if semantic.get("subject_kind") == "repository" else "file"
    summary = _clear_text(semantic.get("summary"))
    role, related_files = _role_and_related_files(semantic.get("architecture_role"), subject_kind)
    placement = _placement(semantic.get("placement_guidance"))
    changed = _change_summary(semantic.get("change_summary"))
    confidence = _confidence(semantic.get("confidence"))
    return {
        "version": SEMANTIC_FILE_LANGUAGE_VERSION,
        "conclusion": _conclusion(path, status, subject_kind),
        "what_this_file_does": summary or role or _missing_role(status, subject_kind),
        "role_in_repository": role or _missing_role(status, subject_kind),
        "related_file_evidence": related_files,
        "where_related_work_belongs": (
            placement or "The AI map did not record where related work should be added."
        ),
        "what_changed_in_description": changed,
        "jobs": _clear_list(semantic.get("responsibilities")),
        "places_for_adding_behavior": _clear_list(semantic.get("extension_points")),
        "risks_and_uncertainty": _clear_list(semantic.get("risks")),
        "evidence_strength": {
            "value": confidence,
            "meaning": _confidence_meaning(status, confidence),
        },
        "how_to_use_the_raw_fields": (
            "The separate fields about patterns, whether nearby code should be combined, and code "
            "that might be unused are early AI notes, not instructions to change code. Before "
            "changing or deleting code, use the architecture_decision section: it checks those "
            "notes against repository evidence and explains the recommended action."
        ),
    }


def _role_and_related_files(value: Any, subject_kind: str) -> tuple[str, str]:
    role = str(value or "").strip()
    match = _RELATED_FILES.search(role)
    if match is None:
        clear_role = _sentence(_clear_text(role))
        return (
            clear_role,
            "The saved AI description did not state how many related files it compared.",
        )
    role = role[: match.start()].rstrip(" .")
    used, callers = (int(match.group(1)), int(match.group(2)))
    subject = "this repository" if subject_kind == "repository" else "this file"
    evidence = (
        f"The AI description compared {used} related {_files(used)} {subject} uses and "
        f"{callers} related {_files(callers)} that {_use_verb(callers)} {subject}."
    )
    return _sentence(_clear_text(role)), evidence


def _placement(value: Any) -> str:
    placement = str(value or "").strip()
    if _LEGACY_PLACEMENT.fullmatch(placement):
        return (
            "Add work here when it has the same job described above. Put work with a different "
            "job in the file or repository area responsible for it."
        )
    return _clear_text(placement)


def _change_summary(value: Any) -> str:
    changed = str(value or "").strip()
    match = _LEGACY_CHANGE.fullmatch(changed)
    if match is not None:
        links, files, pages = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return (
            "The AI updated this description by combining the file's own description with "
            f"{links} direct code {_links(links)}, {files} descriptions of related {_files(files)}, "
            f"and {pages} additional {_pages(pages)} of code facts."
        )
    if changed.lower() == "no previous dossier was supplied.":
        return "There was no older AI description to compare."
    return _clear_text(changed)


def _clear_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [text for item in value[:12] if (text := _clear_text(item))]


def _clear_text(value: Any) -> str:
    return explain_specialist_terms(re.sub(r"\.\.(?=\s|$)", ".", str(value or "").strip()))


def explain_specialist_terms(
    value: Any,
    *,
    extra_definitions: Sequence[tuple[str, str, str]] = (),
) -> str:
    """Rewrite avoidable jargon and define precise code language that remains."""

    text = str(value or "").strip()
    for term, replacement in _TERM_REWRITES:
        text = re.sub(
            rf"(?<![\w]){re.escape(term)}(?![\w])",
            lambda match: _matching_case(replacement, match.group(0)),
            text,
            flags=re.IGNORECASE,
        )
    return _define_unexplained_terms(text, (*_TERM_DEFINITIONS, *extra_definitions))


def _define_unexplained_terms(
    text: str, definitions_to_check: Sequence[tuple[str, str, str]]
) -> str:
    definitions = [
        (term, meaning)
        for term, pattern, meaning in definitions_to_check
        if re.search(pattern, text, flags=re.IGNORECASE)
        and not _already_defined(text, term, pattern)
    ]
    if not definitions:
        return text
    meanings = "; ".join(f"“{term}” means {meaning}" for term, meaning in definitions)
    return f"{_sentence(text)} In this description, {meanings}."


def _already_defined(text: str, term: str, pattern: str) -> bool:
    if re.search(
        rf"[“\"]{re.escape(term)}[”\"]\s+means\b",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return False
    following = text[match.end() : match.end() + 48].lower()
    return bool(
        re.match(r"\s*(?:\(|,?\s*(?:means?|meaning|which means|in other words)\b)", following)
    )


def _matching_case(replacement: str, original: str) -> str:
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def _sentence(value: str) -> str:
    return value if not value or value.endswith((".", "?", "!")) else f"{value}."


def _files(count: int) -> str:
    return "file" if count == 1 else "files"


def _use_verb(count: int) -> str:
    return "uses" if count == 1 else "use"


def _links(count: int) -> str:
    return "link" if count == 1 else "links"


def _pages(count: int) -> str:
    return "page" if count == 1 else "pages"


def _conclusion(path: str, status: str, subject_kind: str) -> str:
    if subject_kind == "repository" and status == "current":
        return "The AI map has an up-to-date description of the repository and how its parts work together."
    if status == "current":
        return (
            f"The AI map has an up-to-date description of {path} and its role in this repository."
        )
    if status == "intrinsic_current":
        return (
            f"The AI map has described {path} itself, but has not finished how it fits with the "
            "rest of the repository."
        )
    if status == "excluded":
        return f"{path} is deliberately outside AI mapping."
    if status.startswith("failed_") or status == "failed":
        return f"AI mapping could not finish an up-to-date description of {path}."
    if status.startswith("pending_") or status in {"pending", "stale"}:
        return f"The AI description of {path} is incomplete or waiting for a refresh."
    return f"The AI map has not described {path} yet."


def _missing_role(status: str, subject_kind: str) -> str:
    subject = "repository" if subject_kind == "repository" else "file"
    if status == "excluded":
        return f"No AI description is expected while this {subject} remains outside AI mapping."
    return f"The AI map does not have an up-to-date description of what this {subject} does."


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _confidence_meaning(status: str, confidence: float) -> str:
    if status not in {"current", "intrinsic_current"}:
        return "No evidence-strength rating is available because this file has no current AI description."
    strength = "strong" if confidence >= 0.7 else "mixed" if confidence >= 0.4 else "weak"
    return (
        f"Support for this AI description is {strength}. This measures its evidence, not the "
        "quality of the code."
    )
