"""Incremental repository scanner and graph builder."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from anaxigraph import __version__
from anaxigraph.analyzers import AnalyzerRegistry, builtin_registry
from anaxigraph.config import AnaxiGraphConfig, load_config
from anaxigraph.coverage import collect_coverage
from anaxigraph.history_discovery import (
    DiscoveredFile,
    DiscoveryResult,
    apply_invalidation_plan,
    available_changes,
    discover_files,
    repository_metadata,
)
from anaxigraph.ir import (
    analysis_from_stored,
    analysis_metadata,
    analyze_with_contract,
    artifact_type,
)
from anaxigraph.models import (
    FileAnalysis,
    GitMetadata,
    ScanStats,
)
from anaxigraph.scan_snapshot import (
    RelationshipBuildResult,
    build_snapshot_graph,
    evaluate_snapshot_architecture,
)
from anaxigraph.storage import AnaxiIndex, utc_now
from anaxigraph.understanding import SemanticEngine

ANALYSIS_VERSION = 4


@dataclass(slots=True)
class PreparedFile:
    discovered: DiscoveredFile
    analysis: FileAnalysis
    analysis_status: str
    previous_version_id: int | None
    first_seen_at: str
    last_changed_at: str


class RepositoryScanner:
    def __init__(
        self,
        database: AnaxiIndex,
        *,
        registry: AnalyzerRegistry | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or builtin_registry()

    def scan(
        self,
        repository: str | Path,
        *,
        config_path: str | Path | None = None,
        revision: str | None = None,
        run_type: str = "scan",
        baseline_snapshot_id: int | None = None,
        previous_revision: str | None = None,
    ) -> ScanStats:
        started = time.monotonic()
        root = Path(repository).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Repository does not exist or is not a directory: {root}")
        config = load_config(root, Path(config_path) if config_path else None)
        git_metadata = repository_metadata(root, revision)
        repository_id = self.database.ensure_repository(
            path=root,
            name=config.project_name or root.name,
            git=git_metadata,
        )
        run_id = self.database.start_run(repository_id, run_type)
        try:
            signature = analysis_signature(config)
            discovered, previous, discovery = self._discover_frame(
                repository_id,
                root,
                config,
                revision=revision,
                baseline_snapshot_id=baseline_snapshot_id,
                previous_revision=previous_revision,
                signature=signature,
            )
            fingerprint = _content_fingerprint(discovered, config, git_metadata)
            existing_snapshot = self.database.snapshot_by_fingerprint(repository_id, fingerprint)
            if existing_snapshot:
                existing_id = int(existing_snapshot["id"])
                snapshot_metadata = json.loads(existing_snapshot["metadata_json"] or "{}")
                snapshot_metadata.update(
                    {
                        "anaxigraph_version": __version__,
                        "analysis_version": ANALYSIS_VERSION,
                        "analysis_signature": signature,
                        "config_path": str(config.config_path) if config.config_path else None,
                    }
                )
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE snapshots SET metadata_json = ? WHERE id = ?",
                        (json.dumps(snapshot_metadata, sort_keys=True), existing_id),
                    )
                if revision is None:
                    self.database.set_current_snapshot(repository_id, existing_id)
                    with self.database.transaction() as connection:
                        self._ingest_git_history(connection, repository_id=repository_id, root=root)
                        connection.execute(
                            "DELETE FROM metrics WHERE snapshot_id = ?", (existing_id,)
                        )
                        connection.execute(
                            "DELETE FROM coverage_measurements WHERE snapshot_id = ?",
                            (existing_id,),
                        )
                        artifacts = {
                            row["path"]: int(row["artifact_id"])
                            for row in connection.execute(
                                """
                                SELECT path, artifact_id FROM file_versions
                                WHERE snapshot_id = ?
                                """,
                                (existing_id,),
                            )
                        }
                        collect_coverage(
                            connection,
                            root=root,
                            config=config,
                            snapshot_id=existing_id,
                            artifacts_by_path=artifacts,
                        )
                        evaluate_snapshot_architecture(
                            connection,
                            repository_id=repository_id,
                            snapshot_id=existing_id,
                            config=config,
                            manage_finding_lifecycle=True,
                        )
                        connection.execute(
                            """
                            UPDATE snapshots SET snapshot_kind = 'working_tree', dirty = ?,
                                branch = ?, analysis_timestamp = ? WHERE id = ?
                            """,
                            (
                                int(git_metadata.dirty),
                                git_metadata.branch,
                                utc_now(),
                                existing_id,
                            ),
                        )
                counts = self._snapshot_counts(existing_id)
                duration = int((time.monotonic() - started) * 1_000)
                self.database.finish_run(
                    run_id,
                    snapshot_id=existing_id,
                    status="unchanged",
                    discovered=len(discovered),
                    reused=len(discovered),
                    metadata=_run_metadata(discovery, duration, revision),
                )
                stats = ScanStats(
                    repository_id=repository_id,
                    snapshot_id=existing_id,
                    analysis_run_id=run_id,
                    discovered=len(discovered),
                    analyzed=0,
                    reused=len(discovered),
                    deleted=0,
                    relationships=counts["relationships"],
                    findings=counts["findings"],
                    duration_ms=duration,
                )
                if revision is None and config.semantic.enabled:
                    SemanticEngine(self.database).plan(repository_id, root, config)
                return stats

            prepared = self._prepare(discovered, previous, config)
            apply_invalidation_plan(prepared, previous)
            with self.database.transaction() as connection:
                snapshot_id = self._insert_snapshot(
                    connection,
                    repository_id=repository_id,
                    git_metadata=git_metadata,
                    fingerprint=fingerprint,
                    revision=revision,
                    config=config,
                )
                artifacts, deleted = self._upsert_artifacts(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    prepared=prepared,
                    commit_sha=git_metadata.commit_sha,
                )
                version_ids = self._insert_versions(
                    connection,
                    snapshot_id=snapshot_id,
                    prepared=prepared,
                    artifacts=artifacts,
                    config=config,
                )
                relationship_build = build_snapshot_graph(
                    connection,
                    snapshot_id=snapshot_id,
                    prepared=prepared,
                    artifacts=artifacts,
                    version_ids=version_ids,
                    config=config,
                )
                relationship_count = relationship_build.total
                self._insert_groups(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    prepared=prepared,
                    artifacts=artifacts,
                    config=config,
                )
                self._ingest_git_history(connection, repository_id=repository_id, root=root)
                coverage_count = 0
                if revision is None:
                    coverage_count = collect_coverage(
                        connection,
                        root=root,
                        config=config,
                        snapshot_id=snapshot_id,
                        artifacts_by_path=artifacts,
                    )
                findings = evaluate_snapshot_architecture(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    config=config,
                    manage_finding_lifecycle=revision is None,
                )
                if revision is None:
                    connection.execute(
                        "UPDATE repositories SET current_snapshot_id = ?, updated_at = ? WHERE id = ?",
                        (snapshot_id, utc_now(), repository_id),
                    )

            analyzed, reused, errors = _analysis_counts(prepared)
            duration = int((time.monotonic() - started) * 1_000)
            self.database.finish_run(
                run_id,
                snapshot_id=snapshot_id,
                status="completed_with_errors" if errors else "completed",
                discovered=len(discovered),
                analyzed=analyzed,
                reused=reused,
                error_count=errors,
                metadata=_run_metadata(
                    discovery,
                    duration,
                    revision,
                    deleted=deleted,
                    **_relationship_metadata(relationship_build),
                    coverage_measurements=coverage_count,
                    findings=len(findings),
                    invalidation_reasons=_invalidation_counts(prepared),
                ),
            )
            stats = ScanStats(
                repository_id=repository_id,
                snapshot_id=snapshot_id,
                analysis_run_id=run_id,
                discovered=len(discovered),
                analyzed=analyzed,
                reused=reused,
                deleted=deleted,
                relationships=relationship_count,
                findings=len(findings),
                duration_ms=duration,
            )
            if revision is None and config.semantic.enabled:
                SemanticEngine(self.database).plan(repository_id, root, config)
            return stats
        except Exception as exc:
            self.database.finish_run(
                run_id,
                snapshot_id=None,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:4_000],
            )
            raise

    def _discover_frame(
        self,
        repository_id: int,
        root: Path,
        config: AnaxiGraphConfig,
        *,
        revision: str | None,
        baseline_snapshot_id: int | None,
        previous_revision: str | None,
        signature: str,
    ) -> tuple[list[DiscoveredFile], dict[str, dict[str, Any]], DiscoveryResult]:
        latest = self.database.latest_snapshot(repository_id)
        previous_snapshot_id = (
            baseline_snapshot_id
            if baseline_snapshot_id is not None or revision is not None
            else (int(latest["id"]) if latest else None)
        )
        previous = self._previous_versions(previous_snapshot_id)
        discovery = discover_files(
            root,
            config,
            revision=revision,
            previous_revision=previous_revision,
            previous=previous,
            analysis_version=ANALYSIS_VERSION,
            allow_carry=self._snapshot_signature(previous_snapshot_id) == signature,
        )
        return list(discovery.files), previous, discovery

    def _previous_versions(self, snapshot_id: int | None) -> dict[str, dict[str, Any]]:
        if snapshot_id is None:
            return {}
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT fv.* FROM file_versions fv WHERE fv.snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchall()
            result = {row["path"]: dict(row) for row in rows}
            for value in result.values():
                value["symbols"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM symbols WHERE artifact_version_id = ? ORDER BY start_line",
                        (value["id"],),
                    ).fetchall()
                ]
            return result

    def _snapshot_signature(self, snapshot_id: int | None) -> str | None:
        if snapshot_id is None:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        metadata = json.loads(row["metadata_json"] or "{}") if row else {}
        return metadata.get("analysis_signature")

    def _prepare(
        self,
        discovered: list[DiscoveredFile],
        previous: dict[str, dict[str, Any]],
        config: AnaxiGraphConfig,
    ) -> list[PreparedFile]:
        now = utc_now()
        prepared: list[PreparedFile] = []
        for item in discovered:
            prior = previous.get(item.path)
            prior_metadata = json.loads(prior["metadata_json"] or "{}") if prior else {}
            can_reuse = (
                prior
                and prior["raw_hash"] == item.raw_hash
                and prior_metadata.get("analysis_version") == ANALYSIS_VERSION
            )
            if can_reuse:
                prepared.append(
                    PreparedFile(
                        discovered=item,
                        analysis=analysis_from_stored(prior),
                        analysis_status="raw_unchanged",
                        previous_version_id=int(prior["id"]),
                        first_seen_at=prior["first_seen_at"],
                        last_changed_at=prior["last_changed_at"],
                    )
                )
                continue
            content = item.content.decode("utf-8", errors="replace")
            analyzer = self.registry.for_language(item.language)
            if analyzer is None:
                raise RuntimeError(f"No analyzer registered for {item.language}")
            analysis = analyze_with_contract(analyzer, item.path, content)
            status = "new"
            if prior:
                if prior["raw_hash"] == item.raw_hash:
                    status = "analyzer_changed"
                else:
                    status = (
                        "metadata_only"
                        if prior["structural_hash"] == analysis.structural_hash
                        else "structural_changed"
                    )
            current = PreparedFile(
                discovered=item,
                analysis=analysis,
                analysis_status=status,
                previous_version_id=int(prior["id"]) if prior else None,
                first_seen_at=prior["first_seen_at"] if prior else now,
                last_changed_at=now,
            )
            prepared.append(current)
        return prepared

    def _insert_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        git_metadata: GitMetadata,
        fingerprint: str,
        revision: str | None,
        config: AnaxiGraphConfig,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO snapshots(
                repository_id, commit_sha, parent_commit_sha, branch, commit_timestamp,
                analysis_timestamp, content_fingerprint, snapshot_kind, dirty, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repository_id,
                git_metadata.commit_sha,
                git_metadata.parent_commit_sha,
                git_metadata.branch,
                git_metadata.commit_timestamp,
                utc_now(),
                fingerprint,
                "commit" if revision else "working_tree",
                int(git_metadata.dirty),
                json.dumps(
                    {
                        "anaxigraph_version": __version__,
                        "analysis_version": ANALYSIS_VERSION,
                        "analysis_signature": analysis_signature(config),
                        "config_path": str(config.config_path) if config.config_path else None,
                    },
                    sort_keys=True,
                ),
            ),
        )
        return int(cursor.lastrowid)

    def _upsert_artifacts(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        prepared: list[PreparedFile],
        commit_sha: str,
    ) -> tuple[dict[str, int], int]:
        rows = connection.execute(
            "SELECT id, canonical_path, deleted_commit FROM artifacts WHERE repository_id = ?",
            (repository_id,),
        ).fetchall()
        existing = {row["canonical_path"]: int(row["id"]) for row in rows}
        active_paths = {
            row["canonical_path"]
            for row in connection.execute(
                "SELECT canonical_path FROM artifacts WHERE repository_id = ? AND deleted_commit IS NULL",
                (repository_id,),
            )
        }
        current_paths = {item.discovered.path for item in prepared}
        now = utc_now()
        for item in prepared:
            path = item.discovered.path
            if path not in existing:
                cursor = connection.execute(
                    """
                    INSERT INTO artifacts(
                        repository_id, canonical_path, artifact_type, first_seen_commit, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        repository_id,
                        path,
                        artifact_type(path, item.discovered.language),
                        commit_sha,
                        now,
                    ),
                )
                existing[path] = int(cursor.lastrowid)
            else:
                connection.execute(
                    "UPDATE artifacts SET deleted_commit = NULL, artifact_type = ? WHERE id = ?",
                    (artifact_type(path, item.discovered.language), existing[path]),
                )
        deleted_paths = active_paths - current_paths
        if deleted_paths:
            connection.executemany(
                "UPDATE artifacts SET deleted_commit = ? WHERE id = ?",
                [(commit_sha, existing[path]) for path in deleted_paths],
            )
        return {path: existing[path] for path in current_paths}, len(deleted_paths)

    def _insert_versions(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot_id: int,
        prepared: list[PreparedFile],
        artifacts: dict[str, int],
        config: AnaxiGraphConfig,
    ) -> dict[str, int]:
        version_ids: dict[str, int] = {}
        for item in prepared:
            path = item.discovered.path
            analysis = item.analysis
            declared = config.declared_group(path)
            inferred = _inferred_group(path, item.discovered.language)
            metadata = _version_metadata(item, config)
            cursor = connection.execute(
                """
                INSERT INTO file_versions(
                    artifact_id, snapshot_id, path, language, runtime, declared_group,
                    inferred_group, raw_hash, structural_hash, lines_of_code, comment_lines,
                    complexity, summary, responsibilities_json, inputs_json, outputs_json,
                    side_effects_json, public_interfaces_json, analyzer, analysis_status,
                    parse_error, metadata_json, first_seen_at, last_changed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifacts[path],
                    snapshot_id,
                    path,
                    item.discovered.language,
                    _runtime(path, item.discovered.language),
                    declared,
                    inferred,
                    item.discovered.raw_hash,
                    analysis.structural_hash,
                    analysis.lines_of_code,
                    analysis.comment_lines,
                    analysis.complexity,
                    analysis.summary,
                    json.dumps(analysis.responsibilities),
                    json.dumps(analysis.inputs),
                    json.dumps(analysis.outputs),
                    json.dumps(analysis.side_effects),
                    json.dumps(analysis.public_interfaces),
                    analysis.analyzer,
                    item.analysis_status,
                    analysis.parse_error,
                    json.dumps(metadata, sort_keys=True),
                    item.first_seen_at,
                    item.last_changed_at,
                ),
            )
            version_id = int(cursor.lastrowid)
            version_ids[path] = version_id
            for symbol in analysis.symbols:
                connection.execute(
                    """
                    INSERT INTO symbols(
                        artifact_version_id, symbol_type, name, qualified_name, start_line,
                        end_line, signature, summary, complexity, logical_lines
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        symbol.symbol_type,
                        symbol.name,
                        symbol.qualified_name,
                        symbol.start_line,
                        symbol.end_line,
                        symbol.signature,
                        symbol.summary,
                        symbol.complexity,
                        symbol.logical_lines,
                    ),
                )
        return version_ids

    def _insert_groups(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        prepared: list[PreparedFile],
        artifacts: dict[str, int],
        config: AnaxiGraphConfig,
    ) -> None:
        group_ids: dict[tuple[str, str], int] = {}
        for group in config.groups:
            connection.execute(
                """
                INSERT INTO groups(repository_id, name, level, parent_name, source, description)
                VALUES (?, ?, ?, ?, 'declared', ?)
                ON CONFLICT(repository_id, name, source) DO UPDATE SET
                    level = excluded.level, parent_name = excluded.parent_name,
                    description = excluded.description
                """,
                (repository_id, group.name, group.level, group.parent, group.description),
            )
        for item in prepared:
            path = item.discovered.path
            memberships = []
            declared = config.declared_group(path)
            if declared:
                memberships.append((declared, "declared", 1.0, "Matched configured path glob"))
            inferred = _inferred_group(path, item.discovered.language)
            memberships.append((inferred, "inferred", 0.7, "Inferred from repository path/runtime"))
            for name, source, confidence, evidence in memberships:
                key = (name, source)
                if key not in group_ids:
                    connection.execute(
                        """
                        INSERT INTO groups(repository_id, name, level, source)
                        VALUES (?, ?, 'subsystem', ?)
                        ON CONFLICT(repository_id, name, source) DO NOTHING
                        """,
                        (repository_id, name, source),
                    )
                    row = connection.execute(
                        "SELECT id FROM groups WHERE repository_id = ? AND name = ? AND source = ?",
                        (repository_id, name, source),
                    ).fetchone()
                    assert row is not None
                    group_ids[key] = int(row["id"])
                connection.execute(
                    """
                    INSERT INTO group_memberships(
                        snapshot_id, artifact_id, group_id, confidence, evidence
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (snapshot_id, artifacts[path], group_ids[key], confidence, evidence),
                )

    def _ingest_git_history(
        self, connection: sqlite3.Connection, *, repository_id: int, root: Path
    ) -> None:
        changes = available_changes(root)
        connection.executemany(
            """
            INSERT OR IGNORE INTO git_changes(
                repository_id, commit_sha, committed_at, author_name, subject, path,
                change_type, additions, deletions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    repository_id,
                    item.commit_sha,
                    item.committed_at,
                    item.author_name,
                    item.subject,
                    item.path,
                    item.change_type,
                    item.additions,
                    item.deletions,
                )
                for item in changes
            ],
        )

    def _snapshot_counts(self, snapshot_id: int) -> dict[str, int]:
        with self.database.connect() as connection:
            relationships = connection.execute(
                "SELECT COUNT(*) AS count FROM relationships WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()["count"]
            findings = connection.execute(
                "SELECT COUNT(*) AS count FROM findings WHERE last_snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()["count"]
        return {"relationships": int(relationships), "findings": int(findings)}


def _version_metadata(item: PreparedFile, config: AnaxiGraphConfig) -> dict[str, Any]:
    metadata = analysis_metadata(
        item.analysis,
        analysis_version=ANALYSIS_VERSION,
        configured_aliases=config.aliases,
    )
    metadata.update(
        {
            "invalidation_reason": item.discovered.invalidation_reason,
            "history_change_kind": item.discovered.change_kind,
            "source_read": item.discovered.source_read,
        }
    )
    return metadata


def _analysis_counts(prepared: list[PreparedFile]) -> tuple[int, int, int]:
    analyzed = sum(item.analysis_status != "raw_unchanged" for item in prepared)
    return (
        analyzed,
        len(prepared) - analyzed,
        sum(bool(item.analysis.parse_error) for item in prepared),
    )


def _invalidation_counts(prepared: list[PreparedFile]) -> dict[str, int]:
    return dict(sorted(Counter(item.discovered.invalidation_reason for item in prepared).items()))


def _relationship_metadata(result: RelationshipBuildResult) -> dict[str, int]:
    return {
        "relationships": result.total,
        "relationships_copied": result.copied,
        "relationship_sources_resolved": result.resolved_sources,
        "relationship_sources_reused": result.reused_sources,
    }


def _run_metadata(
    discovery: DiscoveryResult,
    duration: int,
    revision: str | None,
    **values: Any,
) -> dict[str, Any]:
    return {
        "duration_ms": duration,
        "revision": revision,
        "source_reads": discovery.source_reads,
        "carried_forward": discovery.carried_forward,
        **values,
    }


def _content_fingerprint(
    files: list[DiscoveredFile], config: AnaxiGraphConfig, git_metadata: GitMetadata
) -> str:
    digest = hashlib.sha256()
    digest.update(f"anaxigraph:{__version__}:analysis:{ANALYSIS_VERSION}\0".encode())
    digest.update(git_metadata.commit_sha.encode())
    digest.update(_config_json(config).encode())
    for item in files:
        digest.update(item.path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(item.raw_hash.encode())
    return digest.hexdigest()


def analysis_signature(config: AnaxiGraphConfig) -> str:
    digest = hashlib.sha256()
    digest.update(f"anaxigraph:{__version__}:analysis:{ANALYSIS_VERSION}\0".encode())
    digest.update(_config_json(config).encode())
    return digest.hexdigest()


def _config_json(config: AnaxiGraphConfig) -> str:
    config_value = dataclasses.asdict(config)
    # Mount points differ between local and container runs; only policy content affects analysis.
    config_value.pop("config_path", None)
    return json.dumps(config_value, sort_keys=True, default=str)


def _inferred_group(path: str, language: str) -> str:
    parts = PurePosixPath(path).parts
    lowered = [part.lower() for part in parts]
    if artifact_type(path, language) == "test":
        return "testing"
    for name in (
        "frontend",
        "backend",
        "agent-runner",
        "runner-launcher",
        "native-worker",
        "git-worker",
        "infra",
        "docs",
        "scripts",
    ):
        if name in lowered:
            return name
    if lowered and lowered[0] == "src" and len(lowered) > 1:
        return lowered[1]
    return lowered[0] if lowered else "root"


def _runtime(path: str, language: str) -> str:
    lowered = path.lower()
    if lowered.startswith("frontend/") or language in {"javascriptreact", "typescriptreact"}:
        return "browser"
    if "worker" in lowered:
        return "worker"
    if language == "python":
        return "python"
    if language in {"javascript", "typescript"}:
        return "node"
    if language in {"dockerfile", "terraform", "hcl", "yaml"}:
        return "deployment"
    return "static"
