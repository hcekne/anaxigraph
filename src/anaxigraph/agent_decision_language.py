"""Plain-language consolidation and removal advice for people and coding agents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from anaxigraph.semantic_file_language import explain_specialist_terms

CONSOLIDATION_LANGUAGE_VERSION = "consolidation-explanation-v1"
DEAD_CODE_LANGUAGE_VERSION = "dead-code-explanation-v1"


def consolidation_explanation(
    *,
    path: str,
    status: str,
    recommendation: str,
    score: int,
    rationale: str,
    candidates: Sequence[str],
    evidence: Sequence[str],
    counter_evidence: Sequence[str],
) -> dict[str, Any]:
    """Explain a merge, split, or keep-separate assessment without score-first shorthand."""

    return {
        "version": CONSOLIDATION_LANGUAGE_VERSION,
        "conclusion": _consolidation_conclusion(path, status, recommendation, candidates),
        "what_anaxigraph_saw": _consolidation_observations(rationale, evidence),
        "why_it_may_matter": _consolidation_reason(recommendation),
        "what_to_do": _consolidation_action(path, status, recommendation, candidates),
        "reasons_to_be_careful": _consolidation_cautions(status, recommendation, counter_evidence),
        "how_to_check": _consolidation_checks(path, recommendation, candidates),
        "evidence_strength": {
            "value": _score(score),
            "meaning": (
                f"Support for this recommendation is {_strength(score)}. This number measures the "
                "available evidence for this suggestion; it is not a code-quality grade and does "
                "not authorize a refactor."
            ),
        },
    }


def dead_code_policy_explanation(candidate_count: int) -> dict[str, Any]:
    noun = "item" if candidate_count == 1 else "items"
    return {
        "version": DEAD_CODE_LANGUAGE_VERSION,
        "summary": (
            f"AnaxiGraph found {candidate_count} {noun} worth checking, but it is not saying that "
            "any of them can be deleted yet."
        ),
        "what_a_candidate_means": (
            "A candidate has signs of being unused. Direct links found in source code cannot show "
            "uses through settings, framework hooks, code that looks up names while running, "
            "plugins, or generated code."
        ),
        "what_to_do": (
            "Trace each candidate through source code, settings, code that registers it when the "
            "application starts or runs, and tests. Only remove it after those checks agree and "
            "focused tests still pass."
        ),
    }


def dead_code_explanation(
    *,
    module: str,
    path_or_symbol: str,
    status: str,
    rationale: str,
    evidence: Sequence[str],
    counter_evidence: Sequence[str],
    suppression_reasons: Sequence[str],
    verification: str,
) -> dict[str, Any]:
    """Explain why an apparently unused item still lacks deletion authorization."""

    target = path_or_symbol or module or "this item"
    return {
        "version": DEAD_CODE_LANGUAGE_VERSION,
        "conclusion": _dead_code_conclusion(target, status),
        "what_anaxigraph_saw": _dead_code_observations(rationale, evidence),
        "why_it_is_not_safe_to_remove": _dead_code_cautions(counter_evidence, suppression_reasons),
        "what_to_do": _dead_code_action(target, verification),
        "deletion_rule": (
            "This result does not authorize deletion. Remove the item only after source code, "
            "settings, code that registers it when the application starts or runs, and focused "
            "tests all show that it is unused."
        ),
    }


def _consolidation_conclusion(
    path: str, status: str, recommendation: str, candidates: Sequence[str]
) -> str:
    targets = _candidate_text(candidates)
    if status == "keep_separate":
        return f"Keep {path} separate from {targets} for now."
    if status == "candidate" and recommendation == "merge":
        return (
            f"Consider combining {path} with {targets}, but test the proposal before refactoring."
        )
    if status == "candidate" and recommendation == "split":
        return f"Consider splitting {path}, but test the proposed boundaries before refactoring."
    return f"Do not merge or split {path} based on this result yet; the evidence is not complete enough."


def _consolidation_observations(rationale: str, evidence: Sequence[str]) -> list[str]:
    observations = [_sentence(item) for item in evidence if str(item).strip()]
    if rationale.strip() and rationale.strip() not in evidence:
        observations.insert(0, _sentence(rationale))
    return observations or ["The AI review did not supply a concrete observation."]


def _consolidation_reason(recommendation: str) -> str:
    return {
        "keep": (
            "Keeping distinct responsibilities apart can make ownership and public behavior easier "
            "to understand."
        ),
        "merge": (
            "Combining code can remove duplicated responsibility, but only when the parts really "
            "belong together and change together."
        ),
        "split": (
            "Splitting code can make each job clearer, but only when the new division between "
            "files is more useful than the extra files and connections it creates."
        ),
    }.get(
        recommendation,
        "The current way this code is divided between files may be worth checking before nearby "
        "work changes.",
    )


def _consolidation_action(
    path: str, status: str, recommendation: str, candidates: Sequence[str]
) -> str:
    if status != "candidate":
        return f"Leave {path} as it is unless stronger code, history, and test evidence changes the result."
    if recommendation == "merge":
        return (
            f"Compare {path} with {_candidate_text(candidates)}. Combine only the responsibility "
            "that is truly shared, while preserving public behavior."
        )
    return (
        f"Name the distinct jobs inside {path}, choose the smallest useful division between files, "
        "and move one job at a time."
    )


def _consolidation_cautions(
    status: str, recommendation: str, counter_evidence: Sequence[str]
) -> list[str]:
    cautions = [_sentence(item) for item in counter_evidence if str(item).strip()]
    if status == "review":
        cautions.append(
            "The current evidence is not strong and balanced enough to recommend a change."
        )
    if recommendation in {"merge", "split"}:
        cautions.append(
            "The index does not currently show whether these files usually change together over time."
        )
    return _unique(cautions) or ["No structural change is required by this assessment."]


def _consolidation_checks(path: str, recommendation: str, candidates: Sequence[str]) -> list[str]:
    targets = f"{path} and {_candidate_text(candidates)}" if candidates else path
    checks = [
        f"Read the caller-visible behavior, names, and focused tests for {targets}.",
        "Check callers, stored data, settings, and code that registers behavior when the "
        "application starts or runs before moving code.",
    ]
    if recommendation in {"merge", "split"}:
        checks.append(
            "After a small change, run focused tests and compare a fresh AnaxiGraph scan."
        )
    return checks


def _dead_code_conclusion(target: str, status: str) -> str:
    if status == "suppressed":
        return (
            f"Do not delete {target}. An AI raised it as possibly unused, but the source map did "
            "not independently confirm that exact item."
        )
    if status == "corroborated_candidate":
        return (
            f"Do not delete {target} yet. Both an AI review of what the code does and the source "
            "map found signs that it may be unused, but use while the application runs has not "
            "been ruled out."
        )
    return (
        f"Do not delete {target} yet. The source map found no direct source-code link to it, but "
        "that does not prove the item is unused while the application runs."
    )


def _dead_code_observations(rationale: str, evidence: Sequence[str]) -> list[str]:
    result = [_dead_code_evidence(item) for item in evidence if str(item).strip()]
    if rationale.strip():
        result.insert(0, f"The analysis raised this candidate because {_lower_sentence(rationale)}")
    return result or ["The analysis supplied no concrete evidence beyond naming the candidate."]


def _dead_code_cautions(
    counter_evidence: Sequence[str], suppression_reasons: Sequence[str]
) -> list[str]:
    cautions = [
        f"A possible sign that it is still used: {_lower_sentence(item)}"
        for item in counter_evidence
        if str(item).strip()
    ]
    cautions.extend(_plain_suppression_reason(item) for item in suppression_reasons)
    return _unique(cautions)


def _dead_code_action(target: str, verification: str) -> str:
    if verification.strip():
        return f"Before changing {target}, {_lower_sentence(verification)}"
    return (
        f"Trace {target} through callers, settings, code that registers it when the application "
        "starts or runs, and focused tests before deciding whether to keep or remove it."
    )


def _dead_code_evidence(value: Any) -> str:
    text = str(value or "").strip()
    normalized = text.lower().replace(" ", "_")
    if normalized in {"incoming_references=0", "incoming_static_relationships=0"}:
        return "The indexed source contains no direct source-code link to this item."
    key, separator, recorded = normalized.partition("=")
    if not separator:
        return f"The analysis reported this evidence: {_sentence(text)}"
    if key == "days_since_change":
        return f"Git history shows no change to this item for {recorded} days."
    if key == "internal_resolution_rate":
        return _resolution_evidence(recorded)
    if key == "entry_point_capability":
        return _capability_evidence(recorded, "whether the item starts the program")
    if key == "registration_capability":
        return _capability_evidence(recorded, "whether running code can register the item")
    if key == "detected_entry_points":
        return f"The source-code reader found {recorded} signs that this item starts the program."
    if key == "detected_registrations":
        return (
            f"The source-code reader found {recorded} places that register this item for later use."
        )
    if key == "parse_status":
        return _parse_evidence(recorded)
    return f"The analysis reported this evidence: {_sentence(text)}"


def _resolution_evidence(value: str) -> str:
    try:
        percent = round(float(value) * 100)
    except ValueError:
        return "AnaxiGraph could not explain how completely it connected source-code links."
    return (
        f"AnaxiGraph connected {percent}% of internal source-code references to one indexed file. "
        "Unclear links could still hide a caller."
    )


def _capability_evidence(level: str, fact: str) -> str:
    detail = {
        "unavailable": "could not check",
        "heuristic": "could only make a rough estimate of",
        "lexical": "could check names and code words for",
        "structural": "could check parsed code structure for",
        "deep": "could check detailed code relationships for",
    }.get(level, "reported an unknown amount of information about")
    return f"The source-code reader {detail} {fact}."


def _parse_evidence(status: str) -> str:
    return {
        "parsed": "The source-code reader successfully parsed this file's structure.",
        "partial": "The source-code reader understood only part of this file's structure.",
        "fallback": "AnaxiGraph could read this file only as plain text, so code links may be missing.",
        "failed": "The source-code reader could not understand this file's structure.",
    }.get(status, f"The source-code reader reported its file-reading state as {status}.")


def _plain_suppression_reason(value: Any) -> str:
    text = str(value or "").strip()
    if "deterministic reachability" in text.lower():
        return (
            "The source map did not independently confirm that this exact file or symbol is unused."
        )
    if "dynamic registration" in text.lower():
        return (
            "Settings, framework setup, code that looks up names while running, plugins, or "
            "generated connection code can use this item without a direct source-code link."
        )
    return _sentence(text)


def _candidate_text(candidates: Sequence[str]) -> str:
    names = [str(item) for item in candidates if str(item).strip()]
    return ", ".join(names) if names else "nearby modules"


def _lower_sentence(value: Any) -> str:
    text = _sentence(value)
    return text[:1].lower() + text[1:] if text else text


def _sentence(value: Any) -> str:
    text = explain_specialist_terms(value)
    if text and text[-1] not in ".?!":
        text += "."
    return text


def _score(value: Any) -> int:
    try:
        return max(0, min(100, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _strength(value: Any) -> str:
    score = _score(value)
    if score >= 70:
        return "strong"
    if score >= 40:
        return "mixed"
    return "weak"


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
