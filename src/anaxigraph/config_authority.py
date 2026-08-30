"""Safe service configuration provenance and semantic-policy transport."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

_PRIVATE_SEMANTIC_FIELDS = frozenset({"command"})


def effective_semantic_policy(semantic: Any) -> dict[str, Any]:
    """Return the effective, non-secret policy needed by remote host executors."""

    policy = asdict(semantic)
    for field in _PRIVATE_SEMANTIC_FIELDS:
        policy.pop(field, None)
    return {"contract_version": "semantic-policy-v1", **policy}


def service_config_authority(
    repository: Path,
    target: Any | None,
    config: Any,
) -> dict[str, Any]:
    """Describe the policy source in service-side path terms without guessing a host path."""

    root = repository.expanduser().resolve()
    selected = (target.config_path if target else None) or config.config_path
    path = selected.expanduser().resolve() if selected else None
    repository_policy = (root / ".anaxigraph.yml").resolve()
    if path is None:
        source_kind = "service_defaults"
    elif path == repository_policy:
        source_kind = "repository_policy"
    else:
        source_kind = "external_registry_policy"
    return {
        "contract_version": "config-authority-v1",
        "authority": "service",
        "registry_key": target.key if target else None,
        "source_kind": source_kind,
        "service_config_path": str(path) if path else None,
        "path_namespace": "service",
        "sha256": _file_sha256(path),
    }


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
