"""Offline matched profile of catalogue status and bounded Pattern witnesses.

Run with ``PYTHONPATH=src:tests:. .venv/bin/python benchmarks/semantic_control_plane.py``.
The previous variant restores only the two documented hot paths in memory; both
variants use the same completed, deterministic 200-module fixture. No models run.
"""

from __future__ import annotations

import cProfile
import hashlib
import inspect
import io
import json
import pstats
import statistics
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from semantic_support import _DeterministicLifecycleProvider, _enable_agent_semantics

import anaxigraph.semantic_pattern_requests as requests
from anaxigraph import semantic_status_queries
from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.persistence import pattern_catalogue_read
from anaxigraph.persistence.semantic_evidence import semantic_inventory
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine
from benchmarks.repository_factory import create_history_repository


def _fixture(directory):
    root = directory / "repository"
    create_history_repository(root, file_count=200, commits=1)
    _enable_agent_semantics(root, detailed_reviews=True)
    database = AnaxiIndex(directory / "index.db")
    stats = RepositoryScanner(database).scan(root)
    config = load_config(root)
    engine = SemanticEngine(database)
    provider = _DeterministicLifecycleProvider()
    with patch("anaxigraph.semantic_runner.create_semantic_provider", lambda _config: provider):
        completed = engine.bootstrap(
            stats.repository_id,
            root,
            config,
            until_complete=True,
            execution_semantic=SemanticConfig(provider="codex", max_parallel_jobs=16),
        )
    assert completed["semantic"]["semantically_ready"], completed
    return root, database, stats, config, engine


def _witness_job(database, repository_id):
    with database.connect() as connection:
        job = dict(
            connection.execute(
                "SELECT * FROM semantic_jobs WHERE job_kind = 'pattern_assessment' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        )
    job["metadata"] = json.loads(job["metadata_json"])
    paths = [row["path"] for row in database.modules(repository_id)[:8]]
    # Terminal metadata is intentionally compact. Restore a controlled bounded
    # witness packet, not a claim about the original provider's exact packet.
    job["metadata"]["target_evidence"] = {
        "features": [
            {"name": "architecture.witnesses", "value": {"items": [{"path": p} for p in paths]}}
        ],
        "placement_hints": [],
    }
    return job


def _previous_functions():
    source = inspect.getsource(pattern_catalogue_read.read_pattern_catalogue)
    start = source.index("    # Saved coverage belongs")
    end = source.index("    if not query.include_manifest:", start)
    source = (
        source[:start]
        + "    coverage = _coverage(expected, all_items, records, manifest, catalog.fingerprint)\n"
        + source[end:]
    )
    namespace = dict(vars(pattern_catalogue_read))
    exec(compile(source, "<previous-catalogue-read>", "exec"), namespace)
    read = namespace["read_pattern_catalogue"]
    witness = inspect.getsource(requests._parent_source_evidence)
    start = witness.index("    witnesses = _witness_facts(")
    end = witness.index("    result = []", start)
    witness = (
        witness[:start]
        + "    with database.connect() as connection:\n"
        + "        inventory, _relationships = semantic_inventory(connection, int(job['snapshot_id']))\n"
        + witness[end:]
    )
    witness = witness.replace(
        "version, symbols = witnesses.get(path, (None, []))",
        "version = inventory.get(path)\n        symbols = (version or {}).get('symbols') or []",
    )
    namespace = {**vars(requests), "semantic_inventory": semantic_inventory}
    exec(compile(witness, "<previous-parent-source-evidence>", "exec"), namespace)
    return read, namespace["_parent_source_evidence"]


def _measure(operation):
    operation()
    samples = []
    for _ in range(5):
        started = time.perf_counter()
        operation()
        samples.append(time.perf_counter() - started)
    profile = cProfile.Profile()
    profile.runcall(operation)
    output = io.StringIO()
    pstats.Stats(profile, stream=output).sort_stats("cumulative").print_stats(16)
    return {
        "median_s": statistics.median(samples),
        "samples_s": samples,
        "profile": output.getvalue(),
    }


def _variant(name, fixture, previous):
    root, database, stats, config, engine = fixture
    job = _witness_job(database, stats.repository_id)
    with ExitStack() as patches:
        if name == "previous_hot_paths":
            patches.enter_context(
                patch.object(semantic_status_queries, "read_pattern_catalogue", previous[0])
            )
            patches.enter_context(patch.object(requests, "_parent_source_evidence", previous[1]))

        def request():
            return engine._services.evidence.job_request(job, root, config.semantic)

        operations = {
            "status": lambda: engine.status(stats.repository_id, config.semantic),
            "idle_claim": lambda: engine.claim_agent_work(
                stats.repository_id, root, config, agent_id="benchmark", agent_model="fixture"
            ),
            "witness_request": request,
            "fixture_model": lambda: _DeterministicLifecycleProvider().analyze(request_value),
        }
        request_value = request()
        encoded = json.dumps(request_value, sort_keys=True).encode()
        return {
            "request_sha256": hashlib.sha256(encoded).hexdigest(),
            "request_bytes": len(encoded),
            **{key: _measure(operation) for key, operation in operations.items()},
        }


def main():
    previous = _previous_functions()
    with tempfile.TemporaryDirectory(prefix="anaxigraph-control-plane-") as temporary:
        fixture = _fixture(Path(temporary))
        variants = {
            name: _variant(name, fixture, previous) for name in ("previous_hot_paths", "current")
        }
    assert variants["previous_hot_paths"]["request_sha256"] == variants["current"]["request_sha256"]
    result = {
        "date": "2026-10-23",
        "method": "Matched current code with only two previous hot paths restored in memory; same completed deterministic 200-module repository, 133 catalogue cards, no coverage; five warmed timing samples and a separate cProfile per operation.",
        "paid_model_calls": 0,
        "witness_packet": "Controlled eight-file packet reconstructed after terminal-job metadata compaction.",
        "limitations": [
            "Synthetic controlled workload, not a live repository or model-quality evaluation.",
            "Same host with other agents active; latency is observed, not a service guarantee.",
            "No measured whole-workflow speedup or architectural novelty claim.",
        ],
        "variants": variants,
    }
    destination = Path("benchmarks/results/semantic-control-plane-2026-10-23.json")
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                name: {
                    key: value["median_s"]
                    for key, value in variant.items()
                    if isinstance(value, dict)
                }
                for name, variant in variants.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
