"""Read repository inputs without importing or executing the analyzed project."""

from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import os
import subprocess
import tokenize
from datetime import datetime, timezone
from pathlib import Path

from anaxigraph.contracts import Snapshot

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    ".anaxigraph",
    ".anaxigraph-v2",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "htmlcov",
    "test-results",
    "playwright-report",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".db-shm", ".db-wal"}
MAX_INPUT_BYTES = 2_000_000
INDEX_VERSION = "python-ast-v1"


def _git(root: Path, *args: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, timeout=20, check=False
        )
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _excluded(path: str, patterns: tuple[str, ...]) -> bool:
    parts = Path(path).parts
    if not parts or parts[0] == "anaxigraph":
        return True  # The Git-carried portable record, not a source package under src/.
    if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in parts):
        return True
    if any(path.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return True
    return any(
        fnmatch.fnmatchcase(path, pattern.rstrip("/"))
        or path.startswith(pattern.rstrip("/") + "/")
        or (
            "/" not in pattern.rstrip("/")
            and any(fnmatch.fnmatchcase(part, pattern.rstrip("/")) for part in parts)
        )
        for pattern in patterns
    )


def _regular_input(root: Path, relative: str) -> Path | None:
    """Reject symlinks at every component, including cached Git directory entries."""
    candidate = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        return None
    current = root
    try:
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                return None
        resolved = candidate.resolve(strict=True)
        return resolved if resolved.is_relative_to(root) and resolved.is_file() else None
    except (OSError, RuntimeError):
        return None


def discover(root: Path, excluded: tuple[str, ...]) -> tuple[Snapshot, dict[str, str], list[str]]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository root must be a directory")
    diagnostics: list[str] = []
    listing = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", ".")
    revision = _git(root, "rev-parse", "HEAD")
    changed = _git(root, "diff", "--name-only", "--relative", "-z", "HEAD", "--", ".")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", ".")
    if listing is not None:
        candidates = sorted(set(os.fsdecode(p) for p in listing.split(b"\0") if p))
    else:
        diagnostics.append(
            "No Git inventory available; scanning regular files with default exclusions."
        )
        candidates = []
        for directory, dirs, files in os.walk(root, followlinks=False):
            relative = Path(directory).relative_to(root)
            dirs[:] = [d for d in dirs if not _excluded((relative / d).as_posix(), excluded)]
            candidates.extend((relative / name).as_posix() for name in files)
        candidates.sort()
    dirty_paths = [os.fsdecode(p) for p in (changed or b"").split(b"\0") if p]
    dirty_paths.extend(os.fsdecode(p) for p in (untracked or b"").split(b"\0") if p)
    if listing is not None and revision is None:
        dirty_paths.extend(candidates)  # New Git repository without its first commit.
    dirty = any(not _excluded(path, excluded) for path in dirty_paths)
    files: dict[str, str] = {}
    contents: dict[str, str] = {}
    binary_count = 0
    for relative in candidates:
        if _excluded(relative, excluded):
            continue
        path = _regular_input(root, relative)
        if path is None:
            if (root / relative).exists():
                diagnostics.append(f"{relative}: not a regular repository input; not analyzed.")
            continue
        try:
            # Bound reads; the same captured bytes feed both fingerprints and parsing.
            # Files omitted here are explicitly outside this snapshot's analyzed coverage.
            if path.stat().st_size > MAX_INPUT_BYTES:
                diagnostics.append(
                    f"{relative}: exceeds {MAX_INPUT_BYTES}-byte input limit; not analyzed."
                )
                continue
            with path.open("rb") as stream:
                content = stream.read(MAX_INPUT_BYTES + 1)
            if len(content) > MAX_INPUT_BYTES:
                raise ValueError(
                    f"{relative}: file grew beyond input limit during capture; rescan."
                )
            if b"\0" in content[:8192] and path.suffix not in {".py", ".pyi"}:
                binary_count += 1
                continue
            files[relative] = hashlib.sha256(content).hexdigest()
            if path.suffix in {".py", ".pyi"}:
                encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
                contents[relative] = content.decode(encoding)
        except (OSError, UnicodeError, SyntaxError) as exc:
            diagnostics.append(f"{relative}: input could not be read ({type(exc).__name__}).")
    if binary_count:
        diagnostics.append(f"{binary_count} binary files excluded from analyzed coverage.")
    unsupported = sum(
        Path(path).suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"} for path in files
    )
    if unsupported:
        diagnostics.append(
            f"{unsupported} JavaScript/TypeScript files fingerprinted but not parsed in this Python-first milestone."
        )
    identity = {
        "root": str(root),
        "revision": revision.decode().strip() if revision else None,
        "dirty": dirty,
        "files": files,
        "excluded": sorted(excluded),
        "indexer": INDEX_VERSION,
    }
    snapshot_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return (
        Snapshot(
            id=snapshot_id,
            root=str(root),
            revision=identity["revision"],
            dirty=dirty,
            files=files,
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        contents,
        diagnostics,
    )
