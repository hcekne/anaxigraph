"""Pattern-neutral structural evidence extracted from Python syntax trees."""

from __future__ import annotations

import ast
from pathlib import PurePosixPath

from anaxigraph.analyzer_facts import AnalyzerFact

_CONTROL_FLOW = (ast.If, ast.For, ast.While, ast.Match)
_SIDE_EFFECT_ROOTS = {
    "aiohttp": "network",
    "httpx": "network",
    "open": "filesystem",
    "print": "console",
    "requests": "network",
    "shutil": "filesystem",
    "socket": "network",
    "subprocess": "process",
}
_CONCURRENCY_ROOTS = {"asyncio", "concurrent", "multiprocessing", "threading"}


def extract_python_evidence(path: str, content: str, tree: ast.AST) -> list[AnalyzerFact]:
    visitor = _EvidenceVisitor(path, content)
    visitor.visit(tree)
    return sorted(
        visitor.facts,
        key=lambda item: (item.subject, item.fact, item.line, item.value),
    )


class _EvidenceVisitor(ast.NodeVisitor):
    def __init__(self, path: str, content: str) -> None:
        self.path = path
        self.content = content
        self.module = _module_name(path)
        self.scope: list[str] = []
        self.facts: list[AnalyzerFact] = []
        self._seen: set[tuple[str, str, str, int]] = set()
        self._test_module = _is_test_path(path)

    @property
    def subject(self) -> str:
        return ".".join((self.module, *self.scope)).strip(".") or self.path

    def visit_Module(self, node: ast.Module) -> None:
        self._documentation(node, self.subject, "module_documentation")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        subject = self._qualified(node.name)
        self._documentation(node, subject, "symbol_documentation")
        self._decorators(node, subject)
        for base in node.bases:
            name = _name(base)
            if name:
                self._emit("inheritance", name, base, subject=subject)
                if name.rsplit(".", 1)[-1] in {"Generic", "Protocol"}:
                    self._emit("generics", name, base, subject=subject)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        subject = self._qualified(node.name)
        self._documentation(node, subject, "symbol_documentation")
        self._decorators(node, subject)
        self._annotations(node, subject)
        if isinstance(node, ast.AsyncFunctionDef):
            self._emit("async_behavior", "async-definition", node, subject=subject)
            self._emit("concurrency", "async-task", node, subject=subject, confidence=0.75)
        if node.name in {"__init__", "__new__"}:
            self._emit("constructors", node.name, node, subject=subject)
        if node.name.startswith("test_"):
            self._emit("entry_points", "test-case", node, subject=subject)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Import(self, node: ast.Import) -> None:
        if self._test_module:
            for item in node.names:
                self._emit(
                    "test_relationships",
                    item.name,
                    node,
                    subject=self.module,
                    confidence=0.9,
                )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._test_module:
            target = "." * node.level + (node.module or "")
            if target:
                self._emit(
                    "test_relationships",
                    target,
                    node,
                    subject=self.module,
                    confidence=0.9,
                )

    def visit_If(self, node: ast.If) -> None:
        self._emit("control_flow", "if", node)
        if _is_main_guard(node.test):
            self._emit("entry_points", "python-main-guard", node, subject=self.module)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._control(node, "for")

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._emit("async_behavior", "async-for", node)
        self._control(node, "async-for")

    def visit_While(self, node: ast.While) -> None:
        self._control(node, "while")

    def visit_Match(self, node: ast.Match) -> None:
        self._control(node, "match")

    def visit_Try(self, node: ast.Try) -> None:
        self._emit("error_handling", "try", node)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        value = _name(node.exc) or "raise"
        self._emit("error_handling", value, node)
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        self._emit("async_behavior", "await", node)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._emit("async_behavior", "async-context", node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        annotation = _unparse(node.annotation)
        if annotation:
            self._emit("annotations", annotation, node)
        self._mutation(node.target, node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._mutation(target, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._mutation(node.target, node, force=True)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _name(node.func)
        root = name.split(".", 1)[0]
        if root in _SIDE_EFFECT_ROOTS:
            self._emit(
                "side_effects",
                _SIDE_EFFECT_ROOTS[root],
                node,
                confidence=0.65,
            )
        if root in _CONCURRENCY_ROOTS:
            self._emit("concurrency", name, node, confidence=0.7)
        tail = name.rsplit(".", 1)[-1]
        if tail in {"add_route", "connect", "register", "route", "subscribe"}:
            self._emit("registrations", name, node)
        if tail in {"TypeVar", "NewType"}:
            self._emit("generics", name, node)
        self.generic_visit(node)

    def _control(self, node: ast.AST, value: str) -> None:
        self._emit("control_flow", value, node)
        self.generic_visit(node)

    def _decorators(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, subject: str
    ) -> None:
        for decorator in node.decorator_list:
            value = _name(decorator.func if isinstance(decorator, ast.Call) else decorator)
            if not value:
                continue
            self._emit("decorators", value, decorator, subject=subject)
            if value.rsplit(".", 1)[-1] in {
                "consumer",
                "handler",
                "listener",
                "register",
                "route",
            }:
                self._emit("registrations", value, decorator, subject=subject)
                self._emit("entry_points", "decorated-handler", decorator, subject=subject)

    def _annotations(self, node: ast.FunctionDef | ast.AsyncFunctionDef, subject: str) -> None:
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg:
            arguments.append(node.args.vararg)
        if node.args.kwarg:
            arguments.append(node.args.kwarg)
        for argument in arguments:
            value = _unparse(argument.annotation)
            if value:
                self._emit("annotations", f"{argument.arg}: {value}", argument, subject=subject)
        returns = _unparse(node.returns)
        if returns:
            self._emit("annotations", f"return: {returns}", node.returns, subject=subject)

    def _documentation(self, node: ast.AST, subject: str, fact: str) -> None:
        value = (
            ast.get_docstring(node, clean=True)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            else None
        )
        body = getattr(node, "body", ())
        if value and body:
            self._emit(fact, value.splitlines()[0][:500], body[0], subject=subject)

    def _mutation(self, target: ast.AST, node: ast.AST, *, force: bool = False) -> None:
        if force or isinstance(target, (ast.Attribute, ast.Subscript)):
            value = _name(target) or type(target).__name__.lower()
            self._emit("mutation", value, node)

    def _qualified(self, name: str) -> str:
        return ".".join((self.module, *self.scope, name)).strip(".")

    def _emit(
        self,
        fact: str,
        value: str,
        node: ast.AST,
        *,
        subject: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        line = int(getattr(node, "lineno", 0) or 0)
        owner = subject or self.subject
        key = (fact, owner, value, line)
        if key in self._seen:
            return
        self._seen.add(key)
        evidence = ast.get_source_segment(self.content, node) or type(node).__name__
        self.facts.append(
            AnalyzerFact(
                fact=fact,
                subject=owner,
                value=value[:500],
                line=line,
                end_line=int(getattr(node, "end_lineno", line) or line),
                evidence=" ".join(evidence.split())[:500],
                confidence=confidence,
            )
        )


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_test_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return "tests" in pure.parts or pure.name.startswith("test_") or pure.name.endswith("_test.py")


def _is_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    left = _name(node.left)
    right = node.comparators[0]
    return left == "__name__" and isinstance(right, ast.Constant) and right.value == "__main__"


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    if isinstance(node, ast.Call):
        return _name(node.func)
    return ""


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (TypeError, ValueError):
        return ""
