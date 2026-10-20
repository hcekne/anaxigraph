"""Recognize linked checkouts of the operator registered Git repositories."""

from __future__ import annotations

import hashlib
import time
from functools import lru_cache
from pathlib import Path

import anaxigraph.git as git
from anaxigraph.registry import RepositoryTarget


def expand_worktree_targets(targets: tuple[RepositoryTarget, ...]) -> tuple[RepositoryTarget, ...]:
    """Recognize linked checkouts of registered repositories, including newly created ones."""
    stamps = tuple(_worktree_stamp(target.path) for target in targets)
    return _expanded_worktrees(targets, stamps, int(time.monotonic() // 2))


def _worktree_stamp(root: Path) -> int:
    directory = root / ".git"
    try:
        if directory.is_file():
            directory = (
                (root / directory.read_text().strip().removeprefix("gitdir: "))
                .resolve()
                .parent.parent
            )
        return (directory / "worktrees").stat().st_mtime_ns
    except OSError:
        return 0


@lru_cache(maxsize=64)
def _expanded_worktrees(
    targets: tuple[RepositoryTarget, ...], stamps: tuple[int, ...], epoch: int
) -> tuple[RepositoryTarget, ...]:
    result = {target.path.resolve(): target for target in targets}
    for target in targets:
        for root in git.worktrees(target.path):
            if root in result:
                continue
            config = target.config_path
            if config and config.is_relative_to(target.path):
                config = root / config.relative_to(target.path)
            result[root] = RepositoryTarget(
                key=f"{target.key}:worktree:{root.name}:{hashlib.sha256(str(root).encode()).hexdigest()[:8]}",
                path=root,
                config_path=config,
                history_snapshots=0,
            )
    return tuple(result.values())
