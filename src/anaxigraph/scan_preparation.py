"""Prepare discovered source files for snapshot persistence."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anaxigraph import __version__
from anaxigraph.analyzers import AnalyzerRegistry
from anaxigraph.analyzers.base import LanguageAnalyzer
from anaxigraph.architecture_vocabulary import VOCABULARY_VERSION
from anaxigraph.clock import utc_now
from anaxigraph.history_discovery import DiscoveredFile
from anaxigraph.ir import analysis_from_stored, analyze_with_contract


@dataclass(slots=True)
class PreparedFile:
    discovered: DiscoveredFile
    analysis: Any
    analysis_status: str
    previous_version_id: int | None
    first_seen_at: str
    last_changed_at: str


def prepare_files(
    discovered: list[DiscoveredFile],
    previous: dict[str, dict[str, Any]],
    config: Any,
    registry: AnalyzerRegistry,
    *,
    analysis_version: int,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[PreparedFile]:
    """Analyze changed files and reconstruct unchanged analysis from immutable facts."""

    now = utc_now()
    prepared: list[PreparedFile] = []
    total = len(discovered)
    for completed, item in enumerate(discovered, start=1):
        prior = previous.get(item.path)
        analyzer = registry.for_language(item.language)
        if analyzer is None:
            raise RuntimeError(f"No analyzer registered for {item.language}")
        if _can_reuse(prior, item, analysis_version, analyzer):
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
            _report_progress(progress, completed, total, item.path)
            continue
        analysis = analyze_with_contract(
            analyzer,
            item.path,
            item.content.decode("utf-8", errors="replace"),
        )
        prepared.append(
            PreparedFile(
                discovered=item,
                analysis=analysis,
                analysis_status=_analysis_status(prior, item, analysis),
                previous_version_id=int(prior["id"]) if prior else None,
                first_seen_at=prior["first_seen_at"] if prior else now,
                last_changed_at=now,
            )
        )
        _report_progress(progress, completed, total, item.path)
    return prepared


def _report_progress(
    progress: Callable[[int, int, str], None] | None,
    completed: int,
    total: int,
    path: str,
) -> None:
    if progress is not None:
        progress(completed, total, path)


def analysis_counts(prepared: list[PreparedFile]) -> tuple[int, int, int]:
    analyzed = sum(item.analysis_status != "raw_unchanged" for item in prepared)
    return (
        analyzed,
        len(prepared) - analyzed,
        sum(bool(item.analysis.parse_error) for item in prepared),
    )


def invalidation_counts(prepared: list[PreparedFile]) -> dict[str, int]:
    return dict(sorted(Counter(item.discovered.invalidation_reason for item in prepared).items()))


def _analysis_status(
    prior: dict[str, Any] | None,
    item: DiscoveredFile,
    analysis: Any,
) -> str:
    if prior is None:
        return "new"
    if prior["raw_hash"] == item.raw_hash:
        return "analyzer_changed"
    if prior["structural_hash"] == analysis.structural_hash:
        return "metadata_only"
    return "structural_changed"


def content_fingerprint(
    files: list[DiscoveredFile],
    config: Any,
    git_metadata: Any,
    *,
    analysis_version: int,
    registry: AnalyzerRegistry,
) -> str:
    value = hashlib.sha256()
    value.update(_version_prefix(analysis_version))
    value.update(git_metadata.commit_sha.encode())
    value.update(_config_json(config).encode())
    for item in files:
        value.update(item.path.encode("utf-8", errors="surrogateescape"))
        value.update(b"\0")
        value.update(item.raw_hash.encode())
        value.update(b"\0")
        analyzer = registry.for_language(item.language)
        if analyzer is None:
            raise RuntimeError(f"No analyzer registered for {item.language}")
        value.update(_analyzer_contract(analyzer).encode())
    return value.hexdigest()


def structural_analysis_signature(config: Any, *, analysis_version: int) -> str:
    value = hashlib.sha256()
    value.update(_version_prefix(analysis_version))
    value.update(_structural_config_json(config).encode())
    return value.hexdigest()


def analysis_signature(config: Any, *, analysis_version: int) -> str:
    """Compatibility name for the explicitly structural signature."""

    return structural_analysis_signature(config, analysis_version=analysis_version)


def _can_reuse(
    prior: dict[str, Any] | None,
    item: DiscoveredFile,
    analysis_version: int,
    analyzer: LanguageAnalyzer,
) -> bool:
    metadata = json.loads(prior["metadata_json"] or "{}") if prior else {}
    ir = metadata.get("ir") or {}
    capabilities = ir.get("analyzer_capabilities") or {}
    return bool(
        prior
        and prior["raw_hash"] == item.raw_hash
        and metadata.get("analysis_version") == analysis_version
        and prior.get("analyzer") == analyzer.name
        and str(ir.get("analyzer_version") or "legacy") == analyzer.version
        and capabilities.get("schema_version") == analyzer.capabilities.schema_version
        and capabilities.get("fingerprint") == analyzer.capabilities.fingerprint
    )


def _analyzer_contract(analyzer: LanguageAnalyzer) -> str:
    return ":".join((analyzer.name, analyzer.version, analyzer.capabilities.fingerprint))


def _version_prefix(analysis_version: int) -> bytes:
    return f"anaxigraph:{__version__}:analysis:{analysis_version}\0".encode()


def _config_json(config: Any) -> str:
    return _structural_config_json(config)


def structural_config_projection(config: Any) -> dict[str, Any]:
    """Return only policy capable of changing deterministic repository facts."""

    return {
        "discovery": {
            "ignore": list(config.ignore),
            "include": list(config.include),
            "max_file_bytes": config.max_file_bytes,
        },
        "resolution": {"aliases": dict(config.aliases)},
        "placement": {"groups": [dataclasses.asdict(group) for group in config.groups]},
        "architecture_vocabulary": VOCABULARY_VERSION,
    }


def _structural_config_json(config: Any) -> str:
    return json.dumps(structural_config_projection(config), sort_keys=True, default=str)
