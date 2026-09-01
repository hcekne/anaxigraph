#!/usr/bin/env python3
"""Validate the shared Codex/Claude AnaxiGraph agent package."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

PLUGIN = Path("plugins/anaxigraph")
SKILL = PLUGIN / "skills/anaxigraph"
CORE_TOOLS = (
    "ANAXIGRAPH_REPOSITORIES",
    "ANAXIGRAPH_OVERVIEW",
    "ANAXIGRAPH_SEMANTIC_STATUS",
    "ANAXIGRAPH_SEARCH",
    "ANAXIGRAPH_FILE",
    "ANAXIGRAPH_GUIDE",
    "ANAXIGRAPH_IMPACT",
    "ANAXIGRAPH_FINDINGS",
    "ANAXIGRAPH_FINDING_CONTEXT",
    "ANAXIGRAPH_SCAN",
)


def validate_agent_package(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    version = _project_version(root, errors)
    skill_text, frontmatter = _skill(root, errors)
    _skill_contract(skill_text, frontmatter, errors)
    _openai_metadata(root, errors)
    _plugin_manifests(root, version, errors)
    _marketplaces(root, version, errors)
    _mcp(root, errors)
    _required_files(root, errors)
    return errors


def _project_version(root: Path, errors: list[str]) -> str:
    try:
        document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(document["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"cannot read project version: {exc}")
        return ""


def _skill(root: Path, errors: list[str]) -> tuple[str, dict[str, Any]]:
    path = root / SKILL / "SKILL.md"
    try:
        content = path.read_text(encoding="utf-8")
        _, frontmatter_text, _ = content.split("---", 2)
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            raise ValueError("frontmatter is not a mapping")
        return content, frontmatter
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(f"invalid {path.relative_to(root)}: {exc}")
        return "", {}


def _skill_contract(content: str, frontmatter: dict[str, Any], errors: list[str]) -> None:
    if frontmatter.get("name") != "anaxigraph":
        errors.append("skill name must be anaxigraph")
    if len(str(frontmatter.get("description") or "")) < 80:
        errors.append("skill description must contain concrete trigger context")
    if "TODO" in content:
        errors.append("skill contains a TODO placeholder")
    for tool in CORE_TOOLS:
        if tool not in content:
            errors.append(f"skill does not cover {tool}")
    for phrase in ("semantically_ready: true", "Do not edit repository source"):
        if phrase not in content:
            errors.append(f"skill is missing semantic safety phrase {phrase!r}")


def _openai_metadata(root: Path, errors: list[str]) -> None:
    path = root / SKILL / "agents/openai.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        interface = value["interface"]
        dependency = value["dependencies"]["tools"][0]
        if "$anaxigraph" not in interface["default_prompt"]:
            errors.append("OpenAI default prompt must invoke $anaxigraph")
        if dependency.get("value") != "anaxigraph":
            errors.append("OpenAI skill dependency must be the anaxigraph MCP server")
        for field in ("icon_small", "icon_large"):
            asset = (root / SKILL / interface[field]).resolve()
            if not asset.is_relative_to((root / SKILL).resolve()) or not asset.is_file():
                errors.append(f"OpenAI {field} must resolve inside the skill")
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"invalid {path.relative_to(root)}: {exc}")


def _plugin_manifests(root: Path, version: str, errors: list[str]) -> None:
    paths = (PLUGIN / ".codex-plugin/plugin.json", PLUGIN / ".claude-plugin/plugin.json")
    for path in paths:
        value = _json(root / path, errors)
        if value.get("name") != "anaxigraph":
            errors.append(f"{path} name must be anaxigraph")
        if value.get("version") != version:
            errors.append(f"{path} version must match project version {version}")
        if value.get("skills") != "./skills/" or value.get("mcpServers") != "./.mcp.json":
            errors.append(f"{path} must package the canonical skill and MCP definition")
    codex = _json(root / paths[0], errors)
    for field in ("composerIcon", "logo"):
        candidate = (root / PLUGIN / codex.get("interface", {}).get(field, "")).resolve()
        if not candidate.is_relative_to((root / PLUGIN).resolve()) or not candidate.is_file():
            errors.append(f"Codex plugin {field} must resolve inside the plugin")


def _marketplaces(root: Path, version: str, errors: list[str]) -> None:
    codex = _json(root / ".agents/plugins/marketplace.json", errors)
    claude = _json(root / ".claude-plugin/marketplace.json", errors)
    for label, value in (("Codex", codex), ("Claude", claude)):
        if value.get("name") != "anaxigraph":
            errors.append(f"{label} marketplace name must be anaxigraph")
        plugins = value.get("plugins") or []
        if len(plugins) != 1 or plugins[0].get("name") != "anaxigraph":
            errors.append(f"{label} marketplace must expose exactly the anaxigraph plugin")
    source = codex.get("plugins", [{}])[0].get("source", {}).get("path")
    if source != "./plugins/anaxigraph":
        errors.append("Codex marketplace must use the repository plugin path")
    claude_entry = claude.get("plugins", [{}])[0]
    if claude_entry.get("source") != "./plugins/anaxigraph":
        errors.append("Claude marketplace must use the repository plugin path")
    if claude_entry.get("version") != version:
        errors.append("Claude marketplace version must match the project version")


def _mcp(root: Path, errors: list[str]) -> None:
    value = _json(root / PLUGIN / ".mcp.json", errors)
    server = value.get("mcpServers", {}).get("anaxigraph", {})
    parsed = urlsplit(str(server.get("url") or ""))
    if server.get("type") != "http" or parsed.scheme != "http":
        errors.append("bundled AnaxiMCP must use the local HTTP transport")
    try:
        port = parsed.port
    except ValueError:
        port = None
    if parsed.hostname not in {"127.0.0.1", "localhost"} or port != 8765:
        errors.append("bundled AnaxiMCP must default to loopback port 8765")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        errors.append("bundled AnaxiMCP URL must not contain credentials, query, or fragment")


def _required_files(root: Path, errors: list[str]) -> None:
    for path in (PLUGIN / "LICENSE", SKILL / "assets/anaxigraph.svg"):
        if not (root / path).is_file():
            errors.append(f"agent package is missing {path}")


def _json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("document is not an object")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    errors = validate_agent_package(args.root)
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Agent package check: {len(errors)} error(s).")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
