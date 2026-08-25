from collections import Counter

from benchmarks.baseline import _counting_registry


def test_benchmark_counter_preserves_analyzer_capability_contract():
    counts = Counter()
    registry = _counting_registry(counts)
    analyzer = registry.for_language("python")

    assert analyzer is not None
    assert analyzer.capabilities.analyzer == analyzer.name
    assert analyzer.capabilities.analyzer_version == analyzer.version
    analyzer.analyze("example.py", "value = 1\n")
    assert counts["total"] == 1
