#!/usr/bin/env python3
"""Reject local protected-branch commits and newly introduced merge history."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def commit_errors(root: Path) -> list[str]:
    errors = []
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if branch in {"main", "master"}:
        errors.append(f"Cannot commit on protected branch {branch}; use a pull request.")
    merge_head = _git(root, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip()
    if merge_head and (root / merge_head).is_file():
        errors.append("Cannot create a merge commit; rebase the feature branch instead.")
    return errors


def history_errors(root: Path, base: str, head: str) -> list[str]:
    for revision in (base, head):
        if _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}").returncode:
            return [f"History base/head unavailable: {revision!r}; fetch origin main first."]
    result = _git(root, "rev-list", "--min-parents=2", f"{base}..{head}")
    if result.returncode:
        return [f"Cannot inspect proposed history: {result.stderr.strip()}"]
    if result.stdout.strip():
        commits = ", ".join(line[:12] for line in result.stdout.splitlines()[:10])
        return [f"New merge commit(s) violate linear history: {commits}; rebase before pushing."]
    return []


def push_errors(root: Path, base: str) -> list[str]:
    errors = history_errors(root, base, "HEAD")
    remote_branch = os.environ.get("PRE_COMMIT_REMOTE_BRANCH", "")
    if remote_branch in {"refs/heads/main", "refs/heads/master"}:
        errors.append("Direct protected-branch push detected; merge through a reviewed PR.")
    local_ref = os.environ.get("PRE_COMMIT_LOCAL_BRANCH")
    if local_ref:
        target = _git(root, "rev-parse", "--verify", f"{local_ref}^{{commit}}")
        head = _git(root, "rev-parse", "HEAD")
        if target.returncode or target.stdout != head.stdout:
            errors.append("Push the checked-out HEAD; these checks cannot verify another tree.")
        if _git(root, "diff", "--quiet", "HEAD", "--").returncode:
            errors.append("Tracked changes are uncommitted; commit them before verifying a push.")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--stage", choices=("commit", "push", "history"), default="commit")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    if _git(args.root, "rev-parse", "--git-dir").returncode:
        errors = ["Git repository unavailable; cannot verify commit policy."]
    elif args.stage == "history":
        errors = history_errors(args.root, args.base, args.head)
    elif args.stage == "push":
        errors = push_errors(args.root, args.base)
    else:
        errors = commit_errors(args.root)
    for error in errors:
        print(f"ERROR: {error}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
