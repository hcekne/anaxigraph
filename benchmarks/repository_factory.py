"""Deterministic repositories used by performance and correctness benchmarks."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

DEFAULT_SEED = 20_260_820
DEFAULT_FILE_COUNT = 3_000
DEFAULT_COMMITS = 8

_SEED_FILES = {
    "src/sample/analyzers/__init__.py": (
        '"""Language analyzer strategies."""\n\n'
        "from .base import LanguageAnalyzer\n"
        "from .javascript import JavaScriptAnalyzer\n"
        "from .python import PythonAnalyzer\n"
        "from .text import TextAnalyzer\n\n"
        '__all__ = ["LanguageAnalyzer", "JavaScriptAnalyzer", "PythonAnalyzer", "TextAnalyzer"]\n'
    ),
    "src/sample/analyzers/base.py": (
        '"""Contract shared by every language analyzer."""\n\n'
        "from typing import Protocol\n\n"
        "class LanguageAnalyzer(Protocol):\n"
        "    def analyze(self, path: str, content: str) -> dict[str, object]: ...\n"
    ),
    "src/sample/analyzers/javascript.py": (
        '"""JavaScript and TypeScript analyzer."""\n\n'
        "class JavaScriptAnalyzer:\n"
        '    languages = frozenset({"javascript", "typescript"})\n\n'
        "    def analyze(self, path: str, content: str) -> dict[str, object]:\n"
        '        return {"path": path, "lines": len(content.splitlines())}\n'
    ),
    "src/sample/analyzers/python.py": (
        '"""Python syntax analyzer."""\n\n'
        "class PythonAnalyzer:\n"
        '    languages = frozenset({"python"})\n\n'
        "    def analyze(self, path: str, content: str) -> dict[str, object]:\n"
        '        return {"path": path, "symbols": content.count("def ")}\n'
    ),
    "src/sample/analyzers/text.py": (
        '"""Fallback analyzer for languages without a parser."""\n\n'
        "class TextAnalyzer:\n"
        '    languages = frozenset({"go", "rust", "java", "text"})\n\n'
        "    def analyze(self, path: str, content: str) -> dict[str, object]:\n"
        '        return {"path": path, "bytes": len(content.encode())}\n'
    ),
    "src/sample/languages.py": (
        '"""Maps file suffixes to language analyzer names."""\n\n'
        'LANGUAGES = {".py": "python", ".js": "javascript", ".ts": "typescript"}\n\n'
        "def detect_language(path: str) -> str | None:\n"
        "    return next((name for suffix, name in LANGUAGES.items() if path.endswith(suffix)), None)\n"
    ),
    "src/sample/service.py": (
        '"""Selects an analyzer and exposes the analysis use case."""\n\n'
        "from sample.languages import detect_language\n"
        "from sample.analyzers import JavaScriptAnalyzer, PythonAnalyzer, TextAnalyzer\n\n"
        "def analyze_file(path: str, content: str) -> dict[str, object]:\n"
        "    language = detect_language(path)\n"
        '    analyzer = PythonAnalyzer() if language == "python" else JavaScriptAnalyzer()\n'
        "    if language is None:\n"
        "        analyzer = TextAnalyzer()\n"
        "    return analyzer.analyze(path, content)\n"
    ),
    "tests/test_analyzers.py": (
        "from sample.analyzers.python import PythonAnalyzer\n"
        "from sample.languages import detect_language\n\n"
        "def test_python_analyzer():\n"
        '    assert detect_language("module.py") == "python"\n'
        '    assert PythonAnalyzer().analyze("module.py", "value = 1")["path"] == "module.py"\n'
    ),
}


def create_history_repository(
    root: Path,
    *,
    file_count: int = DEFAULT_FILE_COUNT,
    commits: int = DEFAULT_COMMITS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Create a repeatable Git history without retaining generated files in this repository."""

    if file_count < 100:
        raise ValueError("file_count must be at least 100 so change sets remain disjoint")
    if not 1 <= commits <= DEFAULT_COMMITS:
        raise ValueError(f"commits must be between 1 and {DEFAULT_COMMITS}")
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"benchmark target must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    _initialize_git(root)
    _write_config(root)
    for path, content in _SEED_FILES.items():
        _write(root, path, content)

    generic_count = file_count - len(_SEED_FILES)
    for index in range(generic_count):
        _write(root, _module_path(index), _module_content(index, seed=seed))

    operations: list[dict[str, Any]] = []
    _commit(root, 0, "Initial deterministic repository")
    operations.append({"kind": "initial", "files": file_count})

    modified = max(1, file_count // 20)
    renamed = max(1, file_count // 100)
    deleted = max(1, file_count // 100)
    offsets = _operation_offsets(modified, renamed, deleted)
    changes = (
        ("modify", lambda: _modify_modules(root, range(0, modified), seed)),
        ("rename", lambda: _rename_modules(root, range(offsets[0], offsets[1]))),
        ("delete", lambda: _delete_modules(root, range(offsets[1], offsets[2]))),
        ("add", lambda: _add_modules(root, generic_count, deleted, seed)),
        ("ambiguous_import", lambda: _add_ambiguity(root, range(offsets[2], offsets[2] + 3))),
        ("interface_change", lambda: _change_interfaces(root)),
        ("metadata_only", lambda: _metadata_only_change(root)),
    )
    for step, (kind, operation) in enumerate(changes, start=1):
        if step >= commits:
            break
        details = operation()
        _commit(root, step, kind.replace("_", " ").title())
        operations.append({"kind": kind, **details})

    structural_change_kinds = {
        "modify",
        "rename",
        "add",
        "ambiguous_import",
        "interface_change",
    }
    expected_structural_versions = file_count + sum(
        int(item.get("count", 0)) for item in operations if item["kind"] in structural_change_kinds
    )
    expected_raw_versions = expected_structural_versions + sum(
        int(item.get("count", 0)) for item in operations if item["kind"] == "metadata_only"
    )
    return {
        "schema_version": 1,
        "seed": seed,
        "requested_files": file_count,
        "final_files": file_count,
        "commits": commits,
        "change_counts": {
            "modified": modified,
            "renamed": renamed,
            "deleted": deleted,
            "added": deleted,
            "ambiguous_replacements": 3,
            "interface_changes": 3,
            "metadata_only_changes": 1,
        },
        "expected_distinct_artifact_raw_versions": expected_raw_versions,
        "expected_distinct_artifact_structural_versions": expected_structural_versions,
        "operations": operations,
        "scope_goal": "Add a new language analyzer for Go",
        "scope_expected_candidates": sorted(_SEED_FILES),
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _initialize_git(root: Path) -> None:
    _run(root, "init", "-q")
    _run(root, "branch", "-M", "main")
    _run(root, "config", "user.email", "benchmark@example.invalid")
    _run(root, "config", "user.name", "AnaxiGraph Benchmark")


def _write_config(root: Path) -> None:
    _write(
        root,
        ".anaxigraph.yml",
        """project:
  name: Deterministic AnaxiGraph Benchmark
include:
  - src/**
  - app/**
  - tests/**
groups:
  analyzers:
    paths: [src/sample/analyzers/**, src/sample/languages.py]
  application:
    paths: [src/sample/service.py, src/sample/modules/**]
  tests:
    paths: [tests/**]
agent:
  context_limit: 16
  neighbor_depth: 2
  payload_limit_bytes: 20000
semantic:
  enabled: false
""",
    )


def _module_path(index: int) -> str:
    return f"src/sample/modules/module_{index:05d}.py"


def _module_content(index: int, *, seed: int) -> str:
    prior = ""
    body = f"    return value + {(seed + index) % 97}\n"
    if index:
        prior = f"from sample.modules.module_{index - 1:05d} import transform as previous\n\n"
        body = f"    return previous(value) + {(seed + index) % 97}\n"
    return (
        f'"""Deterministic benchmark module {index}."""\n\n'
        f"{prior}"
        "def transform(value: int) -> int:\n"
        f"{body}"
    )


def _operation_offsets(modified: int, renamed: int, deleted: int) -> tuple[int, int, int]:
    rename_start = modified
    delete_start = rename_start + renamed
    ambiguity_start = delete_start + deleted
    return rename_start, delete_start, ambiguity_start


def _modify_modules(root: Path, indexes: Iterable[int], seed: int) -> dict[str, Any]:
    paths = []
    for index in indexes:
        path = root / _module_path(index)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"\nREVISION_VALUE_{index} = {(seed + index) % 1_009}\n")
        paths.append(path.relative_to(root).as_posix())
    return {"count": len(paths), "paths": paths[:10]}


def _rename_modules(root: Path, indexes: Iterable[int]) -> dict[str, Any]:
    paths = []
    for index in indexes:
        source = root / _module_path(index)
        target = source.with_name(f"renamed_{index:05d}.py")
        source.rename(target)
        paths.append(
            {"from": source.relative_to(root).as_posix(), "to": target.relative_to(root).as_posix()}
        )
    return {"count": len(paths), "paths": paths[:10]}


def _delete_modules(root: Path, indexes: Iterable[int]) -> dict[str, Any]:
    paths = []
    for index in indexes:
        path = root / _module_path(index)
        path.unlink()
        paths.append(path.relative_to(root).as_posix())
    return {"count": len(paths), "paths": paths[:10]}


def _add_modules(root: Path, start: int, count: int, seed: int) -> dict[str, Any]:
    paths = []
    for offset in range(count):
        index = start + offset
        path = _module_path(index)
        _write(root, path, _module_content(index, seed=seed))
        paths.append(path)
    return {"count": len(paths), "paths": paths[:10]}


def _add_ambiguity(root: Path, replaced: Iterable[int]) -> dict[str, Any]:
    deleted = []
    for index in replaced:
        path = root / _module_path(index)
        path.unlink()
        deleted.append(path.relative_to(root).as_posix())
    additions = {
        "src/shared.py": "def identify() -> str:\n    return 'source'\n",
        "app/shared.py": "def identify() -> str:\n    return 'application'\n",
        "src/sample/ambiguous_consumer.py": "from shared import identify\n\ndef consume() -> str:\n    return identify()\n",
    }
    for path, content in additions.items():
        _write(root, path, content)
    return {"count": len(additions), "added": sorted(additions), "deleted": deleted}


def _change_interfaces(root: Path) -> dict[str, Any]:
    paths = (
        "src/sample/analyzers/base.py",
        "src/sample/analyzers/python.py",
        "src/sample/languages.py",
    )
    additions = (
        "\n\ndef analyzer_version() -> int:\n    return 2\n",
        "\n\ndef supports_python() -> bool:\n    return True\n",
        "\n\ndef supported_suffixes() -> tuple[str, ...]:\n    return tuple(LANGUAGES)\n",
    )
    for path, content in zip(paths, additions, strict=True):
        with (root / path).open("a", encoding="utf-8") as stream:
            stream.write(content)
    return {"count": len(paths), "paths": list(paths)}


def _metadata_only_change(root: Path) -> dict[str, Any]:
    path = root / "src/sample/service.py"
    content = path.read_text(encoding="utf-8")
    path.write_text(
        content.replace(
            '"""Selects an analyzer and exposes the analysis use case."""',
            '"""Selects analyzers for the public repository-analysis use case."""',
        ),
        encoding="utf-8",
    )
    return {"count": 1, "paths": [path.relative_to(root).as_posix()]}


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(root: Path, step: int, message: str) -> None:
    timestamp = f"2026-01-{step + 1:02d}T12:00:00+00:00"
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    _run(root, "add", "-A", environment=environment)
    _run(root, "commit", "-qm", message, environment=environment)


def _run(
    root: Path,
    *args: str,
    environment: dict[str, str] | None = None,
) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
