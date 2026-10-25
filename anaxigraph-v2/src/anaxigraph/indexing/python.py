"""Scoped Python source facts. Dynamic dispatch is explicitly incomplete."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from anaxigraph.contracts import Edge, Node


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


class _Definitions(ast.NodeVisitor):
    def __init__(self, module: Module):
        self.module = module
        self.scope = ""

    def _symbol(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        qualified = f"{self.scope}.{node.name}".strip(".")
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        if kind == "class" and any(
            expression(base).split(".")[-1] in {"Protocol", "ABC"} for base in node.bases
        ):
            kind = "interface"
        data = {
            "qualified_name": qualified,
            "public": not node.name.startswith("_"),
            "basis": "observed",
            "end_line": node.end_lineno,
            "lines_of_code": (node.end_lineno or node.lineno) - node.lineno + 1,
            "docstring": (ast.get_docstring(node) or "")[:400],
            "is_test": is_test(self.module.path),
            "decorators": [expression(d) for d in node.decorator_list],
        }
        truncated = []
        if len(ast.get_docstring(node) or "") > 400:
            truncated.append("docstring")
        if len(node.decorator_list) > 10:
            data["decorators"] = data["decorators"][:10]
            truncated.append("decorators")
        elif any(len(ast.unparse(item)) > 240 for item in node.decorator_list):
            truncated.append("decorators")
        data["decorator_count"] = len(node.decorator_list)
        if isinstance(node, ast.ClassDef):
            data["bases"] = [expression(base) for base in node.bases[:10]]
            data["base_count"] = len(node.bases)
            if len(node.bases) > 10 or any(len(ast.unparse(base)) > 240 for base in node.bases):
                truncated.append("bases")
        else:
            signature = f"{node.name}({ast.unparse(node.args)})" + (
                f" -> {expression(node.returns)}" if node.returns else ""
            )
            parameters = [
                arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            ]
            if len(signature) > 500:
                truncated.append("signature")
            if len(parameters) > 50:
                truncated.append("parameters")
            if node.returns is not None and len(ast.unparse(node.returns)) > 240:
                truncated.append("returns")
            data.update(
                {
                    "signature": signature[:500],
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "parameters": parameters[:50],
                    "parameter_count": len(parameters),
                    "returns": expression(node.returns),
                }
            )
        data["truncated_fields"] = truncated
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


class Resolver:
    def __init__(self, modules: list[Module]):
        self.by_name: dict[str, list[Module]] = defaultdict(list)
        for module in modules:
            for name in module.names:
                self.by_name[name].append(module)

    def find_module(self, name: str, source: Module) -> tuple[Module | None, str]:
        candidates = self.by_name.get(name, [])
        local = [candidate for candidate in candidates if candidate.origin == source.origin]
        matches = local or candidates
        return (
            (matches[0], "resolved")
            if len(matches) == 1
            else (None, "ambiguous" if matches else "unresolved")
        )

    def target(self, expression_name: str, source: Module, scope: str) -> tuple[str | None, str]:
        names = expression_name.split(".")
        first = names[0]
        # The lexical method is a possible dispatch target, never a proof of runtime dispatch.
        if first in {"self", "cls"} and len(names) == 2 and "." in scope:
            qualified = scope.rpartition(".")[0] + "." + names[1]
            if qualified in source.definitions:
                return source.definitions[qualified].id, "ambiguous"
        scopes = [scope]
        while scopes[-1]:
            scopes.append(scopes[-1].rpartition(".")[0])
        for parent in scopes:
            if parent != scope and any(
                node.kind in {"class", "interface"} and node.data["qualified_name"] == parent
                for node in source.nodes
            ):
                continue  # Class bodies are not enclosing lexical scopes of methods.
            if first in source.bound.get(parent, set()):
                return None, "unresolved"  # Parameters/assignments shadow outer lexical names.
            qualified = ".".join(part for part in (parent, expression_name) if part)
            if qualified in source.definitions:
                node = source.definitions[qualified]
                count = sum(n.data.get("qualified_name") == qualified for n in source.nodes)
                return node.id, "ambiguous" if count > 1 else "resolved"
            binding = source.bindings.get(parent, {}).get(first)
            if binding:
                kind, module_name, imported = binding
                suffix = names[1:]
                if kind == "module":
                    # import package.module binds package, so consume module suffixes first.
                    for length in range(len(suffix), -1, -1):
                        name = ".".join([module_name, *suffix[:length]])
                        target_module, status = self.find_module(name, source)
                        if target_module:
                            remaining = ".".join(suffix[length:])
                            target_node = target_module.definitions.get(remaining)
                            if remaining and target_node is None:
                                return None, "unresolved"
                            return target_node.id if target_node else module_id(
                                target_module.path
                            ), status
                    return None, "unresolved"
                target_module, status = self.find_module(module_name, source)
                if target_module:
                    qualified = ".".join([imported, *suffix])
                    target_node = target_module.definitions.get(qualified)
                    if target_node:
                        return target_node.id, status
                imported_module, substatus = self.find_module(
                    f"{module_name}.{imported}".strip("."), source
                )
                if imported_module:
                    target_node = (
                        imported_module.definitions.get(".".join(suffix)) if suffix else None
                    )
                    if suffix and target_node is None:
                        return None, "unresolved"
                    return target_node.id if target_node else module_id(
                        imported_module.path
                    ), substatus
                return None, status if status == "ambiguous" else "unresolved"
        return None, "unresolved"


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
