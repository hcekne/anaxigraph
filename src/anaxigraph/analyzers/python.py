"""Deterministic Python AST extraction."""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import tokenize
from pathlib import PurePosixPath
from typing import Iterable

from anaxigraph.ir import module_identity, resolver_context, symbol_visibility
from anaxigraph.models import Dependency, FileAnalysis, Symbol


class PythonAnalyzer:
    name = "builtin-python-ast"
    version = "1"
    languages = frozenset({"python"})

    def analyze(self, path: str, content: str) -> FileAnalysis:
        identity = module_identity(path, "python")
        lines = content.splitlines()
        comments = _comment_lines(content)
        loc = sum(
            1 for index, line in enumerate(lines, start=1) if line.strip() and index not in comments
        )
        try:
            tree = ast.parse(content, filename=path, type_comments=True)
        except (SyntaxError, ValueError) as exc:
            return _parse_failure(path, content, loc, len(comments), identity, exc, self)

        visitor = _PythonVisitor(path, content)
        visitor.visit(tree)
        structural_tree = _DocstringStripper().visit(copy.deepcopy(tree))
        ast.fix_missing_locations(structural_tree)
        structural = ast.dump(structural_tree, annotate_fields=True, include_attributes=False)
        module_doc = ast.get_docstring(tree, clean=True) or ""
        public = [symbol.name for symbol in visitor.symbols if not symbol.name.startswith("_")]
        summary = _module_summary(path, module_doc, visitor.symbols)
        responsibilities = _responsibilities(visitor.symbols)
        inputs, outputs, side_effects = _interfaces(visitor)
        complexity = 1 + sum(max(0, symbol.complexity - 1) for symbol in visitor.symbols)
        return FileAnalysis(
            language="python",
            structural_hash=hashlib.sha256(structural.encode()).hexdigest(),
            lines_of_code=loc,
            comment_lines=len(comments),
            complexity=max(1, complexity),
            summary=summary,
            responsibilities=responsibilities,
            inputs=inputs,
            outputs=outputs,
            side_effects=side_effects,
            public_interfaces=public,
            symbols=visitor.symbols,
            dependencies=visitor.dependencies,
            analyzer=self.name,
            metadata={"module_docstring": module_doc[:2_000]},
            module_identity=identity,
            exports=public,
            parse_status="parsed",
            analyzer_version=self.version,
            resolver_context=resolver_context(identity, import_aliases=visitor.import_aliases),
        )


def _parse_failure(path, content, loc, comment_lines, identity, exc, analyzer) -> FileAnalysis:
    normalized = content.replace("\r\n", "\n")
    return FileAnalysis(
        language="python",
        structural_hash=hashlib.sha256(normalized.encode()).hexdigest(),
        lines_of_code=loc,
        comment_lines=comment_lines,
        complexity=1,
        summary=f"Python module {PurePosixPath(path).stem}",
        parse_error=f"{type(exc).__name__}: {exc}",
        analyzer=analyzer.name,
        module_identity=identity,
        parse_status="parse_error",
        analyzer_version=analyzer.version,
        resolver_context=resolver_context(identity),
    )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, path: str, content: str) -> None:
        self.path = path
        self.content = content
        self.source_lines = content.splitlines(keepends=True)
        self.module = _module_name(path)
        self.scope: list[str] = []
        self.symbols: list[Symbol] = []
        self.dependencies: list[Dependency] = []
        self.import_aliases: dict[str, str] = {}
        self.call_targets: set[tuple[str, int]] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            alias = item.asname or item.name.split(".")[0]
            self.import_aliases[alias] = item.name
            self.dependencies.append(
                Dependency(
                    target=item.name,
                    line=node.lineno,
                    evidence=self._source_segment(node),
                    names=(item.name,),
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        prefix = "." * node.level
        target = prefix + (node.module or "")
        names = tuple(item.name for item in node.names)
        for item in node.names:
            self.import_aliases[item.asname or item.name] = target
        self.dependencies.append(
            Dependency(
                target=target,
                line=node.lineno,
                evidence=self._source_segment(node),
                names=names,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        kind = "class"
        bases = {_name(base) for base in node.bases}
        if any(base.endswith(("Base", "Model")) for base in bases):
            kind = "database_model"
        self._add_symbol(node, kind, _class_signature(node), 1)
        for base in node.bases:
            target = _name(base)
            if target:
                self.dependencies.append(
                    Dependency(
                        target=f"symbol:{target}",
                        relationship_type="extends",
                        line=node.lineno,
                        evidence=f"class {node.name}({target})",
                        confidence=0.9,
                    )
                )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = _function_kind(node)
        if self.scope and kind == "function":
            kind = "method"
        self._add_symbol(node, kind, _function_signature(node), _complexity(node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        root = _call_root(node.func)
        target = self.import_aliases.get(root)
        if target and (target, node.lineno) not in self.call_targets:
            self.call_targets.add((target, node.lineno))
            self.dependencies.append(
                Dependency(
                    target=target,
                    relationship_type="calls",
                    line=node.lineno,
                    evidence=self._source_segment(node),
                    confidence=0.85,
                )
            )
        self.generic_visit(node)

    def _source_segment(self, node: ast.AST) -> str:
        return _source_segment(self.source_lines, node)

    def _add_symbol(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: str,
        signature: str,
        complexity: int,
    ) -> None:
        name = node.name
        qualified = ".".join((self.module, *self.scope, name)).strip(".")
        summary = ast.get_docstring(node, clean=True) or ""
        start = node.lineno
        end = getattr(node, "end_lineno", node.lineno)
        self.symbols.append(
            Symbol(
                symbol_type=kind,
                name=name,
                qualified_name=qualified,
                start_line=start,
                end_line=end,
                signature=signature[:1_000],
                summary=summary.split("\n\n", 1)[0][:1_000],
                complexity=complexity,
                logical_lines=max(1, end - start + 1),
                visibility=symbol_visibility(name),
                start_column=int(getattr(node, "col_offset", 0)),
                end_column=int(getattr(node, "end_col_offset", 0) or 0),
            )
        )


class _DocstringStripper(ast.NodeTransformer):
    """Remove documentation-only string expressions from structural fingerprints."""

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


def _comment_lines(content: str) -> set[int]:
    result: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(content).readline):
            if token.type == tokenize.COMMENT:
                result.update(range(token.start[0], token.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        pass
    return result


def _module_name(path: str) -> str:
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _source_segment(lines: list[str], node: ast.AST) -> str:
    start_line = max(0, int(getattr(node, "lineno", 1)) - 1)
    end_line = max(start_line, int(getattr(node, "end_lineno", start_line + 1)) - 1)
    if start_line >= len(lines) or end_line >= len(lines):
        return ""
    start = int(getattr(node, "col_offset", 0))
    end = int(getattr(node, "end_col_offset", 0))
    if start_line == end_line:
        return _normalized_segment(_byte_slice(lines[start_line], start, end if end else None))
    selected = lines[start_line : end_line + 1]
    selected[0] = _byte_slice(selected[0], start, None)
    selected[-1] = _byte_slice(selected[-1], 0, end if end else None)
    return _normalized_segment("".join(selected))


def _byte_slice(value: str, start: int, end: int | None) -> str:
    return value.encode("utf-8")[start:end].decode("utf-8", errors="replace")


def _normalized_segment(value: str) -> str:
    return value.strip().replace("\n", " ")[:500]


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    return ""


def _call_root(node: ast.AST) -> str:
    name = _name(node)
    return name.split(".", 1)[0]


def _complexity(node: ast.AST) -> int:
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


def _format_annotation(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (ValueError, TypeError):
        return ""


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args: list[str] = []
    all_args = [*node.args.posonlyargs, *node.args.args]
    defaults = [None] * (len(all_args) - len(node.args.defaults)) + list(node.args.defaults)
    for arg, default in zip(all_args, defaults, strict=True):
        item = arg.arg
        annotation = _format_annotation(arg.annotation)
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
    returns = _format_annotation(node.returns)
    return f"{result} -> {returns}" if returns else result


def _class_signature(node: ast.ClassDef) -> str:
    bases = ", ".join(filter(None, (_name(base) for base in node.bases)))
    return f"class {node.name}({bases})" if bases else f"class {node.name}"


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        _name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        for decorator in node.decorator_list
    }


def _function_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    decorators = _decorator_names(node)
    if any(name.split(".")[-1] in {"get", "post", "put", "patch", "delete"} for name in decorators):
        return "api_endpoint"
    if node.name.startswith(("on_", "handle_")) or node.name.endswith("_handler"):
        return "event_handler"
    return "function"


def _module_summary(path: str, docstring: str, symbols: list[Symbol]) -> str:
    if docstring:
        return docstring.split("\n\n", 1)[0].replace("\n", " ")[:1_000]
    public = [symbol.name for symbol in symbols if not symbol.name.startswith("_")][:5]
    name = PurePosixPath(path).stem
    if public:
        return f"Python module {name} defining {', '.join(public)}"
    return f"Python module {name}"


def _responsibilities(symbols: Iterable[Symbol]) -> list[str]:
    result: list[str] = []
    for symbol in symbols:
        if symbol.name.startswith("_") or symbol.symbol_type == "method":
            continue
        if symbol.summary:
            result.append(f"{symbol.name}: {symbol.summary.splitlines()[0]}")
        else:
            result.append(f"Provide {symbol.symbol_type.replace('_', ' ')} {symbol.name}")
        if len(result) == 12:
            break
    return result


def _interfaces(visitor: _PythonVisitor) -> tuple[list[str], list[str], list[str]]:
    dependency_targets = {dependency.target for dependency in visitor.dependencies}
    inputs: list[str] = []
    outputs: list[str] = []
    side_effects: list[str] = []
    if any(target.startswith(("fastapi", "flask", "django")) for target in dependency_targets):
        inputs.append("HTTP requests")
        outputs.append("HTTP responses")
    if any(
        token in target
        for target in dependency_targets
        for token in ("sqlalchemy", "sqlite", "psycopg")
    ):
        side_effects.append("database access")
    if any(
        token in target
        for target in dependency_targets
        for token in ("httpx", "requests", "urllib")
    ):
        side_effects.append("network access")
    if any(target.startswith(("pathlib", "os", "shutil")) for target in dependency_targets):
        side_effects.append("filesystem access")
    return inputs, outputs, side_effects
