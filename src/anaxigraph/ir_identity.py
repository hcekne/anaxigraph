"""Path-derived module identity shared by analyzers and stored-fact serialization."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

__all__ = ["canonical_python_module", "module_identity_fields", "python_module_aliases"]


def module_identity_fields(path: str, language: str) -> dict[str, Any]:
    """Return the ``ModuleIdentity`` field values derived from a repository path."""

    normalized = path.replace("\\", "/").removeprefix("./")
    if language == "python":
        canonical = canonical_python_module(normalized)
        aliases = tuple(sorted(python_module_aliases(normalized)))
    else:
        pure = PurePosixPath(normalized)
        canonical = ".".join(pure.with_suffix("").parts)
        aliases = (canonical,) if canonical else ()
    return {
        "path": normalized,
        "language": language,
        "canonical_name": canonical,
        "package_name": canonical.split(".", 1)[0] if canonical else "",
        "aliases": aliases,
    }


def canonical_python_module(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def python_module_aliases(path: str) -> set[str]:
    canonical = canonical_python_module(path)
    parts = canonical.split(".")
    aliases = {canonical}
    if len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    if "src" in parts:
        aliases.add(".".join(parts[parts.index("src") + 1 :]))
    for marker in ("app", "lib", "server"):
        if marker in parts:
            aliases.add(".".join(parts[parts.index(marker) :]))
    return {alias for alias in aliases if alias}
