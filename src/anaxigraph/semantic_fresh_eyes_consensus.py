"""Classify two fresh-eyes generations' recommendations as aligned, conflicting, or unmatched.

The comparison is deliberately lexical and model-free. Each recommendation is reduced to normalized
words from its title, mission capability and affected contracts, to the file names it quotes, and to
the review contract's own ``action`` value; two recommendations are paired when those words overlap
enough, and the pair is ``aligned`` only when both sides also chose the same action. A rejected idea
on one side that matches a recommendation on the other is ``conflicting``: the generations disagree
about whether the change is worth making at all. Nothing here reads a database or calls a model, so
the same two documents always produce the same bytes and the same fingerprint.

What the result is not is a verdict. Two reviewers describing one change in different words score
zero here, and two reviewers describing different changes in a shared vocabulary score high, which
is why every payload states that limit in its own caveats. This pass exists to narrow what a reader
has to compare by hand, never to declare that a generation was right.
"""

from __future__ import annotations

import re
from typing import Any

from anaxigraph.agent_lexicon import jaccard, normalized_terms
from anaxigraph.semantic_fresh_eyes_contract import semantic_digest

FRESH_EYES_ALIGNMENT_VERSION = "fresh-eyes-alignment-v1"
ALIGNMENT_METHOD = "lexical"
MATCH_THRESHOLD = 0.34
CANDIDATE_THRESHOLD = 0.0
PATH_WEIGHT = 0.3

ALIGNMENT_CAVEATS = (
    "This alignment is lexical: it compares normalized words, quoted file names, and the "
    "recommendation action, never meaning.",
    "Lexical matching cannot detect the same intent expressed in different words, so an unmatched "
    "recommendation is not evidence that the other generation missed it, and an aligned pair is "
    "not proof that the two generations mean the same thing.",
    "Read every label here as evidence for a reader, never as a verdict on which generation is "
    "right; deciding that needs a human or a separate adjudication pass over these candidates.",
)
_SAME_GENERATION_CAVEAT = (
    "Both sides name the same recorded generation, so this alignment compares a review with itself."
)

_SOURCE_SUFFIXES = "py|js|jsx|mjs|cjs|ts|tsx|rs|go|java|rb|sql|json|ya?ml|md|html|css|toml"
_PATH_TOKEN = re.compile(rf"\b(\w[\w-]*\.(?:{_SOURCE_SUFFIXES}))\b", re.IGNORECASE)
_TERM_FIELDS = ("title", "mission_capability", "affected_contracts")
_PATH_FIELDS = (*_TERM_FIELDS, "current_evidence", "expected_deletions")
_IDEA_TERM_FIELDS = ("idea",)
_IDEA_PATH_FIELDS = ("idea", "evidence")


def align_reviews(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Report where two fresh-eyes review documents lexically agree, clash, or stand alone."""

    sides = (_side_items(left), _side_items(right))
    conflicting = _rejected_conflicts(sides)
    spoken = _claimed_indexes(conflicting)
    pairs = _scored_pairs(sides[0]["recommendations"], sides[1]["recommendations"])
    matched = _greedy_matches(pairs, spoken)
    aligned = [_pair_entry(item) for item in matched if item["signals"]["same_action"]]
    conflicting = sorted(
        conflicting
        + [_action_conflict(item) for item in matched if not item["signals"]["same_action"]],
        key=_entry_order,
    )
    claimed = _claimed_indexes(conflicting + aligned)
    return {
        "contract_version": FRESH_EYES_ALIGNMENT_VERSION,
        "method": ALIGNMENT_METHOD,
        "pairs": [_pair_entry(item, label=_label(item, aligned, conflicting)) for item in pairs],
        "aligned": aligned,
        "conflicting": conflicting,
        "unmatched_left": _unmatched(sides[0]["recommendations"], claimed["left"]),
        "unmatched_right": _unmatched(sides[1]["recommendations"], claimed["right"]),
        "facts": _facts(sides, aligned, conflicting),
        "caveats": list(ALIGNMENT_CAVEATS),
        "fingerprint": semantic_digest(_fingerprint_input(sides)),
    }


def compare_generations(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Align the review documents of two fresh-eyes status payloads and name both sides."""

    alignment = align_reviews(left.get("strategy"), right.get("strategy"))
    identities = (_side_identity(left), _side_identity(right))
    if identities[0] == identities[1]:
        alignment["caveats"] = [*alignment["caveats"], _SAME_GENERATION_CAVEAT]
    return {"left": identities[0], "right": identities[1], **alignment}


def _side_identity(payload: dict[str, Any]) -> dict[str, Any]:
    strategy = payload.get("strategy") or {}
    return {
        "review_generation": payload.get("review_generation"),
        "snapshot_id": payload.get("snapshot_id"),
        "state": payload.get("state"),
        "recommendation_count": len(strategy.get("recommendations") or []),
        "rejected_idea_count": len(strategy.get("rejected_ideas") or []),
        "confidence": strategy.get("confidence"),
    }


def _side_items(document: dict[str, Any] | None) -> dict[str, Any]:
    value = document or {}
    return {
        "recommendations": [
            _item(entry, index, "recommendation", _TERM_FIELDS, _PATH_FIELDS)
            for index, entry in enumerate(_entries(value.get("recommendations")))
        ],
        "rejected_ideas": [
            _item(entry, index, "rejected_idea", _IDEA_TERM_FIELDS, _IDEA_PATH_FIELDS)
            for index, entry in enumerate(_entries(value.get("rejected_ideas")))
        ],
        "confidence": value.get("confidence"),
    }


def _entries(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _item(
    entry: dict[str, Any],
    index: int,
    kind: str,
    term_fields: tuple[str, ...],
    path_fields: tuple[str, ...],
) -> dict[str, Any]:
    rank = entry.get("rank")
    return {
        "kind": kind,
        "index": index,
        "rank": int(rank) if isinstance(rank, int) and not isinstance(rank, bool) else index + 1,
        "title": str(entry.get("title") or entry.get("idea") or ""),
        "action": str(entry["action"]) if entry.get("action") else None,
        "terms": normalized_terms(_text(entry, term_fields)),
        "paths": _path_tokens(_text(entry, path_fields)),
    }


def _text(entry: dict[str, Any], fields: tuple[str, ...]) -> str:
    parts: list[str] = []
    for field in fields:
        value = entry.get(field)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if isinstance(item, str | int | float))
    return " ".join(parts)


def _path_tokens(text: str) -> set[str]:
    return {match.group(1).lower() for match in _PATH_TOKEN.finditer(text)}


def _score(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Score one candidate pair in [0, 1]; quoted file names can only raise a token overlap."""

    token = jaccard(left["terms"], right["terms"])
    path = jaccard(left["paths"], right["paths"])
    signals = {
        "token_jaccard": round(token, 4),
        "path_jaccard": round(path, 4),
        "shared_terms": sorted(left["terms"] & right["terms"]),
        "shared_paths": sorted(left["paths"] & right["paths"]),
        "same_action": bool(left["action"]) and left["action"] == right["action"],
    }
    return round(min(1.0, token + PATH_WEIGHT * path), 4), signals


def _scored_pairs(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = []
    for one in left:
        for other in right:
            score, signals = _score(one, other)
            if score > CANDIDATE_THRESHOLD:
                pairs.append({"left": one, "right": other, "score": score, "signals": signals})
    return sorted(pairs, key=_pair_order)


def _pair_order(pair: dict[str, Any]) -> tuple[Any, ...]:
    """Order pairs so that swapping the two sides cannot change the order or the winner."""

    left, right = pair["left"], pair["right"]
    return (
        -pair["score"],
        sorted((left["rank"], right["rank"])),
        sorted((left["title"], right["title"])),
    )


def _greedy_matches(
    pairs: list[dict[str, Any]], spoken: dict[str, set[int]]
) -> list[dict[str, Any]]:
    """Assign each recommendation at most one partner, best score first, ties broken symmetrically."""

    used_left, used_right = set(spoken["left"]), set(spoken["right"])
    matches = []
    for pair in pairs:
        left_index, right_index = pair["left"]["index"], pair["right"]["index"]
        if pair["score"] < MATCH_THRESHOLD or left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        matches.append(pair)
    return matches


def _rejected_conflicts(sides: tuple[dict[str, Any], dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag a rejected idea on one side that lexically matches the other side's recommendation."""

    conflicts = []
    for idea in sides[0]["rejected_ideas"]:
        for item in sides[1]["recommendations"]:
            conflicts.extend(_rejected_entry(idea, item, rejected_side="left"))
    for idea in sides[1]["rejected_ideas"]:
        for item in sides[0]["recommendations"]:
            conflicts.extend(_rejected_entry(item, idea, rejected_side="right"))
    return conflicts


def _rejected_entry(
    left: dict[str, Any], right: dict[str, Any], *, rejected_side: str
) -> list[dict[str, Any]]:
    score, signals = _score(left, right)
    if score < MATCH_THRESHOLD:
        return []
    kept = right if rejected_side == "left" else left
    return [
        {
            "kind": "rejected_vs_recommended",
            "left": _reference(left),
            "right": _reference(right),
            "score": score,
            "signals": signals,
            "detail": (
                f"The {rejected_side} generation rejected this idea while the other generation "
                f"recommends it as {kept['action'] or 'a change'}."
            ),
        }
    ]


def _action_conflict(pair: dict[str, Any]) -> dict[str, Any]:
    left, right = pair["left"], pair["right"]
    return {
        "kind": "action_conflict",
        "left": _reference(left),
        "right": _reference(right),
        "score": pair["score"],
        "signals": pair["signals"],
        "detail": (
            f"The wording overlaps but the generations chose different actions: "
            f"{left['action'] or 'none'} versus {right['action'] or 'none'}."
        ),
    }


def _pair_entry(pair: dict[str, Any], label: str | None = None) -> dict[str, Any]:
    entry = {
        "left": _reference(pair["left"]),
        "right": _reference(pair["right"]),
        "score": pair["score"],
        "signals": pair["signals"],
    }
    return {**entry, "label": label} if label else entry


def _reference(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("kind", "index", "rank", "title", "action")}


def _entry_order(entry: dict[str, Any]) -> tuple[Any, ...]:
    titles = sorted((entry["left"]["title"], entry["right"]["title"]))
    return (-entry["score"], entry["kind"], titles)


def _claimed_indexes(entries: list[dict[str, Any]]) -> dict[str, set[int]]:
    """Collect the recommendation positions each side has already had classified."""

    claimed: dict[str, set[int]] = {"left": set(), "right": set()}
    for entry in entries:
        for side in ("left", "right"):
            if entry[side]["kind"] == "recommendation":
                claimed[side].add(entry[side]["index"])
    return claimed


def _label(
    pair: dict[str, Any], aligned: list[dict[str, Any]], conflicting: list[dict[str, Any]]
) -> str:
    marker = (pair["left"]["index"], pair["right"]["index"])
    for label, entries in (("aligned", aligned), ("conflicting", conflicting)):
        for entry in entries:
            if (
                entry["left"]["index"],
                entry["right"]["index"],
            ) == marker and _both_recommendations(entry):
                return label
    return "candidate"


def _both_recommendations(entry: dict[str, Any]) -> bool:
    return entry["left"]["kind"] == "recommendation" and entry["right"]["kind"] == "recommendation"


def _unmatched(items: list[dict[str, Any]], claimed: set[int]) -> list[dict[str, Any]]:
    return [_reference(item) for item in items if item["index"] not in claimed]


def _facts(
    sides: tuple[dict[str, Any], dict[str, Any]],
    aligned: list[dict[str, Any]],
    conflicting: list[dict[str, Any]],
) -> dict[str, Any]:
    """Report the exact counts behind the labels, separately from the lexical judgement."""

    return {
        "left": _side_facts(sides[0]),
        "right": _side_facts(sides[1]),
        "aligned": len(aligned),
        "conflicting": len(conflicting),
        "rejected_vs_recommended": len(
            [item for item in conflicting if item["kind"] == "rejected_vs_recommended"]
        ),
        "shared_paths": sorted(
            {path for item in aligned + conflicting for path in item["signals"]["shared_paths"]}
        ),
        "match_threshold": MATCH_THRESHOLD,
        "candidate_threshold": CANDIDATE_THRESHOLD,
    }


def _side_facts(side: dict[str, Any]) -> dict[str, Any]:
    actions: dict[str, int] = {}
    for item in side["recommendations"]:
        key = item["action"] or "unstated"
        actions[key] = actions.get(key, 0) + 1
    return {
        "recommendations": len(side["recommendations"]),
        "rejected_ideas": len(side["rejected_ideas"]),
        "actions": dict(sorted(actions.items())),
        "confidence": side["confidence"],
    }


def _fingerprint_input(sides: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    """Fingerprint the normalized inputs and the thresholds, never the labels they produced."""

    return {
        "contract_version": FRESH_EYES_ALIGNMENT_VERSION,
        "method": ALIGNMENT_METHOD,
        "match_threshold": MATCH_THRESHOLD,
        "candidate_threshold": CANDIDATE_THRESHOLD,
        "path_weight": PATH_WEIGHT,
        "sides": [
            [
                {
                    "kind": item["kind"],
                    "rank": item["rank"],
                    "title": item["title"],
                    "action": item["action"],
                    "terms": sorted(item["terms"]),
                    "paths": sorted(item["paths"]),
                }
                for group in ("recommendations", "rejected_ideas")
                for item in side[group]
            ]
            for side in sides
        ],
    }
