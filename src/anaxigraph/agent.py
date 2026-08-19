"""Bounded agent task context, impact traversal, and branch collision analysis."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict, deque
from math import log
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.config import AnaxiGraphConfig, path_matches
from anaxigraph.storage import AnaxiIndex

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")
_STOPWORDS = {
    "add",
    "and",
    "change",
    "create",
    "for",
    "from",
    "implement",
    "in",
    "of",
    "on",
    "the",
    "to",
    "update",
    "with",
}


def agent_scope(
    database: AnaxiIndex,
    *,
    repository_id: int,
    goal: str,
    branch: str | None,
    config: AnaxiGraphConfig,
) -> dict[str, Any]:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        raise ValueError("Repository has not been scanned")
    snapshot_id = int(snapshot["id"])
    with database.connect() as connection:
        files, outgoing, incoming = _graph_maps(connection, snapshot_id)
        ranked = _rank_files(connection, snapshot_id, files, goal)
        primary_ids = _select_primary(
            ranked,
            files,
            limit=min(8, config.agent.context_limit),
        )
        if not primary_ids and files:
            primary_ids = [next(iter(files))]
        related_ids, related_scores = _expand_relevant(
            primary_ids,
            outgoing,
            incoming,
            files,
            lexical_scores={artifact_id: score for score, artifact_id in ranked},
            depth=config.agent.neighbor_depth,
            limit=config.agent.context_limit * 2,
        )
        relevant_ids = set(primary_ids) | related_ids
        tests = _related_tests(
            files,
            outgoing,
            incoming,
            set(primary_ids),
            related_ids,
            goal,
            limit=max(8, config.agent.context_limit // 2),
        )
        protected_ids = {
            artifact_id
            for artifact_id in relevant_ids
            if _is_protected(files[artifact_id]["path"], config)
        }
        rules = _applicable_rules(connection, repository_id, files, relevant_ids)
        findings = _applicable_findings(connection, repository_id, files, relevant_ids)
        interfaces = _interfaces(connection, snapshot_id, primary_ids)

    conflicts = _branch_conflicts(
        Path(repository["path"]),
        {files[item]["path"] for item in relevant_ids},
        branch,
    )
    primary = [_file_summary(files[item]) for item in primary_ids]
    related_order = sorted(
        related_ids,
        key=lambda item: (
            files[item]["artifact_type"] == "test",
            -related_scores.get(item, 0),
            files[item]["path"],
        ),
    )
    related_sorted = [
        _file_summary(files[item]) for item in related_order[: config.agent.context_limit]
    ]
    protected = [_file_summary(files[item]) for item in sorted(protected_ids)]
    conflict_paths = {item["path"] for item in conflicts}
    high_degree = any(len(outgoing[item]) + len(incoming[item]) >= 20 for item in primary_ids)
    risk = "high" if protected or conflicts or high_degree else "medium" if related_ids else "low"
    recommended = [item["path"] for item in primary]
    production_budget = max(len(primary), (config.agent.context_limit * 2) // 3)
    recommended.extend(
        item["path"]
        for item in related_sorted
        if item["path"] not in recommended
        and item["path"] not in tests
        and len(recommended) < production_budget
    )
    recommended.extend(
        path
        for path in sorted(tests)
        if path not in recommended and len(recommended) < config.agent.context_limit
    )
    return {
        "goal": goal,
        "branch": branch,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "primary_files": primary,
        "related_files": related_sorted,
        "protected_files": protected,
        "tests": sorted(tests),
        "interfaces": interfaces,
        "architecture_rules": rules,
        "known_findings": findings,
        "active_branch_conflicts": conflicts,
        "risk": risk,
        "risk_reasons": [
            reason
            for reason, active in (
                ("The task context reaches a protected architecture boundary.", bool(protected)),
                ("Another branch changes a file in this task context.", bool(conflicts)),
                ("A primary module is a high-coupling shared dependency.", high_degree),
            )
            if active
        ],
        "recommended_context": recommended,
        "stats": {
            "primary_files": len(primary),
            "primary_loc": sum(item["lines_of_code"] for item in primary),
            "related_files": len(related_ids),
            "tests": len(tests),
            "protected_files": len(protected),
            "conflicting_files": len(conflict_paths),
        },
    }


def finding_context(
    database: AnaxiIndex,
    *,
    repository_id: int,
    finding_id: int,
    branch: str | None,
    config: AnaxiGraphConfig,
) -> dict[str, Any]:
    """Turn one reviewed finding into structured, agent-ready engineering context."""

    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    finding = database.finding(repository_id, finding_id)
    if finding is None:
        raise ValueError(f"Finding not found: {finding_id}")

    affected = [str(path) for path in finding.get("affected_artifacts") or []]
    goal = f"Address architecture finding #{finding_id}: {finding['summary']}"
    if affected:
        goal += f". Start with {', '.join(affected[:4])}"
    scope = agent_scope(
        database,
        repository_id=repository_id,
        goal=goal,
        branch=branch,
        config=config,
    )

    primary_impact = None
    for path in affected:
        if database.file_details(repository_id, path) is not None:
            primary_impact = impact_analysis(
                database,
                repository_id=repository_id,
                target=path,
                branch=branch,
                config=config,
            )
            break

    recommended_context: list[str] = []
    for path in [*affected, *(scope.get("recommended_context") or [])]:
        if path not in recommended_context:
            recommended_context.append(path)

    tests = set(scope.get("tests") or [])
    protected_paths = {item["path"] for item in scope.get("protected_files") or []}
    if primary_impact:
        tests.update(primary_impact.get("tests_relevant") or [])
        protected_paths.update(primary_impact.get("critical_paths_affected") or [])

    risk_levels = {scope.get("risk", "low")}
    if primary_impact:
        risk_levels.add(primary_impact.get("risk", "low"))
    risk = "high" if "high" in risk_levels else "medium" if "medium" in risk_levels else "low"
    status = str(finding["status"])
    prompt_lines = [
        f"Work on AnaxiGraph finding #{finding_id} in {repository['name']}.",
        f"Goal: {finding['summary']}",
        f"Why it matters: {finding['explanation']}",
        f"Suggested direction: {finding['recommended_action']}",
        f"Affected files: {', '.join(affected) if affected else 'No file was attached by the detector.'}",
        "",
        "Before editing, use the AnaxiMCP tools:",
        f"1. Call ANAXIGRAPH_FINDING_CONTEXT with finding_id={finding_id}.",
        "2. Inspect the recommended files with ANAXIGRAPH_FILE.",
        "3. Call ANAXIGRAPH_IMPACT before changing a shared interface.",
        "4. Make the smallest cohesive change and run the listed relevant tests.",
        "5. Refresh AnaxiGraph and confirm the finding disappears without introducing new errors.",
    ]
    return {
        "repository_id": repository_id,
        "repository_name": repository["name"],
        "finding": finding,
        "ready_for_agent": status == "planned",
        "workflow_note": (
            "This finding is in the human-approved agent queue."
            if status == "planned"
            else "Plan this finding before treating it as approved engineering work."
        ),
        "goal": goal,
        "risk": risk,
        "recommended_context": recommended_context,
        "relevant_tests": sorted(tests),
        "protected_paths": sorted(protected_paths),
        "scope": scope,
        "primary_impact": primary_impact,
        "verification": [
            "Run focused tests for the affected behavior and dependency boundary.",
            "Refresh the repository scan after the code change.",
            "Confirm this stable finding is automatically resolved or explain why it remains.",
            "Review any new error-severity findings introduced by the change.",
        ],
        "agent_prompt": "\n".join(prompt_lines),
    }


def impact_analysis(
    database: AnaxiIndex,
    *,
    repository_id: int,
    target: str,
    branch: str | None,
    config: AnaxiGraphConfig,
) -> dict[str, Any]:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    snapshot = database.latest_snapshot(repository_id)
    if snapshot is None:
        raise ValueError("Repository has not been scanned")
    snapshot_id = int(snapshot["id"])
    with database.connect() as connection:
        files, outgoing, incoming = _graph_maps(connection, snapshot_id)
        target_id = _resolve_target(connection, snapshot_id, files, target)
        if target_id is None:
            raise ValueError(f"Target not found: {target}")
        direct_ids = set(incoming[target_id])
        second_ids = set().union(*(incoming[item] for item in direct_ids)) if direct_ids else set()
        second_ids.discard(target_id)
        transitive = _reverse_reachable(target_id, incoming, limit=500)
        affected = {target_id} | transitive
        tests = _related_tests(
            files,
            outgoing,
            incoming,
            {target_id},
            affected - {target_id},
            target,
            limit=50,
        )
        protected = sorted(
            files[item]["path"] for item in affected if _is_protected(files[item]["path"], config)
        )
        migrations = sorted(
            files[item]["path"] for item in affected if "migration" in files[item]["path"].lower()
        )
    paths = {files[item]["path"] for item in affected}
    conflicts = _branch_conflicts(Path(repository["path"]), paths, branch)
    degree = len(outgoing[target_id]) + len(incoming[target_id])
    risk = (
        "high"
        if protected or conflicts or len(transitive) >= 25 or degree >= 20
        else "medium"
        if direct_ids or migrations
        else "low"
    )
    return {
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "target": _file_summary(files[target_id]),
        "direct_dependants": [
            _file_summary(files[item]) for item in _sorted_ids(files, direct_ids)
        ],
        "second_order_dependants": [
            _file_summary(files[item]) for item in _sorted_ids(files, second_ids - direct_ids)
        ],
        "transitive_dependant_count": len(transitive),
        "outgoing_dependencies": [
            _file_summary(files[item]) for item in _sorted_ids(files, outgoing[target_id])
        ],
        "critical_paths_affected": protected,
        "tests_relevant": sorted(tests),
        "database_migrations_possibly_affected": migrations,
        "active_feature_branches_affected": conflicts,
        "risk": risk,
        "metrics": {
            "direct_dependants": len(direct_ids),
            "second_order_dependants": len(second_ids - direct_ids),
            "transitive_dependants": len(transitive),
            "tests": len(tests),
            "degree": degree,
        },
    }


def branch_collisions(
    database: AnaxiIndex,
    *,
    repository_id: int,
) -> dict[str, Any]:
    repository = database.repository(repository_id)
    if repository is None:
        raise ValueError("Repository not found")
    root = Path(repository["path"])
    branches = git.active_branch_changes(root)
    collisions: list[dict[str, Any]] = []
    names = sorted(branches)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            shared = sorted(branches[left] & branches[right])
            if shared:
                collisions.append(
                    {
                        "branches": [left, right],
                        "shared_files": shared,
                        "risk": "high" if len(shared) >= 3 else "medium",
                    }
                )
    return {
        "repository_id": repository_id,
        "branches": {name: sorted(paths) for name, paths in branches.items()},
        "collisions": collisions,
    }


def _graph_maps(
    connection: sqlite3.Connection, snapshot_id: int
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]], dict[int, set[int]]]:
    files = {
        int(row["artifact_id"]): dict(row)
        for row in connection.execute(
            """
            SELECT fv.*, a.artifact_type FROM file_versions fv
            JOIN artifacts a ON a.id = fv.artifact_id WHERE fv.snapshot_id = ?
            """,
            (snapshot_id,),
        )
    }
    outgoing: dict[int, set[int]] = defaultdict(set)
    incoming: dict[int, set[int]] = defaultdict(set)
    for row in connection.execute(
        """
        SELECT source_artifact_id, target_artifact_id FROM relationships
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


def _rank_files(
    connection: sqlite3.Connection,
    snapshot_id: int,
    files: dict[int, dict[str, Any]],
    goal: str,
) -> list[tuple[float, int]]:
    words = {
        word.lower().replace("-", "_")
        for word in _WORD.findall(_split_camel(goal))
        if word.lower() not in _STOPWORDS and len(word) > 1
    }
    words.update(word[:-1] for word in tuple(words) if word.endswith("s") and len(word) > 4)
    symbols: dict[int, str] = defaultdict(str)
    for row in connection.execute(
        """
        SELECT fv.artifact_id, GROUP_CONCAT(s.name, ' ') AS names
        FROM symbols s JOIN file_versions fv ON fv.id = s.artifact_version_id
        WHERE fv.snapshot_id = ? GROUP BY fv.artifact_id
        """,
        (snapshot_id,),
    ):
        symbols[int(row["artifact_id"])] = row["names"] or ""
    documents: dict[int, tuple[str, str, str, str]] = {}
    for artifact_id, item in files.items():
        path = item["path"].lower().replace("-", "_")
        basename = Path(path).stem
        summary = (item["summary"] or "").lower().replace("-", "_")
        symbol_text = symbols[artifact_id].lower().replace("-", "_")
        documents[artifact_id] = (path, basename, summary, symbol_text)
    document_frequency = {
        word: sum(1 for values in documents.values() if word in " ".join(values)) for word in words
    }
    ranked: list[tuple[float, int]] = []
    for artifact_id, item in files.items():
        path, basename, summary, symbol_text = documents[artifact_id]
        score = 0.0
        for word in words:
            inverse_frequency = 1 + log((len(files) + 1) / (document_frequency[word] + 1))
            score += path.count(word) * 7 * inverse_frequency
            score += basename.count(word) * 8 * inverse_frequency
            score += summary.count(word) * 3 * inverse_frequency
            score += symbol_text.count(word) * 4 * inverse_frequency
        normalized_goal = "_".join(
            word.lower() for word in _WORD.findall(_split_camel(goal)) if len(word) > 2
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
    goal_words = {word.lower() for word in _WORD.findall(goal)}
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
        FROM symbols s JOIN file_versions fv ON fv.id = s.artifact_version_id
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
        "SELECT * FROM architecture_rules WHERE repository_id = ? AND enabled = 1",
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
            item["config"] = config
            result.append(item)
    return result


def _applicable_findings(
    connection: sqlite3.Connection,
    repository_id: int,
    files: dict[int, dict[str, Any]],
    artifact_ids: set[int],
) -> list[dict[str, Any]]:
    paths = {files[item]["path"] for item in artifact_ids}
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
        if affected & paths:
            item["affected_artifacts"] = sorted(affected)
            result.append(item)
    return result[:50]


def _resolve_target(
    connection: sqlite3.Connection,
    snapshot_id: int,
    files: dict[int, dict[str, Any]],
    target: str,
) -> int | None:
    normalized = target.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    exact = [artifact_id for artifact_id, item in files.items() if item["path"] == normalized]
    if len(exact) == 1:
        return exact[0]
    basename = [
        artifact_id for artifact_id, item in files.items() if Path(item["path"]).name == normalized
    ]
    if len(basename) == 1:
        return basename[0]
    symbol_rows = connection.execute(
        """
        SELECT DISTINCT fv.artifact_id FROM symbols s
        JOIN file_versions fv ON fv.id = s.artifact_version_id
        WHERE fv.snapshot_id = ? AND (s.name = ? OR s.qualified_name = ?)
        """,
        (snapshot_id, target, target),
    ).fetchall()
    symbol_ids = {int(row["artifact_id"]) for row in symbol_rows}
    return next(iter(symbol_ids)) if len(symbol_ids) == 1 else None


def _branch_conflicts(root: Path, paths: set[str], branch: str | None) -> list[dict[str, str]]:
    if branch and not re.fullmatch(r"[A-Za-z0-9._/-]{1,250}", branch):
        raise ValueError("Branch contains unsupported characters")
    try:
        branches = git.active_branch_changes(root, exclude=branch)
    except (git.GitError, OSError):
        return []
    result = []
    for name, changed in branches.items():
        for path in sorted(paths & changed):
            result.append({"branch": name, "path": path})
    return result


def _is_protected(path: str, config: AnaxiGraphConfig) -> bool:
    patterns = (*config.architecture.protected_paths, *config.agent.protected_paths)
    return any(path_matches(path, pattern) for pattern in patterns)


def _file_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": item["path"],
        "language": item["language"],
        "summary": item["summary"],
        "lines_of_code": item["lines_of_code"],
        "complexity": item["complexity"],
        "group": item["declared_group"] or item["inferred_group"],
    }


def _sorted_ids(files: dict[int, dict[str, Any]], ids: set[int]) -> list[int]:
    return sorted(ids, key=lambda item: files[item]["path"])


def _split_camel(value: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)


def _json(value: str) -> Any:
    try:
        return __import__("json").loads(value)
    except (ValueError, TypeError):
        return None
