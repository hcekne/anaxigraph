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
MAX_SOURCE_PACKET_BYTES = 100_000
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


def _paths(listing: bytes | None) -> list[str]:
    return [os.fsdecode(path) for path in (listing or b"").split(b"\0") if path]


def _walk_files(root: Path, excluded: tuple[str, ...]) -> list[str]:
    candidates = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        relative = Path(directory).relative_to(root)
        dirs[:] = [name for name in dirs if not _excluded((relative / name).as_posix(), excluded)]
        candidates.extend((relative / name).as_posix() for name in files)
    return sorted(candidates)


def _inventory(
    root: Path, excluded: tuple[str, ...], diagnostics: list[str]
) -> tuple[list[str], str | None, bool]:
    """Choose Git-tracked/untracked inputs and report dirty state in the same scope."""
    listing = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", ".")
    revision = _git(root, "rev-parse", "HEAD")
    changed = _git(root, "diff", "--name-only", "--relative", "-z", "HEAD", "--", ".")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", ".")
    if listing is not None:
        candidates = sorted(set(_paths(listing)))
    else:
        diagnostics.append(
            "No Git inventory available; scanning regular files with default exclusions."
        )
        candidates = _walk_files(root, excluded)
    dirty_paths = _paths(changed) + _paths(untracked)
    if listing is not None and revision is None:
        dirty_paths.extend(candidates)  # New Git repository without its first commit.
    dirty = any(not _excluded(path, excluded) for path in dirty_paths)
    return candidates, revision.decode().strip() if revision else None, dirty


def _read_input(
    root: Path, relative: str, diagnostics: list[str], maximum: int = MAX_INPUT_BYTES
) -> bytes | None:
    """Capture one bounded regular input; do not silently truncate parser source."""
    path = _regular_input(root, relative)
    if path is None:
        if (root / relative).exists():
            diagnostics.append(f"{relative}: not a regular repository input; not analyzed.")
        return None
    try:
        if path.stat().st_size > maximum:
            diagnostics.append(f"{relative}: exceeds {maximum}-byte input limit; not analyzed.")
            return None
        with path.open("rb") as stream:
            content = stream.read(maximum + 1)
        if len(content) > maximum:
            raise ValueError(f"{relative}: file grew beyond input limit during capture; rescan.")
        return content
    except OSError as exc:
        diagnostics.append(f"{relative}: input could not be read ({type(exc).__name__}).")
        return None


def capture_sources(root: Path, paths: list[str], fingerprints: dict[str, str]) -> dict[str, str]:
    """Read exact mapped source for agent packets without following symlinks or executing code.

    The source packet budget is smaller than structural indexing's input budget. Decode Python
    coding cookies from the same bounded bytes whose fingerprint was checked; never replace an
    invalid sequence silently or return partial source.
    """
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository root must be a directory")
    sources = {}
    for relative in paths:
        if relative not in fingerprints:
            raise ValueError("Source path must belong to the analyzed snapshot")
        diagnostics: list[str] = []
        raw = _read_input(root, relative, diagnostics, MAX_SOURCE_PACKET_BYTES)
        if raw is None:
            raise ValueError(f"Source could not be captured: {relative}; {diagnostics}")
        if hashlib.sha256(raw).hexdigest() != fingerprints[relative]:
            raise ValueError("Source changed after mapping; scan again before annotation")
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            sources[relative] = raw.decode(encoding)
        except (UnicodeError, SyntaxError) as exc:
            raise ValueError(f"Source encoding could not be decoded: {relative}") from exc
    return sources


def _capture_inputs(
    root: Path, candidates: list[str], excluded: tuple[str, ...], diagnostics: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Fingerprint captured bytes and decode supported Python inputs from those exact bytes."""
    files: dict[str, str] = {}
    contents: dict[str, str] = {}
    binary_count = 0
    for relative in candidates:
        if _excluded(relative, excluded):
            continue
        content = _read_input(root, relative, diagnostics)
        if content is None:
            continue
        suffix = Path(relative).suffix
        if b"\0" in content[:8192] and suffix not in {".py", ".pyi"}:
            binary_count += 1
            continue
        files[relative] = hashlib.sha256(content).hexdigest()
        try:
            if suffix in {".py", ".pyi"}:
                encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
                contents[relative] = content.decode(encoding)
        except (UnicodeError, SyntaxError) as exc:
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
    return files, contents


def discover(root: Path, excluded: tuple[str, ...]) -> tuple[Snapshot, dict[str, str], list[str]]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository root must be a directory")
    diagnostics: list[str] = []
    candidates, revision, dirty = _inventory(root, excluded, diagnostics)
    files, contents = _capture_inputs(root, candidates, excluded, diagnostics)
    identity = {
        "root": str(root),
        "revision": revision,
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
