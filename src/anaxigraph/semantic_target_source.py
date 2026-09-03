"""One guard for reading a planned semantic target from the mounted tree.

Agent-supplied job identifiers name a file the planner saw earlier. Before a request builder
embeds that file's bytes, two facts must hold: the path still names a regular file inside the
mounted tree, and its bytes still match the raw hash saved when the job was planned. Both
semantic request builders (intrinsic and pattern) call these helpers with their own agent-facing
messages, so the trust boundary between a job identifier and the filesystem lives in one place.

Symlink policy: the candidate is resolved before the containment check, so a symlink inside the
tree that points outside it fails ``is_relative_to`` and is refused, while a symlink that stays
inside the tree is read through to its target and the saved-hash comparison then decides.
Discovery never plans a symlinked file (``history_discovery._read_source`` refuses them and
``_walk_files`` prunes symlinked directories), so a planned target is a symlink only when one
replaced it after planning. A resolved path is never itself a symlink, so no ``is_symlink`` check
appears here. ``history_discovery._read_source`` keeps its own unresolved-path policy (``None``
instead of an exception, git revisions, ``max_file_bytes``) and is deliberately not served by
this module.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from anaxigraph.semantic_graph import SupersededSemanticJob


def read_mounted_source(root: Path, path: str, *, missing: str) -> bytes:
    """Return the bytes of ``path`` when it resolves to a regular file inside ``root``.

    ``root`` must already be resolved; every caller passes
    ``Path(repository).expanduser().resolve()``. Raises ``SupersededSemanticJob(missing)`` when
    the resolved candidate escapes ``root`` or is not a regular file.
    """
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise SupersededSemanticJob(missing)
    return candidate.read_bytes()


def require_unchanged_source(raw: bytes, version: Mapping[str, Any] | None, *, changed: str) -> str:
    """Return the SHA-256 hex digest of ``raw`` when it matches the planned ``version``.

    ``version`` is the module row saved at planning time (its ``raw_hash`` column) or ``None``
    when the snapshot no longer knows the artifact. Raises ``SupersededSemanticJob(changed)``
    when the version is missing or its saved hash differs from the current bytes.
    """
    raw_hash = hashlib.sha256(raw).hexdigest()
    if version is None or version["raw_hash"] != raw_hash:
        raise SupersededSemanticJob(changed)
    return raw_hash
