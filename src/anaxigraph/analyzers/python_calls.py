"""Lexical Python call bindings; dynamic receivers stay explicitly unresolved."""

from __future__ import annotations

import ast
from pathlib import PurePosixPath

from anaxigraph.analyzers.python_syntax import module_name, node_name


class CallContext:
    def __init__(self, path: str, tree: ast.Module):
        self.path = path
        self.module = module_name(path)
        self.scopes = []
        self.environments = [_bindings(tree, self.module)]
        self.kinds = ["module"]
        self.owners = []
        self.classes = []

    def bind_import(self, name: str, target: str) -> None:
        self.environments[-1][name] = ("import", target)

    def relative_import(self, name: str, level: int) -> str:
        if not level:
            return name
        parts = self.module.split(".")
        if PurePosixPath(self.path).stem != "__init__":
            parts.pop()
        if level > len(parts):
            return ""
        return ".".join((*parts[: len(parts) - level + 1], *name.split("."))).rstrip(".")

    def enter(self, node, kind: str) -> None:
        qualified = ".".join((self.module, *self.scopes, node.name))
        parent = -2 if kind == "function" and self.kinds[-1] == "class" else -1
        environment = {**self.environments[parent], **_bindings(node, qualified)}
        if kind == "function":
            arguments = [*node.args.posonlyargs, *node.args.args]
            for argument in (*arguments, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg):
                if argument:
                    environment[argument.arg] = ("dynamic", "")
            static = any(node_name(item).endswith("staticmethod") for item in node.decorator_list)
            if self.kinds[-1] == "class" and arguments and not static:
                environment[arguments[0].arg] = ("receiver", self.classes[-1])
            self.owners.append(qualified)
        else:
            self.classes.append(qualified)
        self.scopes.append(node.name)
        self.kinds.append(kind)
        self.environments.append(environment)

    def leave(self) -> None:
        kind = self.kinds.pop()
        self.environments.pop()
        self.scopes.pop()
        (self.owners if kind == "function" else self.classes).pop()

    def store(self, name: str) -> None:
        self.environments[-1][name] = ("dynamic", "")

    def call(self, node: ast.Call) -> dict:
        target = node_name(node.func)
        root, separator, tail = target.partition(".")
        kind, bound = self.environments[-1].get(root, ("dynamic", ""))
        if not _static_target(node.func):
            kind, bound = "dynamic", ""
        return {
            "target": target,
            "line": node.lineno,
            "column": node.col_offset,
            "caller": self.owners[-1] if self.owners else "",
            "binding": kind,
            "qualified_target": bound + separator + tail if bound else "",
        }


def _bindings(node: ast.AST, prefix: str) -> dict:
    result = {}
    stack = list(getattr(node, "body", []))
    global_names = set()
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.setdefault(child.name, ("definition", prefix + "." + child.name))
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for item in child.names:
                result[item.asname or item.name.split(".")[0]] = ("dynamic", "")
        elif isinstance(child, ast.Global):
            global_names.update(child.names)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            result[child.id] = ("dynamic", "")
        elif not isinstance(
            child, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            stack.extend(ast.iter_child_nodes(child))
    return {key: value for key, value in result.items() if key not in global_names}


def _static_target(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Name) or isinstance(node, ast.Attribute) and _static_target(node.value)
    )
