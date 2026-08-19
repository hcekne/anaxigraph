"""Language detection and source-file classification."""

from __future__ import annotations

from pathlib import PurePosixPath

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascriptreact",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "typescriptreact",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".html": "html",
    ".htm": "html",
    ".vue": "vue",
    ".svelte": "svelte",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".json": "json",
    ".jsonc": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".xml": "xml",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".tf": "terraform",
    ".hcl": "hcl",
}

SPECIAL_FILES = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "Makefile": "makefile",
    "Procfile": "text",
    "Gemfile": "ruby",
    "Rakefile": "ruby",
}

SOURCE_LANGUAGES = frozenset(
    {
        "python",
        "javascript",
        "javascriptreact",
        "typescript",
        "typescriptreact",
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
        "terraform",
    }
)


def detect_language(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.name in SPECIAL_FILES:
        return SPECIAL_FILES[pure.name]
    if pure.name.lower().startswith("dockerfile"):
        return "dockerfile"
    return LANGUAGE_BY_SUFFIX.get(pure.suffix.lower())


def artifact_type(path: str, language: str) -> str:
    normalized = path.lower()
    if any(part in normalized for part in ("/tests/", "/test/")) or normalized.startswith(
        ("tests/", "test/")
    ):
        return "test"
    if any(token in normalized for token in (".test.", ".spec.")):
        return "test"
    if language in {"markdown", "rst", "text"}:
        return "documentation"
    if language in {"yaml", "json", "toml", "ini", "dockerfile", "terraform", "hcl"}:
        return "configuration"
    if language in {"css", "scss", "sass", "less", "html"}:
        return "asset"
    return "source"
