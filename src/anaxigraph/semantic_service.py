"""Discover and prepare the authoritative AnaxiGraph service for a checkout."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.config import load_config
from anaxigraph.onboarding_clients import validate_mcp_url
from anaxigraph.pattern_candidate_query import PatternCandidateQuery
from anaxigraph.pattern_query import PatternEvaluationQuery

DEFAULT_SERVICE_URL = "http://127.0.0.1:8765"


@dataclass(frozen=True, slots=True)
class SemanticServiceTarget:
    base_url: str
    repository_id: int
    repository_name: str
    repository_path: str

    @property
    def mcp_url(self) -> str:
        return f"{self.base_url}/mcp"

    def identity(self) -> dict[str, Any]:
        return {
            "authority": "service",
            "service_url": self.base_url,
            "mcp_url": self.mcp_url,
            "repository_id": self.repository_id,
            "repository_name": self.repository_name,
            "repository_path": self.repository_path,
        }


def discover_semantic_service(
    repository: Path,
    *,
    explicit_url: str | None = None,
    timeout: float = 0.75,
) -> SemanticServiceTarget | None:
    """Match a running service by checkout path or canonical Git remote identity."""

    configured = explicit_url or os.environ.get("ANAXIGRAPH_SERVICE_URL")
    base_url = _base_url(configured or DEFAULT_SERVICE_URL)
    try:
        rows = _request_json(f"{base_url}/api/repositories", timeout=timeout)
    except (OSError, ValueError) as exc:
        if configured:
            raise ValueError(f"AnaxiGraph service is unavailable at {base_url}: {exc}") from exc
        return None
    if not isinstance(rows, list):
        raise ValueError(f"AnaxiGraph service at {base_url} returned an invalid repository list")
    matches = _matching_rows(repository.expanduser().resolve(), rows)
    if len(matches) == 1:
        row = matches[0]
        return SemanticServiceTarget(
            base_url=base_url,
            repository_id=int(row["id"]),
            repository_name=str(row.get("name") or ""),
            repository_path=str(row.get("path") or ""),
        )
    if len(matches) > 1:
        identifiers = ", ".join(str(row.get("id")) for row in matches)
        raise ValueError(
            f"Service {base_url} has multiple indexes for this Git identity ({identifiers})"
        )
    if configured:
        raise ValueError(f"Service {base_url} does not index {repository.expanduser().resolve()}")
    return None


def prepare_semantic_service(
    target: SemanticServiceTarget,
    *,
    force: bool,
    retry_failed: bool,
    timeout: float = 300,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "repository_id": target.repository_id,
            "force": str(force).lower(),
            "retry_failed": str(retry_failed).lower(),
            "wait": "true",
        }
    )
    value = _request_json_with_retries(
        f"{target.base_url}/api/semantic/refresh?{query}",
        method="POST",
        timeout=timeout,
    )
    if not isinstance(value, dict):
        raise ValueError("AnaxiGraph service returned an invalid semantic preparation result")
    return value


def _request_json_with_retries(url: str, **options: Any) -> Any:
    for attempt in range(4):
        try:
            return _request_json(url, **options)
        except (OSError, ValueError) as exc:
            transient = isinstance(exc, OSError) or any(
                marker in str(exc)
                for marker in ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")
            )
            if not transient or attempt == 3:
                raise
            time.sleep(0.25 * (2**attempt))
    raise RuntimeError("Unreachable semantic service retry state")


def service_semantic_status(
    target: SemanticServiceTarget, *, timeout: float = 10
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"repository_id": target.repository_id})
    value = _request_json(f"{target.base_url}/api/semantic?{query}", timeout=timeout)
    if not isinstance(value, dict):
        raise ValueError("AnaxiGraph service returned an invalid semantic status")
    return value


def service_pattern_evaluations(
    target: SemanticServiceTarget,
    request: PatternEvaluationQuery,
    *,
    snapshot_id: int | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    return _service_pattern_projection(
        target,
        "/api/patterns",
        {
            **request.filters(),
            "limit": request.limit,
            "offset": request.offset,
        },
        snapshot_id=snapshot_id,
        timeout=timeout,
    )


def service_pattern_candidates(
    target: SemanticServiceTarget,
    request: PatternCandidateQuery,
    *,
    snapshot_id: int | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    return _service_pattern_projection(
        target,
        "/api/patterns/candidates",
        {**request.filters(), "limit": request.limit, "offset": request.offset},
        snapshot_id=snapshot_id,
        timeout=timeout,
    )


def _service_pattern_projection(
    target: SemanticServiceTarget,
    path: str,
    parameters: dict[str, Any],
    *,
    snapshot_id: int | None,
    timeout: float,
) -> dict[str, Any]:
    values = {
        "repository_id": target.repository_id,
        "snapshot_id": snapshot_id,
        **parameters,
    }
    query = urllib.parse.urlencode(
        {key: value for key, value in values.items() if value not in (None, "")}
    )
    value = _request_json(f"{target.base_url}{path}?{query}", timeout=timeout)
    if not isinstance(value, dict):
        raise ValueError("AnaxiGraph service returned an invalid pattern projection")
    return value


def _matching_rows(repository: Path, rows: list[Any]) -> list[dict[str, Any]]:
    candidates = [row for row in rows if isinstance(row, dict) and row.get("id") is not None]
    direct = [
        row
        for row in candidates
        if row.get("path") and Path(str(row["path"])).expanduser().resolve() == repository
    ]
    if direct:
        return direct
    local_remote = _canonical_remote(git.metadata(repository).remote_url)
    if local_remote:
        remote = [
            row
            for row in candidates
            if _canonical_remote(str(row.get("remote_url") or "")) == local_remote
        ]
        if remote:
            return remote
    project_name = str(load_config(repository).project_name or "").strip().casefold()
    named = [
        row for row in candidates if str(row.get("name") or "").strip().casefold() == project_name
    ]
    return named if project_name else []


def _canonical_remote(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw and "@" in raw and ":" in raw:
        user_host, path = raw.split(":", 1)
        host = user_host.rsplit("@", 1)[-1]
        raw = f"ssh://{host}/{path}"
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme:
        host = (parsed.hostname or "").casefold()
        path = parsed.path
        return f"{host}/{path.strip('/').removesuffix('.git')}".casefold()
    return raw.rstrip("/").removesuffix(".git").casefold()


def _base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    if raw.endswith("/mcp"):
        raw = raw[:-4]
    validate_mcp_url(f"{raw}/mcp")
    return raw


def _request_json(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 10,
) -> Any:
    request = urllib.request.Request(
        url,
        data=b"" if method == "POST" else None,
        headers={"Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1_000]
        raise ValueError(f"AnaxiGraph service returned HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OSError(str(exc)) from exc
