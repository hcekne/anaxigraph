"""Deterministic Python AST extraction."""

from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import PurePosixPath

from anaxigraph.analyzer_capabilities import declare_capabilities
from anaxigraph.analyzers.python_evidence import extract_python_evidence
from anaxigraph.analyzers.python_module_semantics import (
    interfaces,
    module_summary,
    responsibilities,
)
from anaxigraph.analyzers.python_syntax import (
    DocstringStripper,
    call_root,
    class_signature,
    comment_lines,
    complexity,
    function_kind,
    function_signature,
    module_name,
    node_name,
    source_segment,
)
from anaxigraph.ir import module_identity, resolver_context, symbol_visibility
from anaxigraph.models import Dependency, FileAnalysis, Symbol


class PythonAnalyzer:
    name = "builtin-python-ast"
    version = "1"
    languages = frozenset({"python"})
    capabilities = declare_capabilities(
        name,
        version,
        "deep",
        deep=(
            "complexity",
            "exports",
            "imports",
            "inheritance",
            "module_documentation",
            "module_identity",
            "signatures",
            "source_spans",
            "symbol_documentation",
            "symbol_kind",
            "symbol_visibility",
            "symbols",
            "types",
        ),
        structural=(
            "annotations",
            "async_behavior",
            "calls",
            "constructors",
            "control_flow",
            "decorators",
            "entry_points",
            "error_handling",
            "generics",
            "mutation",
            "registrations",
            "test_relationships",
        ),
        heuristic=("concurrency", "side_effects"),
        limitations=(
            "Call relationships cover imported roots rather than complete local dispatch.",
            "Data-flow and runtime dispatch are not inferred from syntax alone.",
        ),
    )

    def analyze(self, path: str, content: str) -> FileAnalysis:
        identity = module_identity(path, "python")
        lines = content.splitlines()
        comments = comment_lines(content)
        loc = sum(
            1 for index, line in enumerate(lines, start=1) if line.strip() and index not in comments
        )
        try:
            tree = ast.parse(content, filename=path, type_comments=True)
        except (SyntaxError, ValueError) as exc:
            return _parse_failure(path, content, loc, len(comments), identity, exc, self)

        visitor = _PythonVisitor(path, content)
        visitor.visit(tree)
        structural_tree = DocstringStripper().visit(copy.deepcopy(tree))
        ast.fix_missing_locations(structural_tree)
        structural = ast.dump(structural_tree, annotate_fields=True, include_attributes=False)
        module_doc = ast.get_docstring(tree, clean=True) or ""
        public = [symbol.name for symbol in visitor.symbols if not symbol.name.startswith("_")]
        summary = module_summary(path, module_doc, visitor.symbols)
        module_responsibilities = responsibilities(visitor.symbols)
        inputs, outputs, side_effects = interfaces(visitor.dependencies)
        complexity = 1 + sum(max(0, symbol.complexity - 1) for symbol in visitor.symbols)
        return FileAnalysis(
            language="python",
            structural_hash=hashlib.sha256(structural.encode()).hexdigest(),
            lines_of_code=loc,
            comment_lines=len(comments),
            complexity=max(1, complexity),
            summary=summary,
            responsibilities=module_responsibilities,
            inputs=inputs,
            outputs=outputs,
            side_effects=side_effects,
            public_interfaces=public,
            symbols=visitor.symbols,
            dependencies=visitor.dependencies,
            evidence_facts=extract_python_evidence(path, content, tree),
            analyzer=self.name,
            metadata={"module_docstring": module_doc[:2_000]},
            module_identity=identity,
            exports=public,
            parse_status="parsed",
            analyzer_version=self.version,
            resolver_context=resolver_context(identity, import_aliases=visitor.import_aliases),
            analyzer_capabilities=self.capabilities,
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
        analyzer_capabilities=analyzer.capabilities,
    )


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, path: str, content: str) -> None:
        self.path = path
        self.content = content
        self.source_lines = content.splitlines(keepends=True)
        self.module = module_name(path)
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
        bases = {node_name(base) for base in node.bases}
        if any(base.endswith(("Base", "Model")) for base in bases):
            kind = "database_model"
        self._add_symbol(node, kind, class_signature(node), 1)
        for base in node.bases:
            target = node_name(base)
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
        kind = function_kind(node)
        if self.scope and kind == "function":
            kind = "method"
        self._add_symbol(node, kind, function_signature(node), complexity(node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        root = call_root(node.func)
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
        return source_segment(self.source_lines, node)

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
