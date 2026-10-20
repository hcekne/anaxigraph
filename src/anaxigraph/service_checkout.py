"""Match a service to an exact checkout and register allowed linked worktrees."""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path
from typing import Any

import anaxigraph.git as git


def matching_checkouts(repository: Path, rows: list[Any]) -> list[dict[str, Any]]:
    root = repository.expanduser().resolve()
    candidates = [row for row in rows if isinstance(row, dict) and row.get("id") is not None]
    direct = [
        row
        for row in candidates
        if row.get("path") and Path(row["path"]).expanduser().resolve() == root
    ]
    if direct:
        return direct
    identity, local = git.checkout_identity(root), git.metadata(root)
    return [row for row in candidates if _same_mounted_checkout(identity, local, row)]


def _same_mounted_checkout(identity: Any, local: Any, row: dict[str, Any]) -> bool:
    # An accessible different path is a sibling checkout, never a container path alias.
    if Path(str(row.get("path") or "")).is_dir():
        return False
    served = (row.get("map_status") or {}).get("checkout") or {}
    remote = canonical_remote(getattr(local, "remote_url", None))
    if not remote or remote != canonical_remote(row.get("remote_url")):
        return False
    return bool(
        served.get("worktree_key") == identity.get("worktree_key")
        and served.get("commit_sha") == getattr(local, "commit_sha", None)
        and served.get("branch") == getattr(local, "branch", None)
        and served.get("working_tree_fingerprint") is not None
        and served["working_tree_fingerprint"] == getattr(local, "working_tree_fingerprint", None)
    )


def register_worktree(
    repository: Path, base_url: str, request: Any, timeout: float
) -> list[Any] | None:
    """Ask the existing scan route to admit only a registered repository's linked checkout."""
    root = repository.expanduser().resolve()
    if not git.checkout_identity(root)["is_worktree"]:
        return None
    query = urllib.parse.urlencode({"repository_path": str(root)})
    try:
        scan = request(f"{base_url}/api/scan?{query}", method="POST", timeout=timeout)
    except ValueError as exc:
        if any(f"HTTP {code}" in str(exc) for code in (400, 403, 404, 422)):
            return None
        raise
    if not isinstance(scan, dict) or not scan.get("repository_id"):
        return None
    identifier = scan["repository_id"]
    deadline = time.monotonic() + 30
    while scan.get("active"):
        if time.monotonic() >= deadline:
            raise ValueError(
                f"Worktree {root} is registered and scanning; retry after the scan completes."
            )
        time.sleep(0.05)
        scan = request(f"{base_url}/api/scan?repository_id={identifier}", timeout=timeout)
    if scan.get("status") not in {"complete", "completed"}:
        raise ValueError(
            f"Worktree scan could not finish: {scan.get('error') or scan.get('status')}"
        )
    return request(f"{base_url}/api/repositories", timeout=timeout)


def canonical_remote(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw and "@" in raw and ":" in raw:
        user_host, path = raw.split(":", 1)
        raw = f"ssh://{user_host.rsplit('@', 1)[-1]}/{path}"
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme:
        return f"{(parsed.hostname or '').casefold()}/{parsed.path.strip('/').removesuffix('.git')}".casefold()
    return raw.rstrip("/").removesuffix(".git").casefold()
