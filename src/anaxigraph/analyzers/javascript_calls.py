"""Parser-backed call sites, preserving lexical shadowing and unknown dispatch."""

from __future__ import annotations

from anaxigraph.analyzers.javascript_parser import literal_value, node_span, walk
from anaxigraph.analyzers.javascript_symbols import _binding_names
from anaxigraph.call_graph_contract import CALLABLE_SYMBOL_KINDS

_FUNCTIONS = {
    "function_declaration",
    "function_expression",
    "arrow_function",
    "method_definition",
    "generator_function",
    "generator_function_declaration",
}


def call_sites(parsed, symbols, dependencies):
    result, bindings = [], {}
    for node in walk(parsed.root):
        if node.type not in {"call_expression", "new_expression"}:
            continue
        target = node.child_by_field_name("function") or node.child_by_field_name("constructor")
        name = parsed.text(target)
        root = name.split(".", 1)[0]
        binding = _lexical_binding(parsed, node, root, bindings)
        static = _static_target(target) and binding is not False
        imported = (binding or dependencies.symbol_aliases.get(root)) if static else None
        start, _end, column, _end_column = node_span(parsed, node)
        result.append(
            {
                "target": name,
                "line": start,
                "column": column,
                "caller": _caller(parsed, symbols, node),
                "binding": "import" if imported else "lexical" if static else "dynamic",
                "import_binding": imported,
                "qualified_target": "",
            }
        )
    return result


def _static_target(node):
    if node is None:
        return False
    if node.type in {"identifier", "this", "super"}:
        return True
    return node.type in {"member_expression", "optional_member_expression"} and _static_target(
        node.child_by_field_name("object")
    )


def _caller(parsed, symbols, node):
    start, _end, column, _end_column = node_span(parsed, node)
    point = (start, column)
    choices = [
        s
        for s in symbols
        if s.symbol_type in CALLABLE_SYMBOL_KINDS
        and (s.start_line, s.start_column) <= point < (s.end_line, s.end_column)
        and not (s.symbol_type == "api_endpoint" and point == (s.start_line, s.start_column))
    ]
    chosen = min(
        choices,
        key=lambda s: (s.end_line - s.start_line, s.end_column - s.start_column),
        default=None,
    )
    return chosen.qualified_name if chosen else ""


def _lexical_binding(parsed, node, root, cache):
    parent = node.parent
    while parent:
        if parent.type in _FUNCTIONS:
            params = parent.child_by_field_name("parameters") or parent.child_by_field_name(
                "parameter"
            )
            if root in _binding_names(parsed, params):
                return False
        if parent.type in {*_FUNCTIONS, "statement_block", "program"}:
            key = (parent.start_byte, parent.end_byte)
            if key not in cache:
                cache[key] = _stores(parsed, parent)
            if root in cache[key]:
                return cache[key][root]
        parent = parent.parent
    return None


def _stores(parsed, scope):
    result, stack = {}, list(scope.named_children)
    while stack:
        node = stack.pop()
        if node.type in _FUNCTIONS | {"class_declaration", "class"}:
            continue
        if node.type in {"variable_declarator", "assignment_expression"}:
            value = node.child_by_field_name("value") or node.child_by_field_name("right")
            name = node.child_by_field_name("name") or node.child_by_field_name("left")
            if value and value.type in _FUNCTIONS:
                continue
            if name and name.type in {"identifier", "object_pattern", "array_pattern"}:
                binding = _require_binding(parsed, value) if name.type == "identifier" else False
                for key in _binding_names(parsed, name):
                    result[key] = binding if key not in result or result[key] == binding else False
        stack.extend(node.named_children)
    return result


def _require_binding(parsed, value):
    if value is None or value.type != "call_expression":
        return False
    if parsed.text(value.child_by_field_name("function")) != "require":
        return False
    arguments = value.child_by_field_name("arguments")
    first = arguments.named_children[0] if arguments and arguments.named_children else None
    module = literal_value(parsed, first)
    return {"module": module, "name": "*"} if module else False
