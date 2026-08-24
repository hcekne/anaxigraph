"""Safe fallback analysis for configuration, documentation, and other text."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath

import yaml

from anaxigraph.analyzer_capabilities import declare_capabilities
from anaxigraph.ir import module_identity, resolver_context
from anaxigraph.models import Dependency, FileAnalysis

_CSS_IMPORT = re.compile(r"@(?:import|use|forward)\s+(?:url\()?['\"]([^'\"]+)['\"]")
_MARKDOWN_LINK = re.compile(r"\[[^]]+\]\((?!https?://|mailto:|#)([^)#?]+)")


class TextAnalyzer:
    name = "builtin-text"
    version = "1"
    languages = frozenset(
        {
            "css",
            "scss",
            "sass",
            "less",
            "html",
            "vue",
            "svelte",
            "go",
            "rust",
            "java",
            "kotlin",
            "ruby",
            "php",
            "csharp",
            "c",
            "cpp",
            "swift",
            "shell",
            "sql",
            "graphql",
            "protobuf",
            "json",
            "yaml",
            "toml",
            "ini",
            "xml",
            "markdown",
            "rst",
            "text",
            "terraform",
            "hcl",
            "dockerfile",
            "makefile",
        }
    )
    capabilities = declare_capabilities(
        name,
        version,
        "inventory",
        deep=("module_identity",),
        heuristic=("complexity", "imports", "module_documentation"),
        limitations=(
            "Language-specific symbols, calls, types, and control flow are not extracted.",
            "Import evidence is opportunistic for CSS and Markdown rather than universal.",
        ),
    )

    def analyze(self, path: str, content: str) -> FileAnalysis:
        language = _language_for_path(path)
        identity = module_identity(path, language)
        lines = content.splitlines()
        comment_prefixes = _comment_prefixes(language)
        comment_lines = sum(1 for line in lines if line.strip().startswith(comment_prefixes))
        loc = sum(
            1 for line in lines if line.strip() and not line.strip().startswith(comment_prefixes)
        )
        normalized, parse_error = _normalized(language, content)
        dependencies = _dependencies(language, content)
        summary = _summary(path, language, lines)
        complexity = 1 + sum(
            len(re.findall(pattern, content, flags=re.IGNORECASE | re.MULTILINE))
            for pattern in _complexity_patterns(language)
        )
        return FileAnalysis(
            language=language,
            structural_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            lines_of_code=loc,
            comment_lines=comment_lines,
            complexity=max(1, complexity),
            summary=summary,
            responsibilities=[summary],
            dependencies=dependencies,
            parse_error=parse_error,
            analyzer=self.name,
            module_identity=identity,
            parse_status="parse_error" if parse_error else "fallback",
            analyzer_version=self.version,
            resolver_context=resolver_context(identity),
            analyzer_capabilities=self.capabilities,
        )


def _language_for_path(path: str) -> str:
    from anaxigraph.languages import detect_language

    return detect_language(path) or "text"


def _comment_prefixes(language: str) -> tuple[str, ...]:
    if language in {"python", "shell", "yaml", "toml", "ini", "makefile", "dockerfile"}:
        return ("#",)
    if language in {"sql"}:
        return ("--",)
    if language in {"markdown", "rst", "text", "json", "xml", "html"}:
        return ("<!--",)
    return ("//", "/*", "*")


def _normalized(language: str, content: str) -> tuple[str, str | None]:
    try:
        if language == "json":
            try:
                value = json.loads(content)
            except json.JSONDecodeError:
                value = json.loads(_jsonc_to_json(content))
            return json.dumps(value, sort_keys=True, separators=(",", ":")), None
        if language == "yaml":
            value = yaml.safe_load(content)
            return (
                json.dumps(
                    _string_keyed(value),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
                None,
            )
    except (ValueError, TypeError, yaml.YAMLError) as exc:
        parse_error = f"{type(exc).__name__}: {exc}"
    else:
        parse_error = None
    normalized_lines = [line.rstrip() for line in content.replace("\r\n", "\n").split("\n")]
    return "\n".join(normalized_lines).strip(), parse_error


def _jsonc_to_json(content: str) -> str:
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(content):
        char = content[index]
        following = content[index + 1] if index + 1 < len(content) else ""
        if state == "code":
            if char in {'"', "'"}:
                state = "string"
                quote = char
                output.append(char)
            elif char == "/" and following == "/":
                state = "line_comment"
                index += 1
            elif char == "/" and following == "*":
                state = "block_comment"
                index += 1
            else:
                output.append(char)
        elif state == "string":
            output.append(char)
            if char == "\\" and index + 1 < len(content):
                index += 1
                output.append(content[index])
            elif char == quote:
                state = "code"
        elif state == "line_comment":
            if char == "\n":
                output.append(char)
                state = "code"
        elif state == "block_comment" and char == "*" and following == "/":
            state = "code"
            index += 1
        index += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(output))


def _string_keyed(value):
    if isinstance(value, dict):
        return {str(key): _string_keyed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_string_keyed(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_string_keyed(item) for item in value)
    return value


def _dependencies(language: str, content: str) -> list[Dependency]:
    dependencies: list[Dependency] = []
    if language in {"css", "scss", "sass", "less"}:
        for match in _CSS_IMPORT.finditer(content):
            dependencies.append(
                Dependency(
                    target=match.group(1),
                    line=content.count("\n", 0, match.start()) + 1,
                    evidence=match.group(0)[:300],
                )
            )
    if language == "markdown":
        for match in _MARKDOWN_LINK.finditer(content):
            dependencies.append(
                Dependency(
                    target=match.group(1),
                    relationship_type="references",
                    line=content.count("\n", 0, match.start()) + 1,
                    evidence=match.group(0)[:300],
                    confidence=0.95,
                )
            )
    return dependencies


def _summary(path: str, language: str, lines: list[str]) -> str:
    for line in lines[:80]:
        stripped = line.strip()
        if language == "markdown" and stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:500]
        if stripped and not stripped.startswith(_comment_prefixes(language)):
            break
    name = PurePosixPath(path).name
    return f"{language.title()} {name}"


def _complexity_patterns(language: str) -> tuple[str, ...]:
    if language == "sql":
        return (r"\bJOIN\b", r"\bUNION\b", r"\bCASE\b")
    if language in {"terraform", "hcl"}:
        return (r"\bfor_each\b", r"\bcount\b", r"\bdynamic\b")
    if language in {"shell", "makefile", "dockerfile"}:
        return (r"\bif\b", r"\bfor\b", r"\bwhile\b", r"&&", r"\|\|")
    return ()
