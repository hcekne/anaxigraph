"""Bounded agent task context, impact traversal, and branch collision analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.agent_graph import (
    _applicable_findings,
    _applicable_rules,
    _expand_relevant,
    _interfaces,
    _projected_graph_maps,
    _rank_files,
    _related_tests,
    _reverse_reachable,
    _select_primary,
)
from anaxigraph.agent_payload import (
    _bound_scope_payload,
    _branch_conflicts,
    _file_summary,
    _is_protected,
    _sorted_ids,
)
from anaxigraph.config import AnaxiGraphConfig
from anaxigraph.persistence.snapshot_projection import resolve_projected_target
from anaxigraph.storage import AnaxiIndex


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
        files, outgoing, incoming = _projected_graph_maps(connection, snapshot_id)
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
        findings = _applicable_findings(
            connection,
            repository_id,
            files,
            relevant_ids,
            set(primary_ids),
        )
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
    payload = {
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
    return _bound_scope_payload(payload, config.agent.payload_limit_bytes)


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
        files, outgoing, incoming = _projected_graph_maps(connection, snapshot_id)
        target_id = resolve_projected_target(connection, snapshot_id, files, target)
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
