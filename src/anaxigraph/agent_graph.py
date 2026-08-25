"""Lexically rank files and expand bounded graph context for agents."""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from math import log
from pathlib import Path
from typing import Any

from anaxigraph.agent_graph_read import (
    _attach_architecture_map as _attach_architecture_map,
)
from anaxigraph.agent_graph_read import (
    _interfaces as _interfaces,
)
from anaxigraph.agent_graph_read import (
    _projected_graph_maps as _projected_graph_maps,
)
from anaxigraph.agent_graph_read import _public_interfaces as _public_interfaces
from anaxigraph.agent_graph_read import _symbols as _symbols
from anaxigraph.agent_lexicon import GOAL_STOPWORDS, WORD_PATTERN, split_camel
from anaxigraph.agent_scope_evidence import (
    _applicable_findings as _applicable_findings,
)
from anaxigraph.agent_scope_evidence import (
    _applicable_rules as _applicable_rules,
)


def _rank_files(
    connection: sqlite3.Connection,
    snapshot_id: int,
    files: dict[int, dict[str, Any]],
    goal: str,
) -> list[tuple[float, int]]:
    words, normalized_goal = _goal_terms(goal)
    documents = _ranking_documents(connection, snapshot_id, files)
    document_frequency = {
        word: sum(1 for values in documents.values() if word in " ".join(values)) for word in words
    }
    ranked = [
        (
            _document_score(
                documents[artifact_id],
                words,
                document_frequency,
                normalized_goal,
                len(files),
                is_test=item["artifact_type"] == "test",
            ),
            artifact_id,
        )
        for artifact_id, item in files.items()
    ]
    return sorted(
        (pair for pair in ranked if pair[0]),
        key=lambda pair: (-pair[0], files[pair[1]]["path"]),
    )


def _goal_terms(goal: str) -> tuple[set[str], str]:
    words = {
        word.lower().replace("-", "_")
        for word in WORD_PATTERN.findall(split_camel(goal))
        if word.lower() not in GOAL_STOPWORDS and len(word) > 1
    }
    words.update(word[:-1] for word in tuple(words) if word.endswith("s") and len(word) > 4)
    normalized = "_".join(
        word.lower() for word in WORD_PATTERN.findall(split_camel(goal)) if len(word) > 2
    )
    return words, normalized


def _ranking_documents(
    connection: sqlite3.Connection,
    snapshot_id: int,
    files: dict[int, dict[str, Any]],
) -> dict[int, tuple[str, ...]]:
    symbols: dict[int, str] = defaultdict(str)
    for row in connection.execute(
        """
        SELECT fv.artifact_id, GROUP_CONCAT(s.name, ' ') AS names
        FROM projected_symbols s JOIN projected_file_versions fv ON fv.id = s.artifact_version_id
        WHERE fv.snapshot_id = ? GROUP BY fv.artifact_id
        """,
        (snapshot_id,),
    ):
        symbols[int(row["artifact_id"])] = row["names"] or ""
    return {
        artifact_id: _ranking_document(item, symbols[artifact_id])
        for artifact_id, item in files.items()
    }


def _ranking_document(item: dict[str, Any], symbol_names: str) -> tuple[str, ...]:
    path = item["path"].lower().replace("-", "_")
    semantic = item.get("semantic") or {}
    semantic_values = (
        semantic.get("detailed_summary"),
        semantic.get("architecture_role"),
        semantic.get("placement_guidance"),
        *(semantic.get("responsibilities") or []),
        *(semantic.get("domain_concepts") or []),
    )
    semantic_text = " ".join(str(value) for value in semantic_values if value)
    return (
        path,
        Path(path).stem,
        (item["summary"] or "").lower().replace("-", "_"),
        symbol_names.lower().replace("-", "_"),
        semantic_text.lower().replace("-", "_"),
    )


def _document_score(
    document: tuple[str, ...],
    words: set[str],
    document_frequency: dict[str, int],
    normalized_goal: str,
    file_count: int,
    *,
    is_test: bool,
) -> float:
    path, basename, summary, symbol_text, semantic_text = document
    score = 0.0
    for word in words:
        inverse_frequency = 1 + log((file_count + 1) / (document_frequency[word] + 1))
        score += path.count(word) * 7 * inverse_frequency
        score += basename.count(word) * 8 * inverse_frequency
        score += summary.count(word) * 3 * inverse_frequency
        score += symbol_text.count(word) * 4 * inverse_frequency
        score += semantic_text.count(word) * 2.5 * inverse_frequency
    if normalized_goal and normalized_goal in path.replace("/", "_"):
        score += 30
    return score * 0.45 if is_test else score


def _select_primary(
    ranked: list[tuple[float, int]],
    files: dict[int, dict[str, Any]],
    *,
    limit: int,
) -> list[int]:
    selected: list[int] = []
    per_directory: dict[str, int] = defaultdict(int)
    per_group: dict[str, int] = defaultdict(int)
    for _, artifact_id in ranked:
        item = files[artifact_id]
        directory = str(Path(item["path"]).parent)
        group = item["declared_group"] or item["inferred_group"] or "ungrouped"
        if per_directory[directory] >= 2 or per_group[group] >= 5:
            continue
        selected.append(artifact_id)
        per_directory[directory] += 1
        per_group[group] += 1
        if len(selected) == limit:
            return selected
    for _, artifact_id in ranked:
        if artifact_id not in selected:
            selected.append(artifact_id)
            if len(selected) == limit:
                break
    return selected


def _expand_relevant(
    seeds: list[int],
    outgoing: dict[int, set[int]],
    incoming: dict[int, set[int]],
    files: dict[int, dict[str, Any]],
    lexical_scores: dict[int, float],
    *,
    depth: int,
    limit: int,
) -> tuple[set[int], dict[int, float]]:
    return _expand_relevant_limited(
        seeds,
        outgoing,
        incoming,
        files,
        lexical_scores,
        depth=depth,
        limit=limit,
    )


def _expand_relevant_limited(
    seeds: list[int],
    outgoing: dict[int, set[int]],
    incoming: dict[int, set[int]],
    files: dict[int, dict[str, Any]],
    lexical_scores: dict[int, float],
    *,
    depth: int,
    limit: int,
) -> tuple[set[int], dict[int, float]]:
    seen = set(seeds)
    frontier = set(seeds)
    distance: dict[int, int] = {item: 0 for item in seeds}
    for current_depth in range(1, max(0, depth) + 1):
        next_frontier: set[int] = set()
        for artifact_id in frontier:
            degree = len(outgoing[artifact_id]) + len(incoming[artifact_id])
            if current_depth > 1 and degree > 80:
                continue
            next_frontier.update(outgoing[artifact_id])
            next_frontier.update(incoming[artifact_id])
        next_frontier.difference_update(seen)
        for artifact_id in next_frontier:
            distance[artifact_id] = current_depth
        seen.update(next_frontier)
        frontier = next_frontier
    related = seen - set(seeds)
    seed_parents = {str(Path(files[item]["path"]).parent) for item in seeds}
    seed_groups = {files[item]["declared_group"] or files[item]["inferred_group"] for item in seeds}
    scores: dict[int, float] = {}
    for artifact_id in related:
        direct_connections = len((outgoing[artifact_id] | incoming[artifact_id]) & set(seeds))
        item = files[artifact_id]
        degree = len(outgoing[artifact_id]) + len(incoming[artifact_id])
        score = 100 / max(1, distance[artifact_id])
        score += direct_connections * 60
        score += lexical_scores.get(artifact_id, 0) * 0.35
        if str(Path(item["path"]).parent) in seed_parents:
            score += 25
        if (item["declared_group"] or item["inferred_group"]) in seed_groups:
            score += 8
        score -= max(0, degree - 20) * 0.8
        scores[artifact_id] = score
    ordered = sorted(related, key=lambda item: (-scores[item], files[item]["path"]))[:limit]
    selected = set(ordered)
    return selected, {item: scores[item] for item in selected}


def _reverse_reachable(target_id: int, incoming: dict[int, set[int]], *, limit: int) -> set[int]:
    seen: set[int] = set()
    queue = deque(incoming[target_id])
    while queue and len(seen) < limit:
        current = queue.popleft()
        if current in seen or current == target_id:
            continue
        seen.add(current)
        queue.extend(incoming[current] - seen)
    return seen


def _related_tests(
    files: dict[int, dict[str, Any]],
    outgoing: dict[int, set[int]],
    incoming: dict[int, set[int]],
    primary_ids: set[int],
    related_ids: set[int],
    goal: str,
    *,
    limit: int,
) -> set[str]:
    relevant_names = {
        Path(files[item]["path"]).stem.lower().removeprefix("test_").removesuffix("_test")
        for item in primary_ids
    }
    goal_words = {word.lower() for word in WORD_PATTERN.findall(goal)}
    scored: list[tuple[float, str]] = []
    for artifact_id, item in files.items():
        if item["artifact_type"] != "test":
            continue
        neighbors = outgoing[artifact_id] | incoming[artifact_id]
        score = 12 * len(neighbors & primary_ids) + 3 * len(neighbors & related_ids)
        normalized = item["path"].lower()
        score += 6 * sum(1 for name in relevant_names if name and name in normalized)
        score += sum(1 for word in goal_words if len(word) > 3 and word in normalized)
        if score:
            scored.append((score, item["path"]))
    return {
        path for _, path in sorted(scored, key=lambda value: (-value[0], value[1]))[: max(1, limit)]
    }
