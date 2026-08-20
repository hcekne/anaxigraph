#!/usr/bin/env python3
"""Prevent generated state, indexes, and likely credentials from entering Git."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path

FORBIDDEN_PATTERNS = (
    ".env",
    "**/.env",
    ".pypirc",
    "**/.pypirc",
    "*.db",
    "**/*.db",
    "*.db-shm",
    "**/*.db-shm",
    "*.db-wal",
    "**/*.db-wal",
    "*.pem",
    "**/*.pem",
    "**/id_rsa",
    "**/id_ed25519",
    ".venv/**",
    ".venv-*/**",
    "node_modules/**",
    "build/**",
    "dist/**",
    "__pycache__/**",
    "**/__pycache__/**",
    ".anaxigraph/**",
)

ALLOWED_PATHS = frozenset({".env.example"})


def forbidden_paths(paths: list[str]) -> list[str]:
    return sorted(
        {
            path.replace("\\", "/")
            for path in paths
            if path.replace("\\", "/") not in ALLOWED_PATHS
            and any(
                fnmatch.fnmatchcase(path.replace("\\", "/"), pattern)
                for pattern in FORBIDDEN_PATTERNS
            )
        }
    )


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode(errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--all-tracked", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = _tracked_files(args.root.resolve()) if args.all_tracked else args.paths
    forbidden = forbidden_paths(paths)
    if args.json:
        print(json.dumps({"errors": len(forbidden), "forbidden": forbidden}))
    elif forbidden:
        print("Forbidden generated, index, or credential-like paths:")
        for path in forbidden:
            print(f"  {path}")
    return 1 if forbidden else 0


if __name__ == "__main__":
    raise SystemExit(main())
