#!/usr/bin/env python3
"""Run Node's syntax parser for every supplied JavaScript module."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

JAVASCRIPT_SUFFIXES = frozenset({".js", ".cjs", ".mjs"})


def syntax_errors(paths: list[Path], *, node: str = "node") -> list[str]:
    executable = shutil.which(node)
    if executable is None:
        return [f"Node executable is unavailable: {node}"]
    errors = []
    for path in paths:
        if path.suffix.lower() not in JAVASCRIPT_SUFFIXES or not path.is_file():
            continue
        result = subprocess.run(
            [executable, "--check", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            errors.append(f"{path}: {(result.stderr or result.stdout).strip()}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    errors = syntax_errors(args.paths)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
