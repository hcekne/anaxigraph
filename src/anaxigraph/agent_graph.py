"""Graph loading, semantic ranking, and bounded context expansion for agents."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from math import log
from pathlib import Path
from typing import Any

from anaxigraph.agent_lexicon import GOAL_STOPWORDS, WORD_PATTERN, split_camel
from anaxigraph.config import path_matches
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection


def _graph_maps(
    connection: sqlite3.Connection, snapshot_id: int
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]], dict[int, set[int]]]:
    files = {
        int(row["artifact_id"]): dict(row)
        for row in connection.execute(
            """
            SELECT fv.*, a.artifact_type FROM projected_file_versions fv
            JOIN artifacts a ON a.id = fv.artifact_id WHERE fv.snapshot_id = ?
            """,
            (snapshot_id,),
        )
    }
    for row in connection.execute(
        """
        SELECT ss.artifact_id, ss.status, ss.reason, sd.value_json, sd.provider,
               sd.model, sd.confidence, sd.document_kind
        FROM semantic_scope_states ss
        LEFT JOIN semantic_documents sd
          ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
        WHERE ss.snapshot_id = ? AND ss.scope_type = 'module'
        """,
        (snapshot_id,),
    ):
        artifact_id = int(row["artifact_id"])
        if artifact_id not in files:
            continue
        value = _json(row["value_json"] or "{}") or {}
        item = files[artifact_id]
        item["deterministic_summary"] = item["summary"]
        if value.get("summary"):
            item["summary"] = value["summary"]
        item["semantic"] = {
            "status": row["status"],
            "reason": row["reason"],
            "source": row["document_kind"],
            "provider": row["provider"],
            "model": row["model"],
            "confidence": row["confidence"],
            "architecture_role": value.get("architecture_role") or "",
            "placement_guidance": value.get("placement_guidance") or "",
            "detailed_summary": value.get("detailed_summary") or "",
            "responsibilities": value.get("responsibilities") or [],
            "domain_concepts": value.get("domain_concepts") or [],
            "extension_points": value.get("extension_points") or [],
            "similar_modules": value.get("similar_modules") or [],
            "pattern_opportunities": (value.get("pattern_opportunities") or [])[:5],
            "consolidation_assessment": value.get("consolidation_assessment"),
            "dead_code_candidates": (value.get("dead_code_candidates") or [])[:5],
            "risks": value.get("risks") or [],
        }
    outgoing: dict[int, set[int]] = defaultdict(set)
    incoming: dict[int, set[int]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT source_artifact_id, target_artifact_id FROM projected_relationships
        WHERE snapshot_id = ? AND target_artifact_id IS NOT NULL
        """,
        (snapshot_id,),
    ):
        source = int(row["source_artifact_id"])
        target = int(row["target_artifact_id"])
        outgoing[source].add(target)
        incoming[target].add(source)
    for artifact_id in files:
        outgoing.setdefault(artifact_id, set())
        incoming.setdefault(artifact_id, set())
    return files, outgoing, incoming


def _projected_graph_maps(
    connection: sqlite3.Connection, snapshot_id: int
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]], dict[int, set[int]]]:
    install_snapshot_projection(connection, snapshot_id)
    return _graph_maps(connection, snapshot_id)


def _rank_files(
    connection: sqlite3.Connection,
    snapshot_id: int,
    files: dict[int, dict[str, Any]],
    goal: str,
) -> list[tuple[float, int]]:
    words = {
        word.lower().replace("-", "_")
        for word in WORD_PATTERN.findall(split_camel(goal))
        if word.lower() not in GOAL_STOPWORDS and len(word) > 1
    }
    words.update(word[:-1] for word in tuple(words) if word.endswith("s") and len(word) > 4)
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
    documents: dict[int, tuple[str, ...]] = {}
    for artifact_id, item in files.items():
        path = item["path"].lower().replace("-", "_")
        basename = Path(path).stem
        summary = (item["summary"] or "").lower().replace("-", "_")
        symbol_text = symbols[artifact_id].lower().replace("-", "_")
        semantic = item.get("semantic") or {}
        semantic_text = (
            " ".join(
                str(value)
                for value in (
                    semantic.get("detailed_summary"),
                    semantic.get("architecture_role"),
                    semantic.get("placement_guidance"),
                    *(semantic.get("responsibilities") or []),
                    *(semantic.get("domain_concepts") or []),
                )
                if value
            )
            .lower()
            .replace("-", "_")
        )
        documents[artifact_id] = (path, basename, summary, symbol_text, semantic_text)
    document_frequency = {
        word: sum(1 for values in documents.values() if word in " ".join(values)) for word in words
    }
    ranked: list[tuple[float, int]] = []
    for artifact_id, item in files.items():
        path, basename, summary, symbol_text, semantic_text = documents[artifact_id]
        score = 0.0
        for word in words:
            inverse_frequency = 1 + log((len(files) + 1) / (document_frequency[word] + 1))
            score += path.count(word) * 7 * inverse_frequency
            score += basename.count(word) * 8 * inverse_frequency
            score += summary.count(word) * 3 * inverse_frequency
            score += symbol_text.count(word) * 4 * inverse_frequency
            score += semantic_text.count(word) * 2.5 * inverse_frequency
        normalized_goal = "_".join(
            word.lower() for word in WORD_PATTERN.findall(split_camel(goal)) if len(word) > 2
        )
        if normalized_goal and normalized_goal in path.replace("/", "_"):
            score += 30
        if item["artifact_type"] == "test":
            score *= 0.45
        if score:
            ranked.append((score, artifact_id))
    return sorted(ranked, key=lambda pair: (-pair[0], files[pair[1]]["path"]))


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


def _interfaces(
    connection: sqlite3.Connection, snapshot_id: int, artifact_ids: list[int]
) -> list[dict[str, Any]]:
    if not artifact_ids:
        return []
    placeholders = ",".join("?" for _ in artifact_ids)
    rows = connection.execute(
        f"""
        SELECT fv.path, s.symbol_type, s.name, s.signature, s.summary
        FROM projected_symbols s
        JOIN projected_file_versions fv ON fv.id = s.artifact_version_id
        WHERE fv.snapshot_id = ? AND fv.artifact_id IN ({placeholders})
          AND s.symbol_type IN ('class', 'api_endpoint', 'database_model')
        ORDER BY fv.path, s.start_line LIMIT 100
        """,
        [snapshot_id, *artifact_ids],
    ).fetchall()
    return [dict(row) for row in rows]


def _applicable_rules(
    connection: sqlite3.Connection,
    repository_id: int,
    files: dict[int, dict[str, Any]],
    artifact_ids: set[int],
) -> list[dict[str, Any]]:
    paths = [files[item]["path"] for item in artifact_ids]
    result: list[dict[str, Any]] = []
    for row in connection.execute(
        """
        SELECT rule_id, rule_type, severity, description, source, config_json
        FROM architecture_rules WHERE repository_id = ? AND enabled = 1
        ORDER BY rule_id
        """,
        (repository_id,),
    ):
        item = dict(row)
        config = _json(item.pop("config_json", "{}"))
        patterns = config.get("paths") if isinstance(config, dict) else None
        if not patterns or any(
            path_matches(path, pattern)
            for path in paths
            for pattern in ([patterns] if isinstance(patterns, str) else patterns)
        ):
            compact = {
                key: value
                for key, value in (config or {}).items()
                if value not in (None, "", [], {}, ())
            }
            result.append(
                {
                    "rule_id": item["rule_id"],
                    "type": item["rule_type"],
                    "severity": item["severity"],
                    **({"description": item["description"]} if item["description"] else {}),
                    "source": item["source"],
                    **({"parameters": compact} if compact else {}),
                }
            )
    return result


def _applicable_findings(
    connection: sqlite3.Connection,
    repository_id: int,
    files: dict[int, dict[str, Any]],
    artifact_ids: set[int],
    primary_ids: set[int],
) -> list[dict[str, Any]]:
    paths = {files[item]["path"] for item in artifact_ids}
    primary_paths = {files[item]["path"] for item in primary_ids}
    result = []
    for row in connection.execute(
        """
        SELECT id, finding_type, severity, confidence, summary, status,
               affected_artifacts_json, recommended_action
        FROM findings WHERE repository_id = ? AND status NOT IN ('resolved', 'dismissed')
        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'error' THEN 1
                 WHEN 'warning' THEN 2 ELSE 3 END, last_detected_at DESC
        LIMIT 500
        """,
        (repository_id,),
    ):
        item = dict(row)
        affected = set(_json(item.pop("affected_artifacts_json", "[]")))
        relevant = affected & paths
        if relevant:
            item["affected_artifacts"] = sorted(affected)
            direct = affected & primary_paths
            severity_score = {
                "critical": 72,
                "error": 62,
                "warning": 42,
                "info": 20,
            }.get(str(item["severity"]), 20)
            score = min(
                100,
                severity_score
                + (18 if direct else 7)
                + min(6, len(relevant) * 2)
                + round(float(item["confidence"] or 0) * 4),
            )
            reasons = [f"{item['severity']} severity"]
            reasons.append(
                "affects a primary task file"
                if direct
                else "affects a dependency in the task context"
            )
            if len(affected) > 1:
                reasons.append(f"spans {len(affected)} files")
            item["priority_score"] = score
            item["priority_reasons"] = reasons
            result.append(item)
    return sorted(
        result,
        key=lambda item: (-int(item["priority_score"]), int(item["id"])),
    )[:12]


def _json(value: str) -> Any:
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None
