"""Incremental repository scanner and graph builder."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import posixpath
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from codeintel import __version__, git
from codeintel.analyzers import AnalyzerRegistry, builtin_registry
from codeintel.architecture import evaluate_architecture
from codeintel.config import CodeIntelConfig, load_config
from codeintel.coverage import collect_coverage
from codeintel.languages import artifact_type, detect_language
from codeintel.models import Dependency, FileAnalysis, GitMetadata, ScanStats, SemanticClaim, Symbol
from codeintel.semantic import CommandSemanticProvider, SemanticAnalysisError
from codeintel.storage import Database, utc_now

ANALYSIS_VERSION = 2


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: str
    language: str
    raw_hash: str
    content: bytes


@dataclass(slots=True)
class PreparedFile:
    discovered: DiscoveredFile
    analysis: FileAnalysis
    analysis_status: str
    previous_version_id: int | None
    first_seen_at: str
    last_changed_at: str
    semantic_claim: SemanticClaim | None = None
    semantic_error: str | None = None


class RepositoryScanner:
    def __init__(
        self,
        database: Database,
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
    ) -> ScanStats:
        started = time.monotonic()
        root = Path(repository).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Repository does not exist or is not a directory: {root}")
        config = load_config(root, Path(config_path) if config_path else None)
        git_metadata = git.metadata(root, revision=revision)
        name = config.project_name or root.name
        repository_id = self.database.ensure_repository(
            path=root,
            name=name,
            git=git_metadata,
        )
        run_id = self.database.start_run(repository_id, run_type)
        try:
            discovered = self._discover(
                root,
                config,
                revision=revision,
            )
            fingerprint = _content_fingerprint(discovered, config, git_metadata)
            latest = self.database.latest_snapshot(repository_id)
            existing_snapshot = self.database.snapshot_by_fingerprint(repository_id, fingerprint)
            if existing_snapshot:
                existing_id = int(existing_snapshot["id"])
                snapshot_metadata = json.loads(existing_snapshot["metadata_json"] or "{}")
                snapshot_metadata.update(
                    {
                        "codeintel_version": __version__,
                        "analysis_version": ANALYSIS_VERSION,
                        "analysis_signature": analysis_signature(config),
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
                        self._ingest_git_history(
                            connection, repository_id=repository_id, root=root
                        )
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
                        evaluate_architecture(
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
                    metadata={"duration_ms": duration, "revision": revision},
                )
                return ScanStats(
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

            previous_snapshot_id = (
                baseline_snapshot_id
                if baseline_snapshot_id is not None
                else (int(latest["id"]) if latest else None)
            )
            previous = self._previous_versions(previous_snapshot_id)
            prepared = self._prepare(discovered, previous, config)
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
                relationship_count = self._insert_relationships(
                    connection,
                    snapshot_id=snapshot_id,
                    prepared=prepared,
                    artifacts=artifacts,
                    config=config,
                )
                self._insert_groups(
                    connection,
                    repository_id=repository_id,
                    snapshot_id=snapshot_id,
                    prepared=prepared,
                    artifacts=artifacts,
                    config=config,
                )
                self._insert_semantic_claims(
                    connection,
                    prepared=prepared,
                    version_ids=version_ids,
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
                findings = evaluate_architecture(
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

            analyzed = sum(item.analysis_status != "raw_unchanged" for item in prepared)
            reused = len(prepared) - analyzed
            errors = sum(
                bool(item.analysis.parse_error or item.semantic_error) for item in prepared
            )
            duration = int((time.monotonic() - started) * 1_000)
            self.database.finish_run(
                run_id,
                snapshot_id=snapshot_id,
                status="completed_with_errors" if errors else "completed",
                discovered=len(discovered),
                analyzed=analyzed,
                reused=reused,
                error_count=errors,
                metadata={
                    "duration_ms": duration,
                    "revision": revision,
                    "deleted": deleted,
                    "relationships": relationship_count,
                    "coverage_measurements": coverage_count,
                    "findings": len(findings),
                },
            )
            return ScanStats(
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
        except Exception as exc:
            self.database.finish_run(
                run_id,
                snapshot_id=None,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:4_000],
            )
            raise

    def _discover(
        self,
        root: Path,
        config: CodeIntelConfig,
        *,
        revision: str | None,
    ) -> list[DiscoveredFile]:
        if revision is not None:
            paths = git.files_at_revision(root, revision)
        else:
            paths = git.listed_files(root) if git.is_repository(root) else _walk_files(root, config)
        result: list[DiscoveredFile] = []
        for raw_path in paths:
            path = raw_path.replace("\\", "/")
            if path.startswith("./"):
                path = path[2:]
            if not path or config.is_ignored(path):
                continue
            language = detect_language(path)
            if language is None:
                continue
            if revision is not None:
                content = git.read_at_revision(
                    root,
                    revision,
                    path,
                    max_bytes=config.max_file_bytes,
                )
            else:
                candidate = root / path
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                try:
                    if candidate.stat().st_size > config.max_file_bytes:
                        continue
                    content = candidate.read_bytes()
                except OSError:
                    continue
            if content is None or b"\0" in content[:8_192]:
                continue
            result.append(
                DiscoveredFile(
                    path=path,
                    language=language,
                    raw_hash=hashlib.sha256(content).hexdigest(),
                    content=content,
                )
            )
        return sorted(result, key=lambda item: item.path)

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

    def _prepare(
        self,
        discovered: list[DiscoveredFile],
        previous: dict[str, dict[str, Any]],
        config: CodeIntelConfig,
    ) -> list[PreparedFile]:
        now = utc_now()
        semantic_provider = (
            CommandSemanticProvider(config.semantic)
            if config.semantic.enabled and config.semantic.command
            else None
        )
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
                        analysis=_analysis_from_previous(prior),
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
            analysis = analyzer.analyze(item.path, content)
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
            semantic_change = not prior or prior["structural_hash"] != analysis.structural_hash
            if (
                semantic_provider
                and status in {"new", "structural_changed", "analyzer_changed"}
                and semantic_change
            ):
                try:
                    current.semantic_claim = semantic_provider.analyze(
                        path=item.path,
                        content=content,
                        facts=analysis,
                    )
                except SemanticAnalysisError as exc:
                    current.semantic_error = str(exc)
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
        config: CodeIntelConfig,
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
                        "codeintel_version": __version__,
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
        config: CodeIntelConfig,
    ) -> dict[str, int]:
        version_ids: dict[str, int] = {}
        for item in prepared:
            path = item.discovered.path
            analysis = item.analysis
            declared = config.declared_group(path)
            inferred = _inferred_group(path, item.discovered.language)
            metadata = dict(analysis.metadata)
            metadata["analysis_version"] = ANALYSIS_VERSION
            metadata["dependencies"] = [
                dataclasses.asdict(value) for value in analysis.dependencies
            ]
            if item.semantic_error:
                metadata["semantic_error"] = item.semantic_error
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

    def _insert_relationships(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot_id: int,
        prepared: list[PreparedFile],
        artifacts: dict[str, int],
        config: CodeIntelConfig,
    ) -> int:
        resolver = _DependencyResolver(prepared, artifacts, config)
        aggregated: dict[tuple[int, int | None, str | None, str], dict[str, Any]] = {}
        for item in prepared:
            source_path = item.discovered.path
            source_id = artifacts[source_path]
            for dependency in item.analysis.dependencies:
                targets = resolver.resolve(source_path, item.discovered.language, dependency)
                if not targets:
                    targets = [(None, dependency.target)]
                for target_id, target_external in targets:
                    if target_id == source_id and dependency.relationship_type == "imports":
                        continue
                    key = (
                        source_id,
                        target_id,
                        target_external if target_id is None else None,
                        dependency.relationship_type,
                    )
                    current = aggregated.setdefault(
                        key,
                        {
                            "confidence": dependency.confidence,
                            "weight": 0,
                            "evidence": [],
                            "line": dependency.line,
                            "source": _relationship_source(
                                item.discovered.language, dependency.relationship_type
                            ),
                        },
                    )
                    current["weight"] += 1
                    current["confidence"] = max(current["confidence"], dependency.confidence)
                    if dependency.evidence and dependency.evidence not in current["evidence"]:
                        current["evidence"].append(dependency.evidence)
                    current["line"] = min(
                        value for value in (current["line"], dependency.line) if value >= 0
                    )
        for (source_id, target_id, external, relation_type), value in aggregated.items():
            connection.execute(
                """
                INSERT INTO relationships(
                    snapshot_id, source_artifact_id, target_artifact_id, target_external,
                    relationship_type, source, confidence, evidence, source_line, weight
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    source_id,
                    target_id,
                    external,
                    relation_type,
                    value["source"],
                    value["confidence"],
                    " | ".join(value["evidence"][:5])[:2_000],
                    value["line"],
                    value["weight"],
                ),
            )
        return len(aggregated)

    def _insert_groups(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        prepared: list[PreparedFile],
        artifacts: dict[str, int],
        config: CodeIntelConfig,
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

    def _insert_semantic_claims(
        self,
        connection: sqlite3.Connection,
        *,
        prepared: list[PreparedFile],
        version_ids: dict[str, int],
    ) -> None:
        for item in prepared:
            version_id = version_ids[item.discovered.path]
            claim = item.semantic_claim
            if claim is not None:
                values = {
                    "summary": claim.summary,
                    "responsibilities": claim.responsibilities,
                    "inputs": claim.inputs,
                    "outputs": claim.outputs,
                    "side_effects": claim.side_effects,
                    "architectural_group": claim.architectural_group,
                }
                connection.execute(
                    """
                    INSERT INTO semantic_claims(
                        artifact_version_id, claim_type, value_json, source, provider, model,
                        prompt_version, created_at, confidence, supporting_evidence_json
                    ) VALUES (?, 'module_analysis', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        json.dumps(values, sort_keys=True),
                        claim.source,
                        claim.provider,
                        claim.model,
                        claim.prompt_version,
                        utc_now(),
                        claim.confidence,
                        json.dumps(claim.supporting_evidence),
                    ),
                )
            elif item.previous_version_id is not None:
                connection.execute(
                    """
                    INSERT INTO semantic_claims(
                        artifact_version_id, claim_type, value_json, source, provider, model,
                        prompt_version, created_at, confidence, supporting_evidence_json
                    )
                    SELECT ?, claim_type, value_json, source, provider, model, prompt_version,
                           created_at, confidence, supporting_evidence_json
                    FROM semantic_claims WHERE artifact_version_id = ?
                    """,
                    (version_id, item.previous_version_id),
                )

    def _ingest_git_history(
        self, connection: sqlite3.Connection, *, repository_id: int, root: Path
    ) -> None:
        try:
            changes = git.recent_changes(root)
        except git.GitError:
            return
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


class _DependencyResolver:
    def __init__(
        self,
        prepared: list[PreparedFile],
        artifacts: dict[str, int],
        config: CodeIntelConfig,
    ) -> None:
        self.paths = set(artifacts)
        self.artifacts = artifacts
        self.config = config
        self.python_modules: dict[str, set[str]] = {}
        self.symbols: dict[str, set[str]] = defaultdict_set()
        for item in prepared:
            path = item.discovered.path
            if item.discovered.language == "python":
                for alias in _python_module_aliases(path):
                    self.python_modules.setdefault(alias, set()).add(path)
            for symbol in item.analysis.symbols:
                self.symbols.setdefault(symbol.name, set()).add(path)
                self.symbols.setdefault(symbol.qualified_name, set()).add(path)

    def resolve(
        self, source_path: str, language: str, dependency: Dependency
    ) -> list[tuple[int | None, str | None]]:
        if dependency.target.startswith("symbol:"):
            name = dependency.target.removeprefix("symbol:")
            matches = self.symbols.get(name, set())
            if len(matches) == 1:
                path = next(iter(matches))
                return [(self.artifacts[path], None)]
            return []
        if language == "python":
            paths = self._resolve_python(source_path, dependency)
        else:
            paths = self._resolve_path_import(source_path, dependency.target)
        return [(self.artifacts[path], None) for path in paths]

    def _resolve_python(self, source_path: str, dependency: Dependency) -> list[str]:
        target = dependency.target
        candidates: list[str] = []
        if target.startswith("."):
            level = len(target) - len(target.lstrip("."))
            remainder = target[level:]
            full_module = _canonical_python_module(source_path)
            base = full_module.split(".")[:-1]
            if level > 1:
                base = base[: max(0, len(base) - (level - 1))]
            target = ".".join((*base, remainder)).strip(".")
        candidates.append(target)
        candidates.extend(f"{target}.{name}".strip(".") for name in dependency.names)
        matches: list[str] = []
        for candidate in candidates:
            values = self.python_modules.get(candidate, set())
            if len(values) == 1:
                path = next(iter(values))
                if path not in matches:
                    matches.append(path)
        return matches[:10]

    def _resolve_path_import(self, source_path: str, target: str) -> list[str]:
        clean = target.split("?", 1)[0].split("#", 1)[0]
        source_parent = str(PurePosixPath(source_path).parent)
        candidate_base: str | None = None
        if clean.startswith("."):
            candidate_base = posixpath.normpath(posixpath.join(source_parent, clean))
        elif clean.startswith("/"):
            candidate_base = clean.lstrip("/")
        else:
            for alias, replacement in sorted(
                self.config.aliases.items(), key=lambda item: len(item[0]), reverse=True
            ):
                alias_prefix = alias.rstrip("*")
                if clean.startswith(alias_prefix):
                    suffix = clean[len(alias_prefix) :].lstrip("/")
                    candidate_base = posixpath.join(replacement.rstrip("*"), suffix)
                    break
        if candidate_base is None or candidate_base.startswith("../"):
            return []
        extensions = (
            "",
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".css",
            ".scss",
            ".json",
            ".md",
            "/__init__.py",
            "/index.ts",
            "/index.tsx",
            "/index.js",
            "/index.jsx",
        )
        return [
            candidate_base + extension
            for extension in extensions
            if candidate_base + extension in self.paths
        ][:1]


def defaultdict_set() -> dict[str, set[str]]:
    return {}


def _walk_files(root: Path, config: CodeIntelConfig) -> list[str]:
    result: list[str] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(root)
        directories[:] = [
            name
            for name in directories
            if not (current_path / name).is_symlink()
            and not config.is_ignored(str((relative_dir / name)).replace("\\", "/"), is_dir=True)
        ]
        for name in files:
            result.append(str((relative_dir / name)).replace("\\", "/"))
    return result


def _analysis_from_previous(value: dict[str, Any]) -> FileAnalysis:
    metadata = json.loads(value["metadata_json"] or "{}")
    dependencies = [
        Dependency(
            target=item["target"],
            relationship_type=item.get("relationship_type", "imports"),
            line=int(item.get("line", 0)),
            evidence=item.get("evidence", ""),
            confidence=float(item.get("confidence", 1.0)),
            names=tuple(item.get("names") or ()),
        )
        for item in metadata.pop("dependencies", [])
    ]
    symbols = [
        Symbol(
            symbol_type=item["symbol_type"],
            name=item["name"],
            qualified_name=item["qualified_name"],
            start_line=int(item["start_line"]),
            end_line=int(item["end_line"]),
            signature=item["signature"],
            summary=item["summary"],
            complexity=int(item["complexity"]),
            logical_lines=int(item["logical_lines"]),
        )
        for item in value["symbols"]
    ]
    return FileAnalysis(
        language=value["language"],
        structural_hash=value["structural_hash"],
        lines_of_code=int(value["lines_of_code"]),
        comment_lines=int(value["comment_lines"]),
        complexity=int(value["complexity"]),
        summary=value["summary"],
        responsibilities=json.loads(value["responsibilities_json"]),
        inputs=json.loads(value["inputs_json"]),
        outputs=json.loads(value["outputs_json"]),
        side_effects=json.loads(value["side_effects_json"]),
        public_interfaces=json.loads(value["public_interfaces_json"]),
        symbols=symbols,
        dependencies=dependencies,
        parse_error=value["parse_error"],
        analyzer=value["analyzer"],
        metadata=metadata,
    )


def _content_fingerprint(
    files: list[DiscoveredFile], config: CodeIntelConfig, git_metadata: GitMetadata
) -> str:
    digest = hashlib.sha256()
    digest.update(f"codeintel:{__version__}:analysis:{ANALYSIS_VERSION}\0".encode())
    digest.update(git_metadata.commit_sha.encode())
    digest.update(_config_json(config).encode())
    for item in files:
        digest.update(item.path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(item.raw_hash.encode())
    return digest.hexdigest()


def analysis_signature(config: CodeIntelConfig) -> str:
    digest = hashlib.sha256()
    digest.update(f"codeintel:{__version__}:analysis:{ANALYSIS_VERSION}\0".encode())
    digest.update(_config_json(config).encode())
    return digest.hexdigest()


def _config_json(config: CodeIntelConfig) -> str:
    config_value = dataclasses.asdict(config)
    # Mount points differ between local and container runs; only policy content affects analysis.
    config_value.pop("config_path", None)
    return json.dumps(config_value, sort_keys=True, default=str)


def _canonical_python_module(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _python_module_aliases(path: str) -> set[str]:
    canonical = _canonical_python_module(path)
    parts = canonical.split(".")
    aliases = {canonical}
    if len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    if "src" in parts:
        aliases.add(".".join(parts[parts.index("src") + 1 :]))
    for marker in ("app", "lib", "server"):
        if marker in parts:
            aliases.add(".".join(parts[parts.index(marker) :]))
    return {alias for alias in aliases if alias}


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


def _relationship_source(language: str, relationship_type: str) -> str:
    if language == "python":
        return "ast"
    if relationship_type == "references":
        return "configuration"
    return "static"
