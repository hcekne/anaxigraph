"""Read-only Git integration used by scans, history, and agent collision checks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from codeintel.models import GitMetadata


class GitError(RuntimeError):
    pass


def _run(
    root: Path,
    *args: str,
    check: bool = True,
    timeout: int = 60,
    text: bool = True,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-c", f"safe.directory={root}", "-C", str(root), *args],
            check=check,
            capture_output=True,
            text=text,
            timeout=timeout,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        if check:
            message = getattr(exc, "stderr", None) or str(exc)
            raise GitError(message.strip()) from exc
        raise


def is_repository(root: Path) -> bool:
    result = _run(root, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def metadata(root: Path, *, revision: str | None = None) -> GitMetadata:
    if not is_repository(root):
        return GitMetadata(
            commit_sha="unversioned",
            parent_commit_sha=None,
            branch="unversioned",
            commit_timestamp=None,
            dirty=True,
            remote_url=None,
            default_branch=None,
        )
    revision = revision or "HEAD"
    commit_sha = _run(root, "rev-parse", revision).stdout.strip()
    parent = _run(root, "rev-parse", f"{revision}^", check=False)
    parent_sha = parent.stdout.strip() if parent.returncode == 0 else None
    if revision == "HEAD":
        branch_result = _run(root, "branch", "--show-current", check=False)
        branch = branch_result.stdout.strip() or "detached"
        dirty = bool(_run(root, "status", "--porcelain=v1", "-uno").stdout.strip())
    else:
        branch = revision
        dirty = False
    timestamp = _run(root, "show", "-s", "--format=%cI", revision).stdout.strip() or None
    remote = _run(root, "remote", "get-url", "origin", check=False)
    remote_url = remote.stdout.strip() if remote.returncode == 0 else None
    origin_head = _run(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    default_branch = (
        origin_head.stdout.strip().removeprefix("origin/") if origin_head.returncode == 0 else None
    )
    return GitMetadata(
        commit_sha=commit_sha,
        parent_commit_sha=parent_sha,
        branch=branch,
        commit_timestamp=timestamp,
        dirty=dirty,
        remote_url=remote_url,
        default_branch=default_branch,
    )


def listed_files(root: Path) -> list[str]:
    if not is_repository(root):
        return []
    result = _run(
        root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        text=False,
    )
    return sorted(
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    )


def files_at_revision(root: Path, revision: str) -> list[str]:
    result = _run(root, "ls-tree", "-r", "--name-only", "-z", revision, text=False)
    return sorted(
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    )


def read_at_revision(root: Path, revision: str, path: str, *, max_bytes: int) -> bytes | None:
    result = _run(root, "show", f"{revision}:{path}", check=False, text=False)
    if result.returncode != 0 or len(result.stdout) > max_bytes:
        return None
    return bytes(result.stdout)


def revisions(
    root: Path,
    *,
    limit: int | None,
    since: str | None = None,
    oldest_first: bool = False,
) -> list[str]:
    args = ["rev-list", "--first-parent"]
    if limit is not None:
        args.append(f"--max-count={max(1, limit)}")
    if since:
        args.append(f"--since={since}")
    if oldest_first:
        args.append("--reverse")
    args.append("HEAD")
    return [line for line in _run(root, *args).stdout.splitlines() if line]


@dataclass(frozen=True, slots=True)
class GitChange:
    commit_sha: str
    committed_at: str
    author_name: str
    subject: str
    path: str
    change_type: str
    additions: int | None
    deletions: int | None


def recent_changes(root: Path, *, limit: int = 5_000) -> list[GitChange]:
    if not is_repository(root):
        return []
    # Record and field separators avoid ambiguity from spaces and tabs in subjects.
    result = _run(
        root,
        "log",
        f"--max-count={max(1, limit)}",
        "--date=iso-strict",
        "--format=%x1e%H%x1f%cI%x1f%an%x1f%s",
        "--numstat",
        "--no-renames",
        timeout=120,
    )
    changes: list[GitChange] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        header, *lines = record.splitlines()
        fields = header.split("\x1f", 3)
        if len(fields) != 4:
            continue
        commit_sha, committed_at, author_name, subject = fields
        for line in lines:
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            additions_raw, deletions_raw, path = parts
            additions = int(additions_raw) if additions_raw.isdigit() else None
            deletions = int(deletions_raw) if deletions_raw.isdigit() else None
            changes.append(
                GitChange(
                    commit_sha=commit_sha,
                    committed_at=committed_at,
                    author_name=author_name,
                    subject=subject,
                    path=path,
                    change_type="modified",
                    additions=additions,
                    deletions=deletions,
                )
            )
    return changes


def changed_paths(root: Path, branch: str, *, base: str | None = None) -> set[str]:
    if not is_repository(root):
        return set()
    base = base or _default_comparison_branch(root)
    merge_base = _run(root, "merge-base", base, branch, check=False)
    if merge_base.returncode != 0:
        return set()
    result = _run(
        root,
        "diff",
        "--name-only",
        "--diff-filter=ACMRTUXB",
        f"{merge_base.stdout.strip()}...{branch}",
        check=False,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def active_branch_changes(root: Path, *, exclude: str | None = None) -> dict[str, set[str]]:
    if not is_repository(root):
        return {}
    result = _run(
        root,
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
        "refs/remotes/origin",
        check=False,
    )
    base = _default_comparison_branch(root)
    branches: dict[str, set[str]] = {}
    for branch in result.stdout.splitlines():
        branch = branch.strip()
        if not branch or branch.endswith("/HEAD") or branch in {base, f"origin/{base}", exclude}:
            continue
        paths = changed_paths(root, branch, base=base)
        if paths:
            branches[branch] = paths
    return branches


def _default_comparison_branch(root: Path) -> str:
    info = metadata(root)
    candidates = [
        f"origin/{info.default_branch}" if info.default_branch else "",
        info.default_branch or "",
        "origin/main",
        "main",
        "origin/master",
        "master",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        result = _run(root, "rev-parse", "--verify", candidate, check=False)
        if result.returncode == 0:
            return candidate
    return "HEAD"
