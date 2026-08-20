#!/usr/bin/env python3
"""Reject package dependency cycles and explicitly forbidden internal imports."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_POLICY = Path("quality/architecture-policy.json")


@dataclass(frozen=True, slots=True)
class ArchitectureIssue:
    issue_type: str
    message: str
    modules: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.issue_type,
            "message": self.message,
            "modules": list(self.modules),
        }


def check_architecture(
    root: Path, *, policy_path: Path = DEFAULT_POLICY
) -> list[ArchitectureIssue]:
    root = root.resolve()
    policy = json.loads((root / policy_path).read_text(encoding="utf-8"))
    graph = dependency_graph(
        root,
        source_root=Path(policy["source_root"]),
        package=policy["package"],
    )
    issues = [
        ArchitectureIssue(
            "dependency_cycle",
            "internal package cycle: " + " -> ".join((*component, component[0])),
            component,
        )
        for component in strongly_connected_components(graph)
        if len(component) > 1
    ]
    for rule in policy.get("forbidden_dependencies", []):
        source_prefix = rule["from"]
        target_prefix = rule["to"]
        for source, targets in graph.items():
            if not _within(source, source_prefix):
                continue
            for target in targets:
                if _within(target, target_prefix):
                    issues.append(
                        ArchitectureIssue(
                            "forbidden_dependency",
                            f"{source} may not import {target}: {rule['reason']}",
                            (source, target),
                        )
                    )
    return sorted(issues, key=lambda item: (item.issue_type, item.modules))


def dependency_graph(root: Path, *, source_root: Path, package: str) -> dict[str, set[str]]:
    base = root / source_root / Path(package.replace(".", "/"))
    modules = {_module_name(path, root / source_root): path for path in base.rglob("*.py")}
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for module, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise ValueError(f"cannot parse {path.relative_to(root)}: {exc}") from exc
        for target in _imports(tree, module, path.name == "__init__.py"):
            resolved = _known_module(target, modules)
            if resolved is not None and resolved != module:
                graph[module].add(resolved)
    return graph


def strongly_connected_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    index = 0
    stack: list[str] = []
    indexes: dict[str, int] = {}
    low_links: dict[str, int] = {}
    active: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        low_links[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for target in sorted(graph[node]):
            if target not in indexes:
                visit(target)
                low_links[node] = min(low_links[node], low_links[target])
            elif target in active:
                low_links[node] = min(low_links[node], indexes[target])
        if low_links[node] != indexes[node]:
            return
        component = []
        while stack:
            target = stack.pop()
            active.remove(target)
            component.append(target)
            if target == node:
                break
        components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return sorted(components)


def _imports(tree: ast.AST, module: str, is_package: bool) -> set[str]:
    values: set[str] = set()
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                retained = base[: max(0, len(base) - node.level + 1)]
                target = ".".join((*retained, node.module or "")).strip(".")
            else:
                target = node.module or ""
            if target:
                values.add(target)
                values.update(f"{target}.{alias.name}" for alias in node.names if alias.name != "*")
    return values


def _module_name(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _known_module(target: str, modules: dict[str, Path]) -> str | None:
    candidates = [
        module for module in modules if target == module or target.startswith(f"{module}.")
    ]
    return max(candidates, key=len) if candidates else None


def _within(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    issues = check_architecture(args.root, policy_path=args.policy)
    if args.json:
        print(json.dumps({"errors": len(issues), "issues": [item.as_dict() for item in issues]}))
    else:
        for issue in issues:
            print(f"ERROR: {issue.message}")
        print(f"Architecture check: {len(issues)} error(s).")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
