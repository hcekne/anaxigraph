"""Pattern-neutral evidence extracted from JavaScript-family syntax trees."""

from __future__ import annotations

from pathlib import PurePosixPath

from tree_sitter import Node

from anaxigraph.analyzer_facts import AnalyzerFact
from anaxigraph.analyzers.javascript_dependencies import DependencyFacts
from anaxigraph.analyzers.javascript_parser import (
    ParsedSource,
    adjacent_comment,
    leading_comment,
    node_span,
    walk,
)
from anaxigraph.ir import Symbol

_CONTROL = {
    "do_statement": "do",
    "for_in_statement": "for-in",
    "for_statement": "for",
    "if_statement": "if",
    "switch_case": "case",
    "ternary_expression": "conditional",
    "while_statement": "while",
}
_ERRORS = {
    "catch_clause": "catch",
    "finally_clause": "finally",
    "throw_statement": "throw",
    "try_statement": "try",
}
_SIDE_EFFECTS = {
    "axios": "network",
    "console": "console",
    "fetch": "network",
    "fs": "filesystem",
    "localStorage": "browser-storage",
    "process": "process",
    "sessionStorage": "browser-storage",
}
_CONCURRENCY = {"Promise", "Worker", "queueMicrotask", "setImmediate", "setTimeout"}
_REGISTRATIONS = {
    "addEventListener",
    "addListener",
    "connect",
    "listen",
    "on",
    "register",
    "route",
    "subscribe",
    "use",
}


def extract_javascript_evidence(
    path: str,
    parsed: ParsedSource,
    symbols: list[Symbol],
    dependencies: DependencyFacts,
    *,
    typescript: bool,
) -> list[AnalyzerFact]:
    evidence = _Evidence(path, parsed, symbols)
    documentation = leading_comment(parsed)
    if documentation:
        evidence.emit_at("module_documentation", documentation, evidence.module, 1, documentation)
    evidence.symbol_documentation()
    for node in walk(parsed.root):
        evidence.visit(node, typescript=typescript)
    if _is_test_path(path):
        for dependency in dependencies.dependencies:
            if dependency.relationship_type == "imports":
                evidence.emit_at(
                    "test_relationships",
                    dependency.target,
                    evidence.module,
                    dependency.line,
                    dependency.evidence,
                    confidence=dependency.confidence,
                )
    return sorted(
        evidence.facts,
        key=lambda item: (item.subject, item.fact, item.line, item.value),
    )


class _Evidence:
    def __init__(self, path: str, parsed: ParsedSource, symbols: list[Symbol]) -> None:
        self.path = path
        self.parsed = parsed
        self.symbols = symbols
        self.module = str(PurePosixPath(path).with_suffix("")).replace("/", ".")
        self.facts: list[AnalyzerFact] = []
        self.seen: set[tuple[str, str, str, int]] = set()

    def symbol_documentation(self) -> None:
        nodes = tuple(walk(self.parsed.root))
        for symbol in self.symbols:
            node = next(
                (
                    item
                    for item in nodes
                    if node_span(self.parsed, item)[0] == symbol.start_line
                    and symbol.name in self.parsed.text(item)[:200]
                ),
                None,
            )
            value = adjacent_comment(self.parsed, node) if node is not None else ""
            if value:
                self.emit_at(
                    "symbol_documentation",
                    value,
                    symbol.qualified_name,
                    symbol.start_line,
                    value,
                )

    def visit(self, node: Node, *, typescript: bool) -> None:
        if self._declaration_evidence(node, typescript=typescript):
            return
        if self._behavior_evidence(node):
            return
        self._effect_evidence(node)

    def _declaration_evidence(self, node: Node, *, typescript: bool) -> bool:
        node_type = node.type
        if node_type == "decorator":
            self.emit("decorators", self.parsed.text(node).lstrip("@"), node)
        elif typescript and node_type == "type_annotation":
            self.emit("annotations", self.parsed.text(node).lstrip(": "), node)
        elif typescript and node_type == "type_parameters":
            self.emit("generics", self.parsed.text(node), node)
        elif typescript and node_type in {
            "enum_declaration",
            "interface_declaration",
            "internal_module",
            "module",
            "type_alias_declaration",
        }:
            self.emit("types", self._declared_name(node) or node_type, node)
        elif node_type in {"class_heritage", "extends_type_clause", "implements_clause"}:
            self.emit("inheritance", self.parsed.excerpt(node), node)
        elif node_type == "method_definition" and self._declared_name(node) == "constructor":
            self.emit("constructors", "constructor", node)
        else:
            return False
        return True

    def _behavior_evidence(self, node: Node) -> bool:
        node_type = node.type
        if node_type == "await_expression":
            self.emit("async_behavior", "await", node)
        elif node_type in {
            "arrow_function",
            "function_declaration",
            "function_expression",
            "generator_function",
            "generator_function_declaration",
            "method_definition",
        } and any(child.type == "async" for child in node.children):
            self.emit("async_behavior", "async-definition", node)
        elif node_type in _CONTROL:
            self.emit("control_flow", _CONTROL[node_type], node)
        elif node_type in _ERRORS:
            self.emit("error_handling", _ERRORS[node_type], node)
        else:
            return False
        return True

    def _effect_evidence(self, node: Node) -> None:
        node_type = node.type
        if node_type in {"assignment_expression", "augmented_assignment_expression"}:
            left = node.child_by_field_name("left")
            if left is not None and left.type in {
                "member_expression",
                "optional_member_expression",
                "subscript_expression",
            }:
                self.emit("mutation", self.parsed.excerpt(left), node)
        elif node_type == "update_expression":
            self.emit("mutation", self.parsed.excerpt(node), node)
        elif node_type in {"call_expression", "new_expression"}:
            self._call(node)

    def _call(self, node: Node) -> None:
        function = node.child_by_field_name("function") or node.child_by_field_name("constructor")
        name = self.parsed.text(function)
        root = _call_root(name)
        tail = _call_tail(name)
        if root in _SIDE_EFFECTS:
            self.emit("side_effects", _SIDE_EFFECTS[root], node, confidence=0.7)
        if root in _CONCURRENCY or tail in _CONCURRENCY:
            self.emit("concurrency", name, node, confidence=0.75)
        if tail in _REGISTRATIONS:
            self.emit("registrations", name, node, confidence=0.9)
            if tail in {"listen", "route"}:
                self.emit("entry_points", "registered-handler", node, confidence=0.85)
        if root in {"describe", "it", "test"}:
            self.emit("entry_points", "test-case", node)
        if root in {"app", "router", "server"} and tail in {
            "delete",
            "get",
            "head",
            "options",
            "patch",
            "post",
            "put",
        }:
            self.emit("entry_points", f"HTTP {tail.upper()}", node)

    def emit(
        self,
        fact: str,
        value: str,
        node: Node,
        *,
        confidence: float = 1.0,
    ) -> None:
        start, end, _column, _end_column = node_span(self.parsed, node)
        self.emit_at(
            fact,
            value,
            self._subject(node),
            start,
            self.parsed.excerpt(node),
            end_line=end,
            confidence=min(confidence, 0.65) if node.has_error else confidence,
        )

    def emit_at(
        self,
        fact: str,
        value: str,
        subject: str,
        line: int,
        evidence: str,
        *,
        end_line: int | None = None,
        confidence: float = 1.0,
    ) -> None:
        normalized = " ".join(value.split())[:500]
        key = (fact, subject, normalized, line)
        if not normalized or key in self.seen:
            return
        self.seen.add(key)
        self.facts.append(
            AnalyzerFact(
                fact=fact,
                subject=subject,
                value=normalized,
                line=max(0, line),
                end_line=max(line, end_line or line),
                evidence=" ".join(evidence.split())[:500] or normalized,
                confidence=confidence,
            )
        )

    def _subject(self, node: Node) -> str:
        line = node_span(self.parsed, node)[0]
        candidates = [item for item in self.symbols if item.start_line <= line <= item.end_line]
        if not candidates:
            return self.module
        return min(candidates, key=lambda item: item.end_line - item.start_line).qualified_name

    def _declared_name(self, node: Node) -> str:
        return self.parsed.text(node.child_by_field_name("name"))


def _call_root(name: str) -> str:
    return name.split(".", 1)[0].split("[", 1)[0]


def _call_tail(name: str) -> str:
    return name.rsplit(".", 1)[-1].split("[", 1)[0]


def _is_test_path(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    return bool(
        "test" in pure.parts or "tests" in pure.parts or ".test." in name or ".spec." in name
    )
