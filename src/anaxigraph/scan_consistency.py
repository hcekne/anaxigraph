"""Bound working-tree drift across the file reads of one live structural scan.

A working-tree scan reads Git metadata once before discovery and then reads every listed
file from disk, so an edit that lands between those two moments produces a frame stitched
from two states of the checkout. Re-reading the metadata after the reads names that drift;
rediscovering once bounds it. When the second pass still observes drift the frame is
recorded as ``changed_during_scan`` instead of being published with a fingerprint that
describes bytes nobody analysed.

The post-read re-read is only trustworthy because the index lives outside the scanned
checkout by default (``cli_common`` places it under ``XDG_STATE_HOME/anaxigraph``). A
``--db`` path inside an un-ignored directory of the scanned repository makes the index's
own writes - the analysis run row is inserted before discovery starts - show up as
untracked content, so such a checkout would observe drift, rediscover once, and be
recorded as ``changed_during_scan`` on every scan.

The helpers stay pure: callers supply the discovery and metadata callables, so no scanner,
Git, or persistence import is needed and the drift rules can be tested directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

COMMIT_CHANGED = "commit_changed"
WORKING_TREE_CHANGED = "working_tree_changed"
CHANGED_DURING_SCAN = "changed_during_scan"


@dataclass(frozen=True, slots=True)
class ConsistentFrame:
    """A discovered frame with the working-tree metadata verified around its reads."""

    discovery: Any
    metadata: Any
    rediscoveries: int
    drift: str | None


def working_tree_drift(before: Any, after: Any) -> str | None:
    """Name how the checkout moved between two metadata reads, or None when it held still.

    Both arguments are ``GitMetadata`` values. A missing fingerprint on either side means
    the checkout is not a working tree that can be compared (a commit revision, a
    directory outside Git, or a repository without commits), which is reported as no
    drift rather than as an unverifiable frame.
    """

    if before.working_tree_fingerprint is None or after.working_tree_fingerprint is None:
        return None
    if before.commit_sha != after.commit_sha:
        return COMMIT_CHANGED
    if before.working_tree_fingerprint != after.working_tree_fingerprint:
        return WORKING_TREE_CHANGED
    return None


def discover_consistent_frame(
    discover: Callable[[], Any],
    metadata: Callable[[], Any] | None,
    *,
    before: Any,
    max_attempts: int = 2,
    on_retry: Callable[[], None] | None = None,
) -> ConsistentFrame:
    """Discover a frame, then re-read metadata until the checkout held still or attempts run out.

    ``metadata`` is None for scans that cannot drift (a commit revision), and the recheck
    is also skipped when the frame carries no working-tree fingerprint, so neither case
    pays for an extra Git call.
    """

    if metadata is None or before.working_tree_fingerprint is None:
        return ConsistentFrame(discover(), before, 0, None)
    verified = before
    rediscoveries = 0
    while True:
        discovery = discover()
        after = metadata()
        drift = working_tree_drift(verified, after)
        verified = after
        if drift is None:
            return ConsistentFrame(discovery, after, rediscoveries, None)
        if rediscoveries + 1 >= max_attempts:
            return ConsistentFrame(discovery, unverified(after), rediscoveries, drift)
        rediscoveries += 1
        if on_retry is not None:
            on_retry()


def unverified(metadata: Any) -> Any:
    """Drop a fingerprint that no longer describes the bytes that were read."""

    return replace(metadata, working_tree_fingerprint=None, scan_consistency=CHANGED_DURING_SCAN)
