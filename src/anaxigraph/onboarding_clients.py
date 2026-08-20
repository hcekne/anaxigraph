"""Safe, explicit MCP client configuration for first-run onboarding."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

CLIENTS = ("codex", "claude")
CONNECTION_SCOPES = ("user", "project")
_CODEX_SECTION = re.compile(r'^\s*\[mcp_servers(?:\.anaxigraph|\."anaxigraph")\]\s*(?:#.*)?$')
_TABLE_HEADER = re.compile(r"^\s*\[")
_URL_ASSIGNMENT = re.compile(r"^(\s*)url\s*=.*$")


def configure_client(
    client: str,
    *,
    scope: str,
    repository: Path,
    mcp_url: str,
    dry_run: bool = False,
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    client = _validate_choice(client, CLIENTS, "client")
    scope = _validate_choice(scope, CONNECTION_SCOPES, "connection scope")
    mcp_url = validate_mcp_url(mcp_url)
    path = client_config_path(
        client,
        scope=scope,
        repository=repository,
        home=home,
        environment=environment,
    )
    current = _read_config(path)
    updated = (
        _update_codex_config(current, mcp_url)
        if client == "codex"
        else _update_claude_config(current, mcp_url)
    )
    changed = updated != current
    existed = path.exists()
    action = _action(existed=existed, changed=changed, dry_run=dry_run)
    backup = None
    if changed and not dry_run:
        backup = _backup(path, private=scope == "user") if existed else None
        _write_atomic(path, updated, private=scope == "user")
    return {
        "client": client,
        "scope": scope,
        "path": str(path),
        "mcp_url": mcp_url,
        "action": action,
        "backup": str(backup) if backup else None,
        "restart_required": True,
        "project_trust_required": scope == "project",
        "command": connection_command(client, scope=scope, mcp_url=mcp_url),
    }


def client_connection_status(
    client: str,
    *,
    scope: str,
    repository: Path,
    expected_url: str,
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    client = _validate_choice(client, CLIENTS, "client")
    scope = _validate_choice(scope, CONNECTION_SCOPES, "connection scope")
    expected_url = validate_mcp_url(expected_url)
    path = client_config_path(
        client,
        scope=scope,
        repository=repository,
        home=home,
        environment=environment,
    )
    if not path.is_file():
        return _connection_report(client, scope, path, expected_url, None, "missing")
    try:
        content = path.read_text(encoding="utf-8")
        actual = (
            _codex_connection_url(content) if client == "codex" else _claude_connection_url(content)
        )
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        report = _connection_report(client, scope, path, expected_url, None, "invalid")
        report["message"] = str(exc)
        return report
    status = "configured" if actual == expected_url else "mismatch"
    return _connection_report(client, scope, path, expected_url, actual, status)


def client_config_path(
    client: str,
    *,
    scope: str,
    repository: Path,
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    repository = repository.expanduser().resolve()
    if scope == "project":
        return repository / (".codex/config.toml" if client == "codex" else ".mcp.json")
    environment = os.environ if environment is None else environment
    home = Path.home() if home is None else home.expanduser().resolve()
    if client == "codex":
        configured = environment.get("CODEX_HOME")
        codex_root = Path(configured).expanduser() if configured else home / ".codex"
        return codex_root / "config.toml"
    return home / ".claude.json"


def connection_command(client: str, *, scope: str, mcp_url: str) -> str:
    if client == "claude":
        return f"claude mcp add --transport http --scope {scope} anaxigraph {mcp_url}"
    if scope == "user":
        return f"codex mcp add anaxigraph --url {mcp_url}"
    return "Add [mcp_servers.anaxigraph] to the trusted project's .codex/config.toml"


def validate_mcp_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("MCP URL must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("MCP URL must not contain credentials or a fragment")
    return normalized


def _read_config(path: Path) -> str:
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlinked client configuration: {path}")
    if not path.exists():
        return ""
    if not path.is_file():
        raise ValueError(f"Client configuration is not a regular file: {path}")
    return path.read_text(encoding="utf-8")


def _update_codex_config(content: str, mcp_url: str) -> str:
    parsed = tomllib.loads(content) if content.strip() else {}
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("Codex mcp_servers must be a TOML table")
    existing = servers.get("anaxigraph")
    if isinstance(existing, dict) and existing.get("url") == mcp_url:
        return content
    lines = content.splitlines(keepends=True)
    start = next((index for index, line in enumerate(lines) if _CODEX_SECTION.match(line)), None)
    quoted_url = json.dumps(mcp_url)
    if start is None:
        if existing is not None:
            raise ValueError(
                "Existing Codex AnaxiGraph config uses an unsupported inline representation"
            )
        prefix = content.rstrip()
        separator = "\n\n" if prefix else ""
        updated = (
            f"{prefix}{separator}# Added by AnaxiGraph; safe to edit.\n"
            f"[mcp_servers.anaxigraph]\nurl = {quoted_url}\n"
        )
    else:
        end = next(
            (index for index in range(start + 1, len(lines)) if _TABLE_HEADER.match(lines[index])),
            len(lines),
        )
        url_index = next(
            (index for index in range(start + 1, end) if _URL_ASSIGNMENT.match(lines[index])),
            None,
        )
        if url_index is None:
            lines.insert(start + 1, f"url = {quoted_url}\n")
        else:
            indent = _URL_ASSIGNMENT.match(lines[url_index]).group(1)  # type: ignore[union-attr]
            lines[url_index] = f"{indent}url = {quoted_url}\n"
        updated = "".join(lines)
    verified = tomllib.loads(updated)
    if verified.get("mcp_servers", {}).get("anaxigraph", {}).get("url") != mcp_url:
        raise ValueError("Generated Codex configuration did not preserve the requested MCP URL")
    return updated


def _update_claude_config(content: str, mcp_url: str) -> str:
    parsed = json.loads(content) if content.strip() else {}
    if not isinstance(parsed, dict):
        raise ValueError("Claude configuration must contain a JSON object")
    servers = parsed.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("Claude mcpServers must contain a JSON object")
    existing = servers.get("anaxigraph")
    if (
        isinstance(existing, dict)
        and existing.get("url") == mcp_url
        and existing.get("type") in {"http", "streamable-http"}
    ):
        return content
    entry = dict(existing) if isinstance(existing, dict) else {}
    entry.update({"type": "http", "url": mcp_url})
    servers["anaxigraph"] = entry
    return json.dumps(parsed, indent=2, sort_keys=False) + "\n"


def _codex_connection_url(content: str) -> str | None:
    parsed = tomllib.loads(content) if content.strip() else {}
    value = parsed.get("mcp_servers", {}).get("anaxigraph", {})
    return str(value.get("url")) if isinstance(value, dict) and value.get("url") else None


def _claude_connection_url(content: str) -> str | None:
    parsed = json.loads(content) if content.strip() else {}
    value = parsed.get("mcpServers", {}).get("anaxigraph", {})
    return str(value.get("url")) if isinstance(value, dict) and value.get("url") else None


def _backup(path: Path, *, private: bool) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.anaxigraph-{timestamp}.bak")
    shutil.copy2(path, backup)
    if private:
        backup.chmod(0o600)
    return backup


def _write_atomic(path: Path, content: str, *, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600 if private else ((path.stat().st_mode & 0o777) if path.exists() else 0o644)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.anaxigraph-",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_name = handle.name
        temporary = Path(temporary_name)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _action(*, existed: bool, changed: bool, dry_run: bool) -> str:
    if not changed:
        return "unchanged"
    if dry_run:
        return "would_update" if existed else "would_create"
    return "updated" if existed else "created"


def _connection_report(
    client: str,
    scope: str,
    path: Path,
    expected: str,
    actual: str | None,
    status: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "client": client,
        "scope": scope,
        "path": str(path),
        "expected_url": expected,
        "actual_url": actual,
    }


def _validate_choice(value: str, choices: tuple[str, ...], label: str) -> str:
    normalized = value.strip().lower()
    if normalized not in choices:
        raise ValueError(f"{label} must be one of: {', '.join(choices)}")
    return normalized
