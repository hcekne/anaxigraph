from __future__ import annotations

from benchmarks.graph_scale import run_benchmark


def test_graph_scale_smoke_proves_bounded_contracts(tmp_path):
    report = run_benchmark(tmp_path, 1_000)

    assert report["passed"] is True
    assert all(report["assertions"].values())
    assert report["overview"]["represented_files"] == 1_000
    assert report["region"]["counts"]["page_internal_nodes"] < 1_000
    assert report["region"]["has_next_cursor"] is True
