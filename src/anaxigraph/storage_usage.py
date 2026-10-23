"""Bounded actual-byte measurements for the shared index and managed repository records."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

MAX_MANAGED_FILES = 64
MAX_MANAGED_ENTRIES = 256


def managed_record_usage(root):
    directory = Path(root) / "anaxigraph"
    if directory.is_symlink() or not directory.is_dir() or not _managed(directory):
        return {"bytes": 0, "files": 0, "managed": False}
    pending, entries, files, size = [directory], 0, 0, 0
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                entries += 1
                if entries > MAX_MANAGED_ENTRIES:
                    raise ValueError("Managed record exceeds the bounded directory-entry budget")
                item = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(item.st_mode):
                    raise ValueError("Managed record paths must not use symlinks")
                if stat.S_ISDIR(item.st_mode):
                    pending.append(Path(child.path))
                elif stat.S_ISREG(item.st_mode):
                    files += 1
                    size += item.st_size
                    if files > MAX_MANAGED_FILES:
                        raise ValueError("Managed record exceeds the 64-file storage budget")
    return {"bytes": size, "files": files, "managed": True}


def _managed(directory):
    for name in ("record.json", "manifest.json"):
        path = directory / name
        if path.is_symlink():
            return False
        try:
            if not path.is_file():
                continue
            if path.stat().st_size > 2_000_000:
                return False
            return str(json.loads(path.read_bytes()).get("format", "")).startswith(
                "anaxigraph-record-"
            )
        except (OSError, ValueError, AttributeError):
            return False
    return False


def registered_record_usage(connection, *, replacing_root=None, replacement_bytes=0):
    replaced = str(Path(replacing_root).absolute()) if replacing_root is not None else None
    roots = {
        str(Path(row[0]).absolute()) for row in connection.execute("SELECT path FROM repositories")
    }
    size, count = replacement_bytes, 0
    for root in roots:
        if root == replaced:
            continue
        usage = managed_record_usage(root)
        size += usage["bytes"]
        count += int(usage["managed"])
    return {"bytes": size, "records": count + int(replaced is not None)}


def index_file_usage(path):
    path = Path(path)
    return {
        name: candidate.stat().st_size if candidate.exists() else 0
        for name, candidate in (
            ("index_bytes", path),
            ("wal_bytes", Path(str(path) + "-wal")),
            ("shm_bytes", Path(str(path) + "-shm")),
        )
    }
