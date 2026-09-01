"""Parser-backed JavaScript-family references, aliases, and export contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from tree_sitter import Node

from anaxigraph.analyzers.javascript_parser import (
    ParsedSource,
    literal_value,
    node_key,
    node_span,
    walk,
)
from anaxigraph.ir import Dependency


@dataclass(slots=True)
class DependencyFacts:
    dependencies: list[Dependency] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    exports: list[str] = field(default_factory=list)
    exported_nodes: set[tuple[int, int, str]] = field(default_factory=set)
    assigned_names: dict[tuple[int, int, str], str] = field(default_factory=dict)


def extract_dependencies(parsed: ParsedSource) -> DependencyFacts:
    facts = DependencyFacts()
    nodes = tuple(walk(parsed.root))
    for node in nodes:
        if node.type == "export_statement":
            _export_statement(parsed, node, facts)
        elif node.type == "assignment_expression":
            _commonjs_export(parsed, node, facts)
    for node in nodes:
        if node.type == "import_statement":
            _import_statement(parsed, node, facts)
        elif node.type == "call_expression":
            _call_reference(parsed, node, facts)
        elif node.type in {"class_heritage", "extends_type_clause"}:
            _inheritance(parsed, node, facts)
    facts.dependencies.extend(_imported_calls(parsed, nodes, facts.aliases))
    facts.dependencies = _deduplicate(facts.dependencies)
    facts.exports = list(dict.fromkeys(value for value in facts.exports if value))
    return facts


def _export_statement(parsed: ParsedSource, node: Node, facts: DependencyFacts) -> None:
    declaration = node.child_by_field_name("declaration") or node.child_by_field_name("value")
    text = parsed.text(node).lstrip()
    top_level = _module_level(node)
    _record_export_declaration(parsed, declaration, text, top_level, facts)
    _record_reexport(parsed, node, text, top_level, facts)


def _record_export_declaration(
    parsed: ParsedSource,
    declaration: Node | None,
    text: str,
    top_level: bool,
    facts: DependencyFacts,
) -> None:
    if declaration is not None:
        facts.exported_nodes.add(node_key(declaration))
        names = _declaration_names(parsed, declaration)
        if top_level and "export default" in text[:80]:
            facts.exports.append("default")
            facts.assigned_names[node_key(declaration)] = "default"
        elif top_level:
            facts.exports.extend(names)


def _record_reexport(
    parsed: ParsedSource,
    node: Node,
    text: str,
    top_level: bool,
    facts: DependencyFacts,
) -> None:
    source = node.child_by_field_name("source")
    target = literal_value(parsed, source)
    clause = next((item for item in node.named_children if item.type == "export_clause"), None)
    groups = _specifier_groups(
        parsed,
        clause,
        exported=True,
        force_type=text.startswith("export type"),
    )
    if clause is not None and top_level:
        facts.exports.extend(alias or name for _form, name, alias in groups)
    if target is None:
        return
    if not groups:
        form = "type_only" if text.startswith("export type") else "static"
        groups = [(form, "*", None)]
    for form in dict.fromkeys(item[0] for item in groups):
        names = tuple(item[1] for item in groups if item[0] == form)
        facts.dependencies.append(_dependency(parsed, node, target, "exports", form, names=names))


def _import_statement(parsed: ParsedSource, node: Node, facts: DependencyFacts) -> None:
    target = literal_value(parsed, node.child_by_field_name("source"))
    if target is None:
        return
    clause = next((item for item in node.named_children if item.type == "import_clause"), None)
    groups = _import_groups(parsed, clause, parsed.text(node).lstrip().startswith("import type"))
    if not groups:
        facts.dependencies.append(_dependency(parsed, node, target, "imports", "static"))
        return
    for form in dict.fromkeys(item[0] for item in groups):
        selected = [item for item in groups if item[0] == form]
        names = tuple(item[1] for item in selected)
        facts.dependencies.append(_dependency(parsed, node, target, "imports", form, names=names))
        for _, _original, local in selected:
            if local:
                facts.aliases[local] = target


def _call_reference(parsed: ParsedSource, node: Node, facts: DependencyFacts) -> None:
    function = node.child_by_field_name("function")
    name = parsed.text(function)
    if name not in {"require", "import"}:
        return
    arguments = node.child_by_field_name("arguments")
    first = arguments.named_children[0] if arguments and arguments.named_children else None
    target = literal_value(parsed, first)
    if name == "require":
        form = "commonjs" if target is not None else "dynamic_expression"
    else:
        form = "dynamic_literal" if target is not None else "dynamic_expression"
    target = target or f"dynamic:{parsed.excerpt(first) or 'expression'}"
    names = tuple(_bound_names(node.parent.child_by_field_name("name"))) if _assigned(node) else ()
    facts.dependencies.append(
        _dependency(
            parsed,
            node,
            target,
            "imports",
            form,
            names=names,
            confidence=0.7 if form == "dynamic_expression" else 1.0,
        )
    )
    if form != "dynamic_expression":
        for alias in names:
            facts.aliases[alias] = target


def _commonjs_export(parsed: ParsedSource, node: Node, facts: DependencyFacts) -> None:
    left = parsed.text(node.child_by_field_name("left"))
    name = _commonjs_name(left)
    if name is None:
        return
    facts.exports.append(name)
    right = node.child_by_field_name("right")
    if right is not None:
        facts.exported_nodes.add(node_key(right))
        facts.assigned_names[node_key(right)] = name


def _inheritance(parsed: ParsedSource, node: Node, facts: DependencyFacts) -> None:
    parent = node.parent
    if node.type == "class_heritage" and parent and parent.type == "interface_declaration":
        return
    inherited: list[tuple[str, bool]] = []
    for child in node.named_children:
        value = _type_name(parsed, child)
        type_only = child.type == "implements_clause" or bool(
            parent and parent.type == "interface_declaration"
        )
        if value and (value, type_only) not in inherited:
            inherited.append((value, type_only))
    for target, type_only in inherited:
        root = target.split(".", 1)[0]
        imported_target = facts.aliases.get(root)
        facts.dependencies.append(
            _dependency(
                parsed,
                node,
                imported_target or f"symbol:{target}",
                "extends",
                "type_only" if type_only else "static",
                names=(target.removeprefix(f"{root}."),) if imported_target else (),
                confidence=0.9,
            )
        )


def _imported_calls(
    parsed: ParsedSource,
    nodes: tuple[Node, ...],
    aliases: dict[str, str],
) -> list[Dependency]:
    result = []
    for node in nodes:
        if node.type not in {"call_expression", "new_expression"}:
            continue
        function = node.child_by_field_name("function") or node.child_by_field_name("constructor")
        root = _root_identifier(parsed, function)
        target = aliases.get(root)
        if target is None:
            continue
        result.append(
            _dependency(
                parsed,
                node,
                target,
                "calls",
                "static",
                names=(_call_tail(parsed, function),),
                confidence=0.85,
            )
        )
    return result


def _dependency(
    parsed: ParsedSource,
    node: Node,
    target: str,
    relationship: str,
    form: str,
    *,
    names: tuple[str, ...] = (),
    confidence: float = 1.0,
) -> Dependency:
    start, end, column, end_column = node_span(parsed, node)
    if node.has_error:
        confidence = min(confidence, 0.65)
    return Dependency(
        target=target,
        relationship_type=relationship,
        line=start,
        evidence=parsed.excerpt(node),
        confidence=confidence,
        names=tuple(value for value in names if value),
        column=column,
        end_line=end,
        end_column=end_column,
        reference_form=form,
    )


def _import_groups(
    parsed: ParsedSource,
    clause: Node | None,
    statement_type_only: bool,
) -> list[tuple[str, str, str | None]]:
    if clause is None:
        return []
    result = []
    for child in clause.named_children:
        if child.type == "identifier":
            result.append(
                ("type_only" if statement_type_only else "static", "default", parsed.text(child))
            )
        elif child.type == "namespace_import":
            local = next(
                (parsed.text(item) for item in child.named_children if item.type == "identifier"),
                None,
            )
            result.append(("type_only" if statement_type_only else "static", "*", local))
        elif child.type == "named_imports":
            result.extend(
                _specifier_groups(parsed, child, exported=False, force_type=statement_type_only)
            )
    return result


def _specifier_groups(
    parsed: ParsedSource,
    clause: Node | None,
    *,
    exported: bool,
    force_type: bool = False,
) -> list[tuple[str, str, str | None]]:
    if clause is None:
        return []
    expected = "export_specifier" if exported else "import_specifier"
    result = []
    for item in walk(clause):
        if item.type != expected:
            continue
        name = parsed.text(item.child_by_field_name("name"))
        alias = parsed.text(item.child_by_field_name("alias")) or None
        form = (
            "type_only"
            if force_type or parsed.text(item).lstrip().startswith("type ")
            else "static"
        )
        if name:
            result.append((form, name, alias or name))
    return result


def _declaration_names(parsed: ParsedSource, node: Node) -> list[str]:
    name = node.child_by_field_name("name")
    if name is not None:
        return _bound_names(name)
    if node.type in {"lexical_declaration", "variable_declaration"}:
        return [
            value
            for child in node.named_children
            if child.type == "variable_declarator"
            for value in _bound_names(child.child_by_field_name("name"))
        ]
    return []


def _bound_names(node: Node | None) -> list[str]:
    if node is None:
        return []
    if node.type in {"identifier", "shorthand_property_identifier_pattern", "type_identifier"}:
        return [node.text.decode("utf-8", errors="replace")]
    result = []
    for child in node.named_children:
        if (
            child.type in {"property_identifier", "property_identifier_pattern"}
            and node.type == "pair_pattern"
        ):
            continue
        result.extend(_bound_names(child))
    return list(dict.fromkeys(result))


def _assigned(node: Node) -> bool:
    return bool(node.parent and node.parent.type == "variable_declarator")


def _module_level(node: Node) -> bool:
    current = node.parent
    nested = {
        "abstract_class_declaration",
        "class",
        "class_declaration",
        "function_declaration",
        "function_expression",
        "interface_declaration",
        "internal_module",
        "method_definition",
        "module",
    }
    while current is not None and current.type != "program":
        if current.type in nested:
            return False
        current = current.parent
    return current is not None


def _commonjs_name(left: str) -> str | None:
    if left == "module.exports":
        return "default"
    for prefix in ("module.exports.", "exports."):
        if left.startswith(prefix):
            return left[len(prefix) :].split(".", 1)[0]
    return None


def _type_name(parsed: ParsedSource, node: Node) -> str:
    if node.type in {
        "identifier",
        "type_identifier",
        "member_expression",
        "nested_type_identifier",
    }:
        return parsed.text(node)
    for child in node.named_children:
        value = _type_name(parsed, child)
        if value:
            return value
    return ""


def _root_identifier(parsed: ParsedSource, node: Node | None) -> str:
    current = node
    while current is not None:
        if current.type in {"identifier", "type_identifier"}:
            return parsed.text(current)
        current = (
            current.child_by_field_name("object")
            or current.child_by_field_name("function")
            or current.child_by_field_name("constructor")
            or current.child_by_field_name("value")
        )
    return ""


def _call_tail(parsed: ParsedSource, node: Node | None) -> str:
    if node is None:
        return "call"
    property_node = node.child_by_field_name("property")
    return parsed.text(property_node) or parsed.text(node).split(".")[-1]


def _deduplicate(items: list[Dependency]) -> list[Dependency]:
    result = []
    seen = set()
    for item in items:
        key = (item.target, item.relationship_type, item.reference_form, item.line, item.column)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result
