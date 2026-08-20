"""Static function and public-interface metrics used by quality gates."""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FunctionMetric:
    path: str
    qualified_name: str
    lines: int
    complexity: int


def scan_functions(root: Path, policy: dict[str, Any]) -> list[FunctionMetric]:
    """Measure every first-party Python function with stable qualified identities."""

    source_root = root / policy["source_root"] / Path(policy["package"].replace(".", "/"))
    metrics: list[FunctionMetric] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if _matches_any(relative, policy.get("exclude", [])):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        metrics.extend(_function_metrics(tree, relative))
    return metrics


def public_surface(content: str) -> set[str]:
    tree = ast.parse(content)
    result: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith(
            "_"
        ):
            result.add(f"function {node.name}{ast.unparse(node.args)}")
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            result.add(f"class {node.name}")
            for child in node.body:
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and not child.name.startswith("_"):
                    result.add(f"method {node.name}.{child.name}{ast.unparse(child.args)}")
    return result


def _function_metrics(tree: ast.AST, path: str) -> list[FunctionMetric]:
    result: list[FunctionMetric] = []

    def visit(body: list[ast.stmt], parents: tuple[str, ...]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*parents, node.name))
                result.append(
                    FunctionMetric(
                        path=path,
                        qualified_name=qualified,
                        lines=max(1, int(node.end_lineno or node.lineno) - node.lineno + 1),
                        complexity=_ComplexityVisitor().measure(node),
                    )
                )
                visit(node.body, (*parents, node.name, "<locals>"))
            elif isinstance(node, ast.ClassDef):
                visit(node.body, (*parents, node.name))

    visit(getattr(tree, "body", []), ())
    return result


class _ComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.value = 1

    def measure(self, node: ast.AST) -> int:
        for statement in getattr(node, "body", []):
            self.visit(statement)
        return self.value

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None

    def visit_If(self, node: ast.If) -> None:
        self.value += 1
        self.generic_visit(node)

    visit_For = visit_If
    visit_AsyncFor = visit_If
    visit_While = visit_If
    visit_IfExp = visit_If
    visit_Assert = visit_If
    visit_comprehension = visit_If

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.value += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.value += len(node.handlers) + bool(node.orelse) + bool(node.finalbody)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.value += max(1, len(node.cases))
        self.generic_visit(node)


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
