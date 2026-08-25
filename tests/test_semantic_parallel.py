"""Bounded fan-out contracts for independent semantic model calls."""

from __future__ import annotations

import threading
import time

from anaxigraph.semantic_parallel import parallel_map


def test_parallel_map_uses_the_bound_and_preserves_input_order():
    lock = threading.Lock()
    active = 0
    peak = 0

    def work(value: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return value * 2

    assert parallel_map(work, range(8), 4) == [value * 2 for value in range(8)]
    assert peak == 4
