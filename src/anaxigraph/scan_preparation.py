"""Prepare discovered source files for snapshot persistence."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from anaxigraph import __version__
from anaxigraph.analyzers import AnalyzerRegistry
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
) -> list[PreparedFile]:
    """Analyze changed files and reconstruct unchanged analysis from immutable facts."""

    now = utc_now()
    prepared: list[PreparedFile] = []
    for item in discovered:
        prior = previous.get(item.path)
        if _can_reuse(prior, item, analysis_version):
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
        analyzer = registry.for_language(item.language)
        if analyzer is None:
            raise RuntimeError(f"No analyzer registered for {item.language}")
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
    return prepared


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
) -> str:
    value = hashlib.sha256()
    value.update(_version_prefix(analysis_version))
    value.update(git_metadata.commit_sha.encode())
    value.update(_config_json(config).encode())
    for item in files:
        value.update(item.path.encode("utf-8", errors="surrogateescape"))
        value.update(b"\0")
        value.update(item.raw_hash.encode())
    return value.hexdigest()


def analysis_signature(config: Any, *, analysis_version: int) -> str:
    value = hashlib.sha256()
    value.update(_version_prefix(analysis_version))
    value.update(_config_json(config).encode())
    return value.hexdigest()


def _can_reuse(
    prior: dict[str, Any] | None,
    item: DiscoveredFile,
    analysis_version: int,
) -> bool:
    metadata = json.loads(prior["metadata_json"] or "{}") if prior else {}
    return bool(
        prior
        and prior["raw_hash"] == item.raw_hash
        and metadata.get("analysis_version") == analysis_version
    )


def _version_prefix(analysis_version: int) -> bytes:
    return f"anaxigraph:{__version__}:analysis:{analysis_version}\0".encode()


def _config_json(config: Any) -> str:
    config_value = dataclasses.asdict(config)
    # Mount points differ between local and container runs; only policy content affects analysis.
    config_value.pop("config_path", None)
    return json.dumps(config_value, sort_keys=True, default=str)
