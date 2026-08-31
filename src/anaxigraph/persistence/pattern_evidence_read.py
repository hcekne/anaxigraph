"""Read one reusable, pattern-neutral evidence projection for a snapshot."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from typing import Any

from anaxigraph.architecture_vocabulary import CURRENT_MAP, RESPONSIBILITY_MAP
from anaxigraph.pattern_evidence import (
    PATTERN_EVIDENCE_VERSION,
    PatternEvidenceProjection,
    TargetEvidence,
)
from anaxigraph.pattern_targets import (
    PATTERN_TARGET_LEVELS,
    PatternTarget,
    area_target,
    module_target,
    repository_target,
    subsystem_target,
)
from anaxigraph.persistence.module_read import read_modules
from anaxigraph.persistence.pattern_evidence_aggregate import aggregate_evidence
from anaxigraph.persistence.pattern_evidence_features import (
    module_evidence,
    symbol_evidence,
)
from anaxigraph.persistence.pattern_evidence_inputs import (
    capability_contracts,
    facts_by_artifact,
    semantic_documents,
)
from anaxigraph.persistence.snapshot_projection import install_snapshot_projection


def read_pattern_evidence(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    *,
    target: str = "",
) -> PatternEvidenceProjection:
    if target:
        leaf_projection = _leaf_projection(connection, repository_id, snapshot_id, target)
        if leaf_projection is not None:
            return leaf_projection
    repository_name = _repository_name(connection, repository_id, snapshot_id)
    modules, raw, symbols, semantic = _snapshot_inputs(connection, repository_id, snapshot_id)
    contracts = capability_contracts(raw.values())
    facts = facts_by_artifact(raw.values())
    areas, subsystems, module_targets = _architecture_targets(modules)
    module_items, symbol_items = _leaf_items(
        modules, raw, symbols, semantic, facts, module_targets, snapshot_id
    )
    subsystem_items, area_items, repository_item = _parent_items(
        repository_name,
        modules,
        module_targets,
        module_items,
        subsystems,
        areas,
        snapshot_id,
        contracts,
    )
    items = tuple(
        sorted(
            (
                *symbol_items,
                *module_items.values(),
                *subsystem_items.values(),
                *area_items.values(),
                repository_item,
            ),
            key=lambda item: (PATTERN_TARGET_LEVELS.index(item.target.level), item.target.key),
        )
    )
    return _projection(repository_id, snapshot_id, contracts, items)


def _leaf_projection(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
    target: str,
) -> PatternEvidenceProjection | None:
    install_snapshot_projection(connection, snapshot_id)
    path = _leaf_target_path(connection, snapshot_id, target)
    if path is None:
        return None
    offset = int(
        connection.execute(
            "SELECT COUNT(*) FROM projected_file_versions WHERE path < ?", (path,)
        ).fetchone()[0]
    )
    modules = read_modules(
        connection,
        repository_id,
        snapshot_id,
        limit=1,
        offset=offset,
        _projection_installed=True,
    )
    if not modules or str(modules[0]["path"]) != path:
        return None
    raw = {
        int(row["artifact_id"]): dict(row)
        for row in connection.execute(
            "SELECT * FROM projected_file_versions WHERE path = ?", (path,)
        ).fetchall()
    }
    symbols = [dict(row) for row in connection.execute(_SYMBOL_FOR_PATH_SQL, (path,)).fetchall()]
    semantic = semantic_documents(connection, snapshot_id, scope_key=path)
    contracts = capability_contracts(raw.values())
    facts = facts_by_artifact(raw.values())
    _areas, _subsystems, targets = _architecture_targets(modules)
    module_items, symbol_items = _leaf_items(
        modules, raw, symbols, semantic, facts, targets, snapshot_id
    )
    items = tuple(
        sorted(
            (*symbol_items, *module_items.values()),
            key=lambda item: (PATTERN_TARGET_LEVELS.index(item.target.level), item.target.key),
        )
    )
    return _projection(repository_id, snapshot_id, contracts, items)


def _leaf_target_path(
    connection: sqlite3.Connection,
    snapshot_id: int,
    target: str,
) -> str | None:
    candidate = target
    for prefix in ("module:", "type:", "symbol:"):
        if target.startswith(prefix):
            candidate = target.removeprefix(prefix).split("#", 1)[0]
            break
    row = connection.execute(
        "SELECT path FROM projected_file_versions WHERE path = ?", (candidate,)
    ).fetchone()
    if row is not None:
        return str(row["path"])
    rows = connection.execute(
        """
        SELECT DISTINCT fv.path FROM projected_symbols s
        JOIN projected_file_versions fv ON fv.id = s.artifact_version_id
        WHERE s.qualified_name = ?
        """,
        (target,),
    ).fetchall()
    return str(rows[0]["path"]) if len(rows) == 1 else None


def _projection(
    repository_id: int,
    snapshot_id: int,
    contracts: dict[str, dict[str, Any]],
    items: tuple[TargetEvidence, ...],
) -> PatternEvidenceProjection:
    fingerprint = _digest(
        {
            "version": PATTERN_EVIDENCE_VERSION,
            "contracts": contracts,
            "items": [(item.target.key, item.input_fingerprint) for item in items],
        }
    )
    return PatternEvidenceProjection(repository_id, snapshot_id, fingerprint, contracts, items)


def _repository_name(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
) -> str:
    row = connection.execute(
        """
        SELECT r.name FROM repositories r JOIN snapshots s ON s.repository_id = r.id
        WHERE r.id = ? AND s.id = ?
        """,
        (repository_id, snapshot_id),
    ).fetchone()
    if row is None:
        raise ValueError("pattern evidence requires a snapshot owned by the repository")
    return str(row["name"])


def _snapshot_inputs(
    connection: sqlite3.Connection,
    repository_id: int,
    snapshot_id: int,
) -> tuple[
    list[dict[str, Any]], dict[int, dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]
]:
    modules = read_modules(connection, repository_id, snapshot_id)
    raw = {
        int(row["artifact_id"]): dict(row)
        for row in connection.execute("SELECT * FROM projected_file_versions").fetchall()
    }
    install_snapshot_projection(connection, snapshot_id)
    symbols = [dict(row) for row in connection.execute(_SYMBOL_SQL).fetchall()]
    return modules, raw, symbols, semantic_documents(connection, snapshot_id)


def _leaf_items(
    modules: list[dict[str, Any]],
    raw: dict[int, dict[str, Any]],
    symbols: list[dict[str, Any]],
    semantic: dict[str, dict[str, Any]],
    facts: dict[int, list[dict[str, Any]]],
    targets: dict[int, PatternTarget],
    snapshot_id: int,
) -> tuple[dict[int, TargetEvidence], list[TargetEvidence]]:
    symbols_by_artifact: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for symbol in symbols:
        symbols_by_artifact[int(symbol["artifact_id"])].append(symbol)
    module_items = {
        int(module["artifact_id"]): module_evidence(
            targets[int(module["artifact_id"])],
            module,
            raw[int(module["artifact_id"])],
            symbols_by_artifact[int(module["artifact_id"])],
            facts[int(module["artifact_id"])],
            semantic.get(str(module["path"])),
            snapshot_id,
        )
        for module in modules
    }
    return module_items, symbol_evidence(symbols, targets, raw, facts, snapshot_id)


def _parent_items(
    repository_name: str,
    modules: list[dict[str, Any]],
    targets: dict[int, PatternTarget],
    module_items: dict[int, TargetEvidence],
    subsystems: dict[str, PatternTarget],
    areas: dict[str, PatternTarget],
    snapshot_id: int,
    contracts: dict[str, dict[str, Any]],
) -> tuple[dict[str, TargetEvidence], dict[str, TargetEvidence], TargetEvidence]:
    subsystem_items = {
        key: aggregate_evidence(
            target,
            [
                module_items[int(module["artifact_id"])]
                for module in modules
                if targets[int(module["artifact_id"])].parent_key == key
            ],
            snapshot_id,
            contracts,
        )
        for key, target in subsystems.items()
    }
    area_items = {
        key: aggregate_evidence(
            target,
            [item for item in subsystem_items.values() if item.target.parent_key == key],
            snapshot_id,
            contracts,
        )
        for key, target in areas.items()
    }
    repository_item = aggregate_evidence(
        repository_target(repository_name),
        list(area_items.values()),
        snapshot_id,
        contracts,
    )
    return subsystem_items, area_items, repository_item


def _architecture_targets(
    modules: list[dict[str, Any]],
) -> tuple[dict[str, PatternTarget], dict[str, PatternTarget], dict[int, PatternTarget]]:
    areas: dict[str, PatternTarget] = {}
    subsystems: dict[str, PatternTarget] = {}
    module_targets: dict[int, PatternTarget] = {}
    for module in modules:
        taxonomy = module.get("semantic_taxonomy") or {}
        layers = module.get("architecture_layers") or {}
        placement = layers.get(RESPONSIBILITY_MAP) or layers.get(CURRENT_MAP) or {}
        area_identity = str(placement.get("area") or module["architecture_area"])
        subsystem_identity = str(placement.get("subsystem") or module["architecture_group"])
        source = str(placement.get("source") or module["architecture_source"])
        area = area_target(
            area_identity,
            str(taxonomy.get("area_name") or _label(area_identity)),
            source=source,
        )
        areas.setdefault(area.key, area)
        subsystem = subsystem_target(
            subsystem_identity,
            str(taxonomy.get("subsystem_name") or _label(subsystem_identity)),
            area_key=area.key,
            source=source,
        )
        subsystems.setdefault(subsystem.key, subsystem)
        module_targets[int(module["artifact_id"])] = module_target(
            str(module["path"]), subsystem_key=subsystem.key
        )
    return areas, subsystems, module_targets


def _label(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").title()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


_SYMBOL_SQL = """
SELECT s.*, fv.artifact_id, fv.path
FROM projected_symbols s
JOIN projected_file_versions fv ON fv.id = s.artifact_version_id
ORDER BY fv.path, s.qualified_name, s.start_line
"""

_SYMBOL_FOR_PATH_SQL = """
SELECT s.*, fv.artifact_id, fv.path
FROM projected_symbols s
JOIN projected_file_versions fv ON fv.id = s.artifact_version_id
WHERE fv.path = ?
ORDER BY fv.path, s.qualified_name, s.start_line
"""


def empty_pattern_evidence(repository_id: int) -> dict[str, Any]:
    return {
        "repository_id": repository_id,
        "snapshot_id": None,
        "projection_version": PATTERN_EVIDENCE_VERSION,
        "fingerprint": "",
        "capability_contracts": {},
        "total": 0,
        "counts_by_level": {},
        "items": [],
    }
