"""Scoped Python source facts. Dynamic dispatch is explicitly incomplete."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from anaxigraph.contracts import Edge, Node

if TYPE_CHECKING:
    from anaxigraph.indexing.resolution import Resolver


def module_id(path: str) -> str:
    return f"module:{path}"


def symbol_id(path: str, name: str) -> str:
    return f"symbol:{path}#{name}"


def expression(node: ast.AST | None) -> str:
    return ast.unparse(node)[:240] if node is not None else ""


def reference_name(node: ast.AST) -> str:
    """Describe a reference without copying arbitrary call arguments into a graph ID."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{reference_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{reference_name(node.func)}(...)"
    if isinstance(node, ast.Subscript):
        return f"{reference_name(node.value)}[...]"
    return "<dynamic>"


def is_test(path: str) -> bool:
    p = PurePosixPath(path)
    return "tests" in p.parts or p.name.startswith("test_") or p.name.endswith("_test.py")


@dataclass
class Module:
    path: str
    tree: ast.Module
    name: str
    origin: str
    names: set[str]
    nodes: list[Node] = field(default_factory=list)
    definitions: dict[str, Node] = field(default_factory=dict)
    bindings: dict[str, dict[str, tuple[str, str, str]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    bound: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    scopes: dict[int, str] = field(default_factory=dict)

    @property
    def package(self) -> str:
        return (
            self.name
            if PurePosixPath(self.path).stem == "__init__"
            else self.name.rpartition(".")[0]
        )


def parse_module(
    path: str, source: str, fingerprint: str
) -> tuple[Module | None, Node, str | None]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    # Conventional src layouts are import roots, including a nested V2 project.
    prefix = parts.index("src") + 1 if "src" in parts else 0
    name = ".".join(parts[prefix:]) or PurePosixPath(path).parent.name
    origin = "/".join(parts[:prefix])
    data = {
        "language": "python",
        "fingerprint": fingerprint,
        "loc": sum(
            bool(line.strip()) and not line.lstrip().startswith("#") for line in source.splitlines()
        ),
        "physical_lines": len(source.splitlines()),
        "function_count": 0,
        "class_count": 0,
        "is_test": is_test(path),
        "basis": "observed",
        "parse_status": "parsed",
    }
    try:
        tree = ast.parse(source, filename=path, type_comments=True)
    except (SyntaxError, ValueError) as exc:
        data["parse_status"] = "error"
        return (
            None,
            Node(module_id(path), "module", name, path, 1, data),
            f"{path}: {type(exc).__name__}: {exc}",
        )
    module = Module(path, tree, name, origin, {name, ".".join(parts)})
    _Definitions(module).visit(tree)
    data["function_count"] = sum(node.kind == "function" for node in module.nodes)
    data["class_count"] = sum(node.kind in {"class", "interface"} for node in module.nodes)
    data["docstring"] = (ast.get_docstring(tree) or "")[:600]
    data["truncated_fields"] = ["docstring"] if len(ast.get_docstring(tree) or "") > 600 else []
    return module, Node(module_id(path), "module", name, path, 1, data), None


def _common_metadata(module: Module, node, qualified: str) -> dict:
    docstring = ast.get_docstring(node) or ""
    truncated = ["docstring"] if len(docstring) > 400 else []
    if len(node.decorator_list) > 10 or any(
        len(ast.unparse(item)) > 240 for item in node.decorator_list
    ):
        truncated.append("decorators")
    return {
        "qualified_name": qualified,
        "public": not node.name.startswith("_"),
        "basis": "observed",
        "end_line": node.end_lineno,
        "lines_of_code": (node.end_lineno or node.lineno) - node.lineno + 1,
        "docstring": docstring[:400],
        "is_test": is_test(module.path),
        "decorators": [expression(item) for item in node.decorator_list[:10]],
        "decorator_count": len(node.decorator_list),
        "truncated_fields": truncated,
    }


def _class_metadata(node: ast.ClassDef) -> tuple[str, dict, list[str]]:
    kind = (
        "interface"
        if any(expression(base).split(".")[-1] in {"Protocol", "ABC"} for base in node.bases)
        else "class"
    )
    truncated = (
        ["bases"]
        if len(node.bases) > 10 or any(len(ast.unparse(base)) > 240 for base in node.bases)
        else []
    )
    return (
        kind,
        {"bases": [expression(base) for base in node.bases[:10]], "base_count": len(node.bases)},
        truncated,
    )


def _function_metadata(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, dict, list[str]]:
    signature = f"{node.name}({ast.unparse(node.args)})" + (
        f" -> {expression(node.returns)}" if node.returns else ""
    )
    parameters = [
        arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    ]
    truncated = []
    if len(signature) > 500:
        truncated.append("signature")
    if len(parameters) > 50:
        truncated.append("parameters")
    if node.returns is not None and len(ast.unparse(node.returns)) > 240:
        truncated.append("returns")
    return (
        "function",
        {
            "signature": signature[:500],
            "async": isinstance(node, ast.AsyncFunctionDef),
            "parameters": parameters[:50],
            "parameter_count": len(parameters),
            "returns": expression(node.returns),
        },
        truncated,
    )


class _Definitions(ast.NodeVisitor):
    def __init__(self, module: Module):
        self.module = module
        self.scope = ""

    def _symbol(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        qualified = f"{self.scope}.{node.name}".strip(".")
        data = _common_metadata(self.module, node, qualified)
        kind, details, truncated = (
            _class_metadata(node) if isinstance(node, ast.ClassDef) else _function_metadata(node)
        )
        data.update(details)
        data["truncated_fields"].extend(truncated)
        # Overloads/redefinitions remain separate observations; resolution will be ambiguous.
        previous = self.module.definitions.get(qualified)
        identity = symbol_id(self.module.path, qualified) + (f"@{node.lineno}" if previous else "")
        observed = Node(identity, kind, node.name, self.module.path, node.lineno, data)
        self.module.nodes.append(observed)
        self.module.definitions[qualified] = observed
        self.module.scopes[id(node)] = qualified
        if not isinstance(node, ast.ClassDef):
            args = node.args
            self.module.bound[qualified].update(
                arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            )
            self.module.bound[qualified].update(arg.arg for arg in (args.vararg, args.kwarg) if arg)
        parent = self.scope
        self.scope = qualified
        self.generic_visit(node)
        self.scope = parent

    visit_FunctionDef = _symbol
    visit_AsyncFunctionDef = _symbol
    visit_ClassDef = _symbol

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.module.bound[self.scope].add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.module.bindings[self.scope][local] = (
                "module",
                alias.name if alias.asname else local,
                "",
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        package = self.module.package.split(".") if self.module.package else []
        if node.level:
            package = package[: len(package) - node.level + 1] if node.level <= len(package) else []
            target = ".".join([*package, *([node.module] if node.module else [])])
        else:
            target = node.module or ""
        for alias in node.names:
            self.module.bindings[self.scope][alias.asname or alias.name] = (
                "symbol",
                target,
                alias.name,
            )


class Relationships(ast.NodeVisitor):
    def __init__(self, module: Module, resolver: Resolver):
        self.module = module
        self.resolver = resolver
        self.scope = ""
        self.owner = module_id(module.path)
        self.edges: list[Edge] = []
        self.external: dict[str, Node] = {}

    def emit(self, target: str, kind: str, line: int, resolution: str = "resolved") -> None:
        self.edges.append(Edge(self.owner, target, kind, self.module.path, line, resolution))
        if (
            kind in {"calls", "imports"}
            and is_test(self.module.path)
            and not target.startswith("external:")
        ):
            self.edges.append(
                Edge(
                    module_id(self.module.path), target, "tests", self.module.path, line, resolution
                )
            )

    def unknown(self, name: str) -> str:
        identity = f"external:{self.module.path}#{self.scope or '<module>'}:{name}"
        self.external[identity] = Node(
            identity,
            "external",
            name,
            self.module.path,
            1,
            {
                "basis": "observed",
                "resolution": "unresolved",
                "scope": self.scope,
                "note": "Observed reference; target is external or could not be resolved statically.",
            },
        )
        return identity

    def _symbol(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        qualified = self.module.scopes[id(node)]
        symbol = next(
            n
            for n in self.module.nodes
            if n.line == node.lineno and n.data["qualified_name"] == qualified
        )
        self.emit(symbol.id, "contains", node.lineno)
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = expression(base)
                target, status = self.resolver.target(name, self.module, self.scope)
                self.edges.append(
                    Edge(
                        symbol.id,
                        target or self.unknown(name),
                        "inherits",
                        self.module.path,
                        base.lineno,
                        status,
                    )
                )
        # Decorators/defaults execute in the enclosing scope, not inside the new function.
        for decorator in node.decorator_list:
            self.visit(decorator)
        if not isinstance(node, ast.ClassDef):
            for default in [*node.args.defaults, *(d for d in node.args.kw_defaults if d)]:
                self.visit(default)
        previous = self.scope, self.owner
        self.scope, self.owner = qualified, symbol.id
        for statement in node.body:
            self.visit(statement)
        self.scope, self.owner = previous

    visit_FunctionDef = _symbol
    visit_AsyncFunctionDef = _symbol
    visit_ClassDef = _symbol

    def visit_Call(self, node: ast.Call) -> None:
        name = reference_name(node.func)
        target, status = self.resolver.target(name, self.module, self.scope)
        self.emit(target or self.unknown(name), "calls", node.lineno, status)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        target, status = self.resolver.target(node.id, self.module, self.scope)
        if target:
            self.emit(target, "references", node.lineno, status)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            target, status = self.resolver.find_module(alias.name, self.module)
            self.emit(
                module_id(target.path) if target else self.unknown(alias.name),
                "imports",
                node.lineno,
                status,
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            local = alias.asname or alias.name
            target, status = self.resolver.target(local, self.module, self.scope)
            self.emit(
                target or self.unknown("." * node.level + (node.module or "") + "." + alias.name),
                "imports",
                node.lineno,
                status,
            )
