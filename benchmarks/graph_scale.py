"""Reproducible 50k-node proof for bounded architecture overview and region reads."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from anaxigraph.graph_contract import GraphNeighborhoodRequest, GraphPageRequest
from anaxigraph.storage import AnaxiIndex
from benchmarks.runtime_metrics import measure

DEFAULT_NODES = 50_000
SUBSYSTEMS = 100
AREAS = 10
PAYLOAD_BUDGET_BYTES = 2_000_000
READ_BUDGET_MS = 15_000
MEMORY_DELTA_BUDGET_BYTES = 512 * 1024 * 1024


def seed_graph(index: AnaxiIndex, repository: Path, node_count: int) -> int:
    started = time.perf_counter()
    now = datetime.now(UTC).isoformat()
    with index.transaction() as connection:
        repository_id = _repository(connection, repository, now)
        snapshot_id = _snapshot(connection, repository_id, node_count, now)
        for start in range(1, node_count + 1, 5_000):
            stop = min(node_count + 1, start + 5_000)
            _seed_node_chunk(connection, repository_id, snapshot_id, start, stop, now)
        for start in range(1, node_count + 1, 5_000):
            stop = min(node_count + 1, start + 5_000)
            _seed_edge_chunk(connection, repository_id, snapshot_id, start, stop, node_count, now)
        _groups(connection, repository_id)
        connection.execute(
            "UPDATE repositories SET current_snapshot_id = ? WHERE id = ?",
            (snapshot_id, repository_id),
        )
    return round((time.perf_counter() - started) * 1_000)


def measure_graph_scale(index: AnaxiIndex, repository_id: int, node_count: int) -> dict[str, Any]:
    overview, overview_runtime = measure(lambda: _architecture_overview(index, repository_id))
    region, region_runtime = measure(
        lambda: index.graph(
            repository_id,
            query=GraphPageRequest(
                areas=("area-03",),
                node_limit=min(250, max(1, node_count // 20)),
                edge_limit=500,
            ),
        )
    )
    neighbors, neighbor_runtime = measure(
        lambda: index.graph_neighborhood(
            repository_id,
            query=GraphNeighborhoodRequest(
                node=_path(3),
                depth=2,
                node_limit=100,
                edge_limit=250,
            ),
        )
    )
    report = {
        "schema_version": "graph-scale-v1",
        "fixture": {"nodes": node_count, "edges": node_count, "areas": AREAS},
        "overview": _measurement(overview, overview_runtime),
        "region": _measurement(region, region_runtime),
        "neighborhood": _measurement(neighbors, neighbor_runtime),
        "budgets": {
            "payload_bytes": PAYLOAD_BUDGET_BYTES,
            "read_ms": READ_BUDGET_MS,
            "peak_resident_delta_bytes": MEMORY_DELTA_BUDGET_BYTES,
        },
    }
    report["assertions"] = _assertions(report)
    report["passed"] = all(report["assertions"].values())
    return report


def _architecture_overview(index: AnaxiIndex, repository_id: int) -> dict[str, Any]:
    nodes = index.overview(repository_id)["group_hierarchies"]["current"]
    return {
        "contract_version": "responsibility-map-v1",
        "counts": {"groups": len(nodes)},
        "nodes": nodes,
        "edges": [],
    }


def run_benchmark(work: Path, node_count: int) -> dict[str, Any]:
    repository = work / "repository"
    repository.mkdir(parents=True, exist_ok=True)
    index = AnaxiIndex(work / "anaxi-index.db")
    seed_ms = seed_graph(index, repository, node_count)
    row = index.repository(repository)
    assert row is not None
    report = measure_graph_scale(index, int(row["id"]), node_count)
    report["fixture"]["seed_ms"] = seed_ms
    report["fixture"]["index_bytes"] = sum(
        path.stat().st_size for path in (index.path, Path(f"{index.path}-wal")) if path.exists()
    )
    return report


def _repository(connection: Any, repository: Path, now: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO repositories(name, path, created_at, updated_at)
        VALUES ('Graph scale fixture', ?, ?, ?)
        """,
        (str(repository.resolve()), now, now),
    )
    return int(cursor.lastrowid)


def _snapshot(connection: Any, repository_id: int, node_count: int, now: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO snapshots(
            repository_id, commit_sha, branch, analysis_timestamp,
            content_fingerprint, dirty, sequence
        ) VALUES (?, 'synthetic', 'main', ?, ?, 0, 0)
        """,
        (repository_id, now, f"graph-scale-{node_count}"),
    )
    return int(cursor.lastrowid)


def _seed_node_chunk(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    start: int,
    stop: int,
    now: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO artifacts(
            id, repository_id, canonical_path, artifact_type, created_at
        ) VALUES (?, ?, ?, 'source', ?)
        """,
        ((index, repository_id, _path(index), now) for index in range(start, stop)),
    )
    connection.executemany(
        """
        INSERT INTO file_facts(
            id, artifact_id, fact_key, analysis_signature, language, raw_hash,
            structural_hash, lines_of_code, comment_lines, complexity, summary,
            responsibilities_json, inputs_json, outputs_json, side_effects_json,
            public_interfaces_json, analyzer, metadata_json, created_at
        ) VALUES (?, ?, ?, 'scale-v1', 'python', ?, ?, 20, 1, 2,
                  'Synthetic graph module', '[]', '[]', '[]', '[]', '[]',
                  'builtin-python-ast', '{}', ?)
        """,
        (
            (index, index, f"fact-{index}", f"raw-{index}", f"struct-{index}", now)
            for index in range(start, stop)
        ),
    )
    connection.executemany(
        """
        INSERT INTO snapshot_file_changes(
            snapshot_id, artifact_id, change_kind, file_fact_id, path,
            declared_group, analysis_status, metadata_json, first_seen_at, last_changed_at
        ) VALUES (?, ?, 'add', ?, ?, ?, 'analyzed', '{}', ?, ?)
        """,
        (
            (snapshot_id, index, index, _path(index), _subsystem(index), now, now)
            for index in range(start, stop)
        ),
    )


def _seed_edge_chunk(
    connection: Any,
    repository_id: int,
    snapshot_id: int,
    start: int,
    stop: int,
    node_count: int,
    now: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO relationship_sets(
            id, repository_id, source_artifact_id, source_file_fact_id, set_key,
            resolver_context_hash, analysis_signature, content_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, 'resolver-v1', 'scale-v1', ?, ?)
        """,
        (
            (index, repository_id, index, index, f"set-{index}", f"edge-{index}", now)
            for index in range(start, stop)
        ),
    )
    connection.executemany(
        """
        INSERT INTO relationship_edges(
            id, relationship_set_id, target_artifact_id, relationship_type,
            source, confidence, evidence, source_line, weight, metadata_json
        ) VALUES (?, ?, ?, 'imports', 'synthetic', 1, 'scale edge', 1, 1, ?)
        """,
        (
            (
                index,
                index,
                ((index + AREAS - 1) % node_count) + 1,
                '{"candidate_paths":[],"resolution_status":"resolved_internal"}',
            )
            for index in range(start, stop)
        ),
    )
    connection.executemany(
        """
        INSERT INTO snapshot_relationship_changes(
            snapshot_id, source_artifact_id, change_kind, relationship_set_id
        ) VALUES (?, ?, 'set', ?)
        """,
        ((snapshot_id, index, index) for index in range(start, stop)),
    )


def _groups(connection: Any, repository_id: int) -> None:
    values: list[tuple[Any, ...]] = []
    for index in range(AREAS):
        values.append((repository_id, f"area-{index:02}", "area", None))
    for index in range(SUBSYSTEMS):
        values.append(
            (
                repository_id,
                f"subsystem-{index:03}",
                "subsystem",
                f"area-{index % AREAS:02}",
            )
        )
    connection.executemany(
        """
        INSERT INTO groups(repository_id, name, level, parent_name, source)
        VALUES (?, ?, ?, ?, 'declared')
        """,
        values,
    )


def _path(index: int) -> str:
    subsystem = index % SUBSYSTEMS
    area = subsystem % AREAS
    return f"src/area-{area:02}/subsystem-{subsystem:03}/module-{index:05}.py"


def _subsystem(index: int) -> str:
    return f"subsystem-{index % SUBSYSTEMS:03}"


def _measurement(payload: dict[str, Any], runtime: dict[str, int]) -> dict[str, Any]:
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return {
        **runtime,
        "payload_bytes": len(encoded),
        "contract_version": payload["contract_version"],
        "counts": payload["counts"],
        "returned_nodes": len(payload.get("nodes") or []),
        "returned_edges": len(payload.get("edges") or []),
        "represented_files": sum(
            int(node.get("files") or 0) for node in payload.get("nodes") or []
        ),
        "has_next_cursor": bool(payload.get("next_cursor")),
    }


def _assertions(report: dict[str, Any]) -> dict[str, bool]:
    measurements = [report[name] for name in ("overview", "region", "neighborhood")]
    return {
        "overview_represents_every_node": (
            report["overview"]["represented_files"] == report["fixture"]["nodes"]
        ),
        "all_payloads_bounded": all(
            item["payload_bytes"] <= PAYLOAD_BUDGET_BYTES for item in measurements
        ),
        "all_reads_within_budget": all(
            item["wall_time_ms"] <= READ_BUDGET_MS for item in measurements
        ),
        "memory_within_budget": all(
            item["peak_resident_delta_bytes"] <= MEMORY_DELTA_BUDGET_BYTES for item in measurements
        ),
        "region_is_paginated": (
            report["region"]["counts"]["matching_nodes"]
            > report["region"]["counts"]["page_internal_nodes"]
            and report["region"]["counts"]["page_internal_nodes"] <= 250
            and report["region"]["has_next_cursor"]
        ),
        "neighborhood_is_bounded": (
            report["neighborhood"]["counts"]["returned_internal_nodes"] <= 100
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=DEFAULT_NODES)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.nodes < 1:
        raise ValueError("--nodes must be positive")
    with tempfile.TemporaryDirectory(prefix="anaxigraph-graph-scale-") as temporary:
        report = run_benchmark(Path(temporary), args.nodes)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
