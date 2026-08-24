from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from anaxigraph.storage import AnaxiIndex


def test_scan_lock_serializes_index_users(database):
    entered = threading.Event()
    release = threading.Event()
    acquired = threading.Event()
    second = AnaxiIndex(database.path)

    def hold_lock() -> None:
        with database.scan_lock():
            entered.set()
            assert release.wait(timeout=2)

    def wait_for_lock() -> None:
        assert entered.wait(timeout=2)
        with second.scan_lock():
            acquired.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        holder = executor.submit(hold_lock)
        assert entered.wait(timeout=2)
        waiter = executor.submit(wait_for_lock)
        try:
            assert not acquired.wait(timeout=0.1)
        finally:
            release.set()
        holder.result(timeout=2)
        waiter.result(timeout=2)

    assert acquired.is_set()
