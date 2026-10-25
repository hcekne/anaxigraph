"""Protect component contracts and the clean package's source boundary."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import tomllib
from pathlib import Path

import pytest

import anaxigraph
from anaxigraph.analysis import build_request
from anaxigraph.indexing import index

PROJECT = Path(__file__).parents[1]
PACKAGE = PROJECT / "src" / "anaxigraph"
SOURCES = sorted(PACKAGE.rglob("*.py"))


def module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE.parent).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def internal_imports(path: Path) -> list[str]:
    current = module_name(path)
    package = current if path.name == "__init__.py" else current.rpartition(".")[0]
    imports = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = ("." * node.level) + (node.module or "")
            imports.append(importlib.util.resolve_name(name, package) if node.level else name)
    return [name for name in imports if name == "anaxigraph" or name.startswith("anaxigraph.")]


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(PACKAGE)))
def test_internal_dependencies_follow_component_contracts(path):
    current = module_name(path)
    parts = current.split(".")
    component = parts[1] if len(parts) > 1 else "metadata"
    allowed = {
        "metadata": set(),
        "contracts": set(),
        "indexing": {"contracts", "indexing"},
        "storage": {"contracts", "storage"},
        "analysis": {"contracts", "analysis"},
        "application": {"metadata", "contracts", "indexing", "storage", "analysis"},
        "interfaces": {"metadata", "application", "interfaces"},
    }
    assert component in allowed, f"Declare a deliberate dependency contract for {current}"
    for imported in internal_imports(path):
        target = imported.split(".")[1] if "." in imported else "metadata"
        assert target in allowed[component], f"{current} must not depend on {imported}"


def test_every_internal_import_is_resolved_inside_v2_and_no_legacy_path_is_added():
    for path in SOURCES:
        for imported in internal_imports(path):
            relative = imported.split(".")[1:]
            target = PACKAGE.joinpath(*relative)
            assert target.with_suffix(".py").exists() or (target / "__init__.py").exists(), (
                f"{path}: {imported} requires source outside the V2 package"
            )
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                assert name not in {"__import__", "importlib.import_module", "runpy.run_path"}, (
                    f"{path}: runtime import must have a statically reviewable component boundary"
                )
            if isinstance(node, ast.Attribute):
                assert ast.unparse(node) != "sys.path", (
                    f"{path}: do not find legacy code through sys.path"
                )
                assert node.attr != "__path__", f"{path}: do not extend package lookup paths"
            if isinstance(node, ast.Name):
                assert node.id != "__path__", f"{path}: do not extend package lookup paths"


def test_frontend_and_protocol_frameworks_do_not_enter_core_components():
    for component in ("contracts.py", "analysis", "indexing", "storage"):
        target = PACKAGE / component
        paths = [target] if target.is_file() else target.rglob("*.py")
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                )
                assert not any(
                    name.split(".")[0] in {"fastapi", "mcp", "uvicorn"} for name in names
                )


def test_v2_build_metadata_packages_only_v2_and_declares_complete_assets():
    metadata = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    assert metadata["project"]["name"] == "anaxigraph"
    assert metadata["project"]["version"] == anaxigraph.__version__
    assert metadata["project"]["scripts"]["anaxigraph"] == "anaxigraph.interfaces.cli:main"
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
    assert not any(
        dependency.lower().split("[", 1)[0].startswith("anaxigraph")
        for dependency in metadata["project"]["dependencies"]
    ), "V2 must not install legacy AnaxiGraph as its engine"
    patterns = metadata["tool"]["setuptools"]["package-data"]["anaxigraph"]
    packaged = {
        path.relative_to(PACKAGE).as_posix()
        for pattern in patterns
        for path in PACKAGE.glob(pattern)
    }
    required = {
        "analysis/catalog/patterns.json",
        "interfaces/assets/index.html",
        "interfaces/assets/app.js",
        "interfaces/assets/styles.css",
    }
    assert required <= packaged
    assert (PROJECT / "LICENSE").is_file()


def test_git_cached_paths_do_not_follow_symlinked_ancestor_outside_repository(tmp_path):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "secret.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    (root / "pkg" / "secret.py").unlink()
    (root / "pkg").rmdir()
    (root / "pkg").symlink_to(outside, target_is_directory=True)
    (outside / "secret.py").write_text("def external_secret():\n    return 123\n")
    graph = index(root)
    assert "pkg/secret.py" not in graph.snapshot.files
    assert not any(node.name == "external_secret" for node in graph.nodes)
    assert any("not a regular repository input" in message for message in graph.diagnostics)


def test_annotation_source_read_rejects_symlinked_ancestor_even_with_same_bytes(tmp_path):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "pkg").mkdir()
    original = root / "pkg" / "safe.py"
    original.write_text("def work():\n    return 1\n")
    graph = index(root)
    (outside / "safe.py").write_bytes(original.read_bytes())
    original.unlink()
    original.parent.rmdir()
    (root / "pkg").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="[Ss]ymlink|[Rr]epository|[Oo]utside|[Ss]ource"):
        build_request(graph, "annotate", ["pkg/safe.py"])
