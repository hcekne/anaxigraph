"""Reusable Python syntax normalization and symbol-shape helpers."""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import PurePosixPath


class DocstringStripper(ast.NodeTransformer):
    """Remove documentation-only expressions from structural fingerprints."""

    def _without_docstring(self, node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:]
        return self.generic_visit(node)

    def visit_Module(self, node: ast.Module) -> ast.AST:
        return self._without_docstring(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        return self._without_docstring(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._without_docstring(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._without_docstring(node)


def comment_lines(content: str) -> set[int]:
    result: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(content).readline):
            if token.type == tokenize.COMMENT:
                result.update(range(token.start[0], token.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        pass
    return result


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def source_segment(lines: list[str], node: ast.AST) -> str:
    start_line = max(0, int(getattr(node, "lineno", 1)) - 1)
    end_line = max(start_line, int(getattr(node, "end_lineno", start_line + 1)) - 1)
    if start_line >= len(lines) or end_line >= len(lines):
        return ""
    start = int(getattr(node, "col_offset", 0))
    end = int(getattr(node, "end_col_offset", 0))
    if start_line == end_line:
        return _normalize(_byte_slice(lines[start_line], start, end if end else None))
    selected = lines[start_line : end_line + 1]
    selected[0] = _byte_slice(selected[0], start, None)
    selected[-1] = _byte_slice(selected[-1], 0, end if end else None)
    return _normalize("".join(selected))


def node_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = node_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return node_name(node.value)
    if isinstance(node, ast.Call):
        return node_name(node.func)
    return ""


def call_root(node: ast.AST) -> str:
    return node_name(node).split(".", 1)[0]


def complexity(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(
            child,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.IfExp,
                ast.ExceptHandler,
                ast.comprehension,
                ast.Match,
            ),
        ):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += max(1, len(child.values) - 1)
    return score


def format_annotation(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (ValueError, TypeError):
        return ""


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args: list[str] = []
    all_args = [*node.args.posonlyargs, *node.args.args]
    defaults = [None] * (len(all_args) - len(node.args.defaults)) + list(node.args.defaults)
    for arg, default in zip(all_args, defaults, strict=True):
        item = arg.arg
        annotation = format_annotation(arg.annotation)
        if annotation:
            item += f": {annotation}"
        if default is not None:
            item += " = ..."
        args.append(item)
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    args.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    result = f"{prefix} {node.name}({', '.join(args)})"
    returns = format_annotation(node.returns)
    return f"{result} -> {returns}" if returns else result


def class_signature(node: ast.ClassDef) -> str:
    bases = ", ".join(filter(None, (node_name(base) for base in node.bases)))
    return f"class {node.name}({bases})" if bases else f"class {node.name}"


def function_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    decorators = {
        node_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        for decorator in node.decorator_list
    }
    if any(name.split(".")[-1] in {"get", "post", "put", "patch", "delete"} for name in decorators):
        return "api_endpoint"
    if node.name.startswith(("on_", "handle_")) or node.name.endswith("_handler"):
        return "event_handler"
    return "function"


def _byte_slice(value: str, start: int, end: int | None) -> str:
    return value.encode("utf-8")[start:end].decode("utf-8", errors="replace")


def _normalize(value: str) -> str:
    return value.strip().replace("\n", " ")[:500]
