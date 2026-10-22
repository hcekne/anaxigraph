"""Recognize the reserved repository record without hiding unrelated source directories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RECORD_DIRECTORY = "anaxigraph"
RECORD_FORMAT = "anaxigraph-record-v2"
LEGACY_RECORD_FORMAT = "anaxigraph-record-v1"


def record_directory(root: Path) -> Path:
    return root / RECORD_DIRECTORY


def managed_record(root: Path) -> bool:
    if record_directory(root).is_symlink():
        return False
    path = record_directory(root) / "record.json"
    if not path.exists():
        path = record_directory(root) / "manifest.json"
    try:
        if path.is_symlink() or path.stat().st_size > 2_000_000:
            return False
        return str(json.loads(path.read_text()).get("format", "")).startswith("anaxigraph-record-")
    except (OSError, ValueError, AttributeError):
        return False


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode()


def record_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def source_pathspec(root: Path) -> tuple[str, ...]:
    return (".", ":(top,exclude)anaxigraph/**") if managed_record(root) else (".",)
