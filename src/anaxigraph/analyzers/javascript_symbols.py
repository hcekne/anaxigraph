"""Parser-backed JavaScript and TypeScript symbol extraction."""

from __future__ import annotations

from pathlib import PurePosixPath

from tree_sitter import Node

from anaxigraph.analyzers.javascript_dependencies import DependencyFacts
from anaxigraph.analyzers.javascript_parser import (
    ParsedSource,
    literal_value,
    logical_lines,
    node_complexity,
    node_key,
    node_span,
    signature_text,
    walk,
)
from anaxigraph.ir import Symbol

_CLASS_NODES = {"abstract_class_declaration", "class", "class_declaration"}
_FUNCTION_NODES = {
    "function_declaration",
    "function_expression",
    "generator_function",
    "generator_function_declaration",
}
_METHOD_NODES = {"abstract_method_signature", "method_definition", "method_signature"}
_TYPE_NODES = {
    "enum_declaration": "enum",
    "interface_declaration": "interface",
    "internal_module": "namespace",
    "module": "namespace",
    "type_alias_declaration": "type_alias",
}


def extract_symbols(
    path: str,
    parsed: ParsedSource,
    dependencies: DependencyFacts,
) -> list[Symbol]:
    module = str(PurePosixPath(path).with_suffix("")).replace("/", ".")
    result = []
    for node in walk(parsed.root):
        result.extend(_declaration_symbols(module, parsed, node, dependencies))
        result.extend(_expression_symbols(module, parsed, node, dependencies))
    return _deduplicate(result)


def _declaration_symbols(
    module: str,
    parsed: ParsedSource,
    node: Node,
    dependencies: DependencyFacts,
) -> list[Symbol]:
    symbol = None
    if node.type in _CLASS_NODES:
        symbol = _class_symbol(module, parsed, node, dependencies)
    elif node.type in _FUNCTION_NODES and not _function_is_assigned(node):
        symbol = _function_symbol(module, parsed, node, dependencies)
    elif node.type in _METHOD_NODES:
        symbol = _method_symbol(module, parsed, node)
    elif node.type in _TYPE_NODES:
        symbol = _named_symbol(module, parsed, node, _TYPE_NODES[node.type], dependencies)
    return [symbol] if symbol else []


def _expression_symbols(
    module: str,
    parsed: ParsedSource,
    node: Node,
    dependencies: DependencyFacts,
) -> list[Symbol]:
    if node.type == "variable_declarator":
        return _variable_symbols(module, parsed, node, dependencies)
    symbol = None
    if node.type == "assignment_expression":
        symbol = _assignment_symbol(module, parsed, node, dependencies)
    elif node.type == "call_expression":
        symbol = _endpoint_symbol(module, parsed, node)
    elif node.type == "export_statement":
        symbol = _export_expression_symbol(module, parsed, node, dependencies)
    elif node.type == "public_field_definition":
        symbol = _field_symbol(module, parsed, node)
    return [symbol] if symbol else []


def _class_symbol(
    module: str,
    parsed: ParsedSource,
    node: Node,
    dependencies: DependencyFacts,
) -> Symbol | None:
    name = _declared_name(parsed, node, dependencies)
    if not name:
        return None
    return _symbol(
        module, parsed, node, "class", name, _visibility(parsed, node, name, dependencies)
    )


def _function_symbol(
    module: str,
    parsed: ParsedSource,
    node: Node,
    dependencies: DependencyFacts,
) -> Symbol | None:
    name = _declared_name(parsed, node, dependencies)
    if not name:
        return None
    kind = "react_component" if name[:1].isupper() and _contains_jsx(node) else "function"
    return _symbol(module, parsed, node, kind, name, _visibility(parsed, node, name, dependencies))


def _method_symbol(module: str, parsed: ParsedSource, node: Node) -> Symbol | None:
    name = parsed.text(node.child_by_field_name("name"))
    if not name:
        return None
    kind = "constructor" if name == "constructor" else "method"
    return _symbol(module, parsed, node, kind, name, _member_visibility(parsed, node, name))


def _named_symbol(
    module: str,
    parsed: ParsedSource,
    node: Node,
    kind: str,
    dependencies: DependencyFacts,
) -> Symbol | None:
    name = _declared_name(parsed, node, dependencies)
    if not name:
        return None
    return _symbol(module, parsed, node, kind, name, _visibility(parsed, node, name, dependencies))


def _variable_symbols(
    module: str,
    parsed: ParsedSource,
    node: Node,
    dependencies: DependencyFacts,
) -> list[Symbol]:
    value = node.child_by_field_name("value")
    callable_value = value is not None and value.type in {*_FUNCTION_NODES, "arrow_function"}
    if not callable_value and not _module_or_namespace_declaration(node):
        return []
    names = _binding_names(parsed, node.child_by_field_name("name"))
    result = []
    for name in names:
        if callable_value:
            kind = "react_component" if name[:1].isupper() and _contains_jsx(value) else "function"
            source_node = value
        else:
            parent = node.parent
            kind = (
                "constant"
                if parent and parsed.text(parent).lstrip().startswith("const ")
                else "variable"
            )
            source_node = node
        result.append(
            _symbol(
                module,
                parsed,
                source_node,
                kind,
                name,
                _visibility(parsed, node, name, dependencies),
                signature_node=node,
            )
        )
    return result


def _assignment_symbol(
    module: str,
    parsed: ParsedSource,
    node: Node,
    dependencies: DependencyFacts,
) -> Symbol | None:
    right = node.child_by_field_name("right")
    if right is None or right.type not in {*_FUNCTION_NODES, "arrow_function", *_CLASS_NODES}:
        return None
    name = dependencies.assigned_names.get(node_key(right))
    if not name or name == "default":
        name = _declared_name(parsed, right, dependencies) or "default"
    kind = "class" if right.type in _CLASS_NODES else "function"
    if kind == "function" and name[:1].isupper() and _contains_jsx(right):
        kind = "react_component"
    return _symbol(module, parsed, right, kind, name, "public", signature_node=node)


def _field_symbol(module: str, parsed: ParsedSource, node: Node) -> Symbol | None:
    value = node.child_by_field_name("value")
    if value is None or value.type not in {*_FUNCTION_NODES, "arrow_function"}:
        return None
    name = parsed.text(node.child_by_field_name("name"))
    if not name:
        return None
    kind = "react_component" if name[:1].isupper() and _contains_jsx(value) else "method"
    return _symbol(
        module,
        parsed,
        value,
        kind,
        name,
        _member_visibility(parsed, node, name),
        signature_node=node,
    )


def _export_expression_symbol(
    module: str,
    parsed: ParsedSource,
    node: Node,
    dependencies: DependencyFacts,
) -> Symbol | None:
    value = node.child_by_field_name("declaration") or node.child_by_field_name("value")
    if value is None or value.type not in {"arrow_function", "function_expression"}:
        return None
    name = dependencies.assigned_names.get(node_key(value))
    if name != "default":
        return None
    kind = "react_component" if _contains_jsx(value) else "function"
    return _symbol(module, parsed, value, kind, name, "public", signature_node=node)


def _endpoint_symbol(module: str, parsed: ParsedSource, node: Node) -> Symbol | None:
    function = node.child_by_field_name("function")
    if function is None or function.type not in {"member_expression", "optional_member_expression"}:
        return None
    owner = parsed.text(function.child_by_field_name("object"))
    method = parsed.text(function.child_by_field_name("property")).lower()
    if owner not in {"app", "router", "server"} or method not in {
        "delete",
        "get",
        "head",
        "options",
        "patch",
        "post",
        "put",
    }:
        return None
    arguments = node.child_by_field_name("arguments")
    route = literal_value(
        parsed, arguments.named_children[0] if arguments and arguments.named_children else None
    )
    if route is None:
        return None
    name = f"{method.upper()} {route}"
    return _symbol(module, parsed, node, "api_endpoint", name, "public")


def _symbol(
    module: str,
    parsed: ParsedSource,
    node: Node,
    kind: str,
    name: str,
    visibility: str,
    *,
    signature_node: Node | None = None,
) -> Symbol:
    start, end, column, end_column = node_span(parsed, node)
    owners = _owner_names(parsed, node)
    qualified = ".".join((module, *owners, name)).strip(".")
    return Symbol(
        symbol_type=kind,
        name=name,
        qualified_name=qualified,
        start_line=start,
        end_line=end,
        signature=signature_text(parsed, signature_node or node),
        complexity=node_complexity(node),
        logical_lines=logical_lines(parsed, node),
        visibility=visibility,
        start_column=column,
        end_column=end_column,
    )


def _declared_name(parsed: ParsedSource, node: Node, dependencies: DependencyFacts) -> str:
    name = parsed.text(node.child_by_field_name("name"))
    return name or dependencies.assigned_names.get(node_key(node), "")


def _owner_names(parsed: ParsedSource, node: Node) -> tuple[str, ...]:
    values = []
    current = node.parent
    while current is not None and current.type != "program":
        if (
            current.type in _CLASS_NODES | _FUNCTION_NODES | _METHOD_NODES | set(_TYPE_NODES)
            and not current.has_error
        ):
            name = parsed.text(current.child_by_field_name("name"))
            if name:
                values.append(name)
        current = current.parent
    return tuple(reversed(values))


def _visibility(
    parsed: ParsedSource,
    node: Node,
    name: str,
    dependencies: DependencyFacts,
) -> str:
    current = node
    while current is not None and current.type != "program":
        if node_key(current) in dependencies.exported_nodes:
            return "public"
        current = current.parent
    if name in dependencies.exports:
        return "public"
    return "private"


def _member_visibility(parsed: ParsedSource, node: Node, name: str) -> str:
    text = parsed.text(node).lstrip()
    if name.startswith("#") or text.startswith("private "):
        return "private"
    if text.startswith("protected "):
        return "protected"
    return "public"


def _function_is_assigned(node: Node) -> bool:
    parent = node.parent
    return bool(parent and parent.type in {"variable_declarator", "assignment_expression"})


def _module_or_namespace_declaration(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.type in _FUNCTION_NODES | _METHOD_NODES | _CLASS_NODES:
            return False
        if current.type in {"program", "internal_module", "module"}:
            return True
        current = current.parent
    return False


def _binding_names(parsed: ParsedSource, node: Node | None) -> list[str]:
    if node is None:
        return []
    if node.type in {"identifier", "shorthand_property_identifier_pattern", "type_identifier"}:
        return [parsed.text(node)]
    result = []
    for child in node.named_children:
        if (
            child.type in {"property_identifier", "property_identifier_pattern"}
            and node.type == "pair_pattern"
        ):
            continue
        result.extend(_binding_names(parsed, child))
    return list(dict.fromkeys(result))


def _contains_jsx(node: Node | None) -> bool:
    return bool(
        node
        and any(
            child.type in {"jsx_element", "jsx_fragment", "jsx_self_closing_element"}
            for child in walk(node)
        )
    )


def _deduplicate(items: list[Symbol]) -> list[Symbol]:
    result = []
    seen = set()
    for item in sorted(items, key=lambda value: (value.start_line, value.start_column, value.name)):
        key = (item.symbol_type, item.qualified_name, item.start_line, item.start_column)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result
