"""Discover and prepare the authoritative AnaxiGraph service for a checkout."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anaxigraph import git
from anaxigraph.config import SemanticConfig, load_config, semantic_config_from_mapping
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
    config_authority: dict[str, Any] = field(default_factory=dict)
    semantic_policy: dict[str, Any] = field(default_factory=dict)

    @property
    def mcp_url(self) -> str:
        return f"{self.base_url}/mcp"

    @property
    def executor_mcp_url(self) -> str:
        return f"{self.base_url}/executor/mcp"

    def identity(self) -> dict[str, Any]:
        return {
            "authority": "service",
            "service_url": self.base_url,
            "mcp_url": self.mcp_url,
            "executor_mcp_url": self.executor_mcp_url,
            "repository_id": self.repository_id,
            "repository_name": self.repository_name,
            "repository_path": self.repository_path,
            "config_authority": self.config_authority,
            "semantic_policy": self.semantic_policy,
        }

    def semantic_config(self) -> SemanticConfig:
        if not self.semantic_policy:
            raise ValueError(
                f"AnaxiGraph service at {self.base_url} did not expose its effective semantic "
                "policy; upgrade or restart the service before running understand"
            )
        return semantic_config_from_mapping(self.semantic_policy)

    def config_label(self) -> str:
        path = self.config_authority.get("service_config_path") or "service defaults"
        key = self.config_authority.get("registry_key")
        return f"{path} (registry key {key!r})" if key else str(path)


def discover_semantic_service(
    repository: Path,
    *,
    explicit_url: str | None = None,
    timeout: float = 2.0,
) -> SemanticServiceTarget | None:
    """Match the service authoritative for this checkout without ambiguous fallback."""

    configured = explicit_url or os.environ.get("ANAXIGRAPH_SERVICE_URL")
    base_url = _base_url(configured or DEFAULT_SERVICE_URL)
    rows = _service_inventory(base_url, timeout, required=bool(configured))
    return _matching_target(repository, base_url, rows, required=bool(configured))


def _service_inventory(
    base_url: str, timeout: float, *, required: bool
) -> list[dict[str, Any]] | None:
    try:
        rows = _discovery_inventory(base_url, timeout)
    except ConnectionRefusedError as exc:
        if required:
            raise ValueError(f"AnaxiGraph service is unavailable at {base_url}: {exc}") from exc
        return None
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"AnaxiGraph service at {base_url} did not return its repository inventory; "
            "refusing local-index fallback because the service may be busy: "
            f"{exc}"
        ) from exc
    if not isinstance(rows, list):
        raise ValueError(f"AnaxiGraph service at {base_url} returned an invalid repository list")
    return rows


def _matching_target(
    repository: Path,
    base_url: str,
    rows: list[dict[str, Any]] | None,
    *,
    required: bool,
) -> SemanticServiceTarget | None:
    if rows is None:
        return None
    matches = _matching_rows(repository.expanduser().resolve(), rows)
    if len(matches) == 1:
        row = matches[0]
        return SemanticServiceTarget(
            base_url=base_url,
            repository_id=int(row["id"]),
            repository_name=str(row.get("name") or ""),
            repository_path=str(row.get("path") or ""),
            config_authority=dict(row.get("config_authority") or {}),
            semantic_policy=dict(row.get("semantic_policy") or {}),
        )
    if len(matches) > 1:
        identifiers = ", ".join(str(row.get("id")) for row in matches)
        raise ValueError(
            f"Service {base_url} has multiple indexes for this Git identity ({identifiers})"
        )
    if required:
        raise ValueError(f"Service {base_url} does not index {repository.expanduser().resolve()}")
    return None


def _discovery_inventory(base_url: str, timeout: float) -> Any:
    url = f"{base_url}/api/repositories"
    for attempt in range(3):
        try:
            return _request_json(url, timeout=timeout)
        except ConnectionRefusedError:
            raise
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(0.1 * (2**attempt))
    raise RuntimeError("Unreachable service-discovery retry state")


def prepare_semantic_service(
    target: SemanticServiceTarget,
    *,
    force: bool,
    retry_failed: bool,
    timeout: float = 30,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "repository_id": target.repository_id,
            "force": str(force).lower(),
            "retry_failed": str(retry_failed).lower(),
        }
    )
    value = _request_json_with_retries(
        f"{target.base_url}/api/semantic/prepare?{query}",
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


def service_architecture_guidance(
    target: SemanticServiceTarget,
    *,
    goal: str,
    intent: str = "build",
    focus: str = "",
    timeout: float = 30,
) -> dict[str, Any]:
    return _service_agent_request(
        target,
        "/api/guidance",
        {
            "goal": goal,
            "intent": intent,
            "focus": focus,
            "repository_id": target.repository_id,
        },
        timeout=timeout,
    )


def service_fresh_eyes_review(
    target: SemanticServiceTarget,
    *,
    start: bool = False,
    proposal_count: int = 2,
    retry_failed: bool = False,
    restart: bool = False,
    timeout: float = 30,
) -> dict[str, Any]:
    if start or restart:
        return _service_agent_request(
            target,
            "/api/fresh-eyes",
            {
                "proposal_count": proposal_count,
                "retry_failed": retry_failed,
                "restart": restart,
                "repository_id": target.repository_id,
            },
            timeout=timeout,
        )
    query = urllib.parse.urlencode({"repository_id": target.repository_id})
    value = _request_json(f"{target.base_url}/api/fresh-eyes?{query}", timeout=timeout)
    if not isinstance(value, dict):
        raise ValueError("AnaxiGraph service returned an invalid fresh-eyes review")
    return value


def service_architecture_reassessment(
    target: SemanticServiceTarget,
    *,
    from_snapshot_id: int | None = None,
    goal: str = "",
    timeout: float = 30,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {"repository_id": target.repository_id}
    if from_snapshot_id is not None:
        parameters["from_snapshot_id"] = from_snapshot_id
    if goal.strip():
        parameters["goal"] = goal.strip()
    query = urllib.parse.urlencode(parameters)
    value = _request_json(f"{target.base_url}/api/reassessment?{query}", timeout=timeout)
    if not isinstance(value, dict):
        raise ValueError("AnaxiGraph service returned an invalid architecture reassessment")
    return value


def service_impact(
    target: SemanticServiceTarget,
    *,
    requested_target: str,
    timeout: float = 30,
) -> dict[str, Any]:
    return _service_agent_request(
        target,
        "/api/impact",
        {
            "target": requested_target,
            "repository_id": target.repository_id,
        },
        timeout=timeout,
    )


def _service_agent_request(
    target: SemanticServiceTarget,
    path: str,
    body: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    value = _request_json(f"{target.base_url}{path}", method="POST", timeout=timeout, body=body)
    if not isinstance(value, dict):
        raise ValueError("AnaxiGraph service returned an invalid coding-context result")
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
    body: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if method == "POST" and data is None:
        data = b""
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1_000]
        raise ValueError(f"AnaxiGraph service returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        if _connection_refused(exc.reason):
            raise ConnectionRefusedError(str(exc)) from exc
        raise OSError(str(exc)) from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise OSError(str(exc)) from exc


def _connection_refused(reason: Any) -> bool:
    return isinstance(reason, ConnectionRefusedError) or getattr(reason, "errno", None) in {
        61,
        111,
        10061,
    }
