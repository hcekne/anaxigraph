"""Plain-language consolidation and removal advice for people and coding agents."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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
            "A candidate has signs of being unused. Static source links cannot show every use "
            "through configuration, frameworks, reflection, plugins, or generated code."
        ),
        "what_to_do": (
            "Trace each candidate through source, configuration, runtime registration, and tests. "
            "Only remove it after those checks agree and focused tests still pass."
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
            "This result does not authorize deletion. Remove the item only after source, "
            "configuration, runtime registration, and focused tests all show that it is unused."
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
    return observations or ["The semantic analysis did not supply a concrete observation."]


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
            "Splitting code can clarify responsibilities, but only when the new boundary is more "
            "useful than the extra files and connections it creates."
        ),
    }.get(
        recommendation,
        "The current module boundary may be worth checking before nearby work changes.",
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
        f"Name the distinct responsibilities inside {path}, choose the smallest useful boundary, "
        "and move one responsibility at a time."
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
        f"Read the public contracts and focused tests for {targets}.",
        "Check callers, stored data, configuration, and runtime registration before moving code.",
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
            f"Do not delete {target} yet. Both the semantic review and source map found signs that "
            "it may be unused, but runtime use has not been ruled out."
        )
    return (
        f"Do not delete {target} yet. The source map found no direct incoming static link, but "
        "that does not prove the item is unused at runtime."
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
        f"Trace {target} through callers, configuration, runtime registration, and focused tests "
        "before deciding whether to keep or remove it."
    )


def _dead_code_evidence(value: Any) -> str:
    text = str(value or "").strip()
    normalized = text.lower().replace(" ", "_")
    if normalized in {"incoming_references=0", "incoming_static_relationships=0"}:
        return "The indexed source contains no direct incoming static link to this item."
    return f"The analysis reported this evidence: {_sentence(text)}"


def _plain_suppression_reason(value: Any) -> str:
    text = str(value or "").strip()
    if "deterministic reachability" in text.lower():
        return (
            "The source map did not independently confirm that this exact file or symbol is unused."
        )
    if "dynamic registration" in text.lower():
        return (
            "Configuration, framework registration, reflection, plugins, or generated wiring can "
            "use code without a direct static link."
        )
    return _sentence(text)


def _candidate_text(candidates: Sequence[str]) -> str:
    names = [str(item) for item in candidates if str(item).strip()]
    return ", ".join(names) if names else "nearby modules"


def _lower_sentence(value: Any) -> str:
    text = _sentence(value)
    return text[:1].lower() + text[1:] if text else text


def _sentence(value: Any) -> str:
    text = str(value or "").strip()
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
