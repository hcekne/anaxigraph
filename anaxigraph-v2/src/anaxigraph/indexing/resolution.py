"""Resolve lexical names and imported members while keeping runtime dispatch uncertain."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from anaxigraph.indexing.python import Module, module_id


def _scopes(source: Module, scope: str) -> Iterator[str]:
    parent = scope
    while True:
        is_class = any(
            node.kind in {"class", "interface"} and node.data["qualified_name"] == parent
            for node in source.nodes
        )
        if parent == scope or not is_class:
            yield parent  # Class bodies are not enclosing lexical scopes of methods.
        if not parent:
            return
        parent = parent.rpartition(".")[0]


def _method_candidate(names: list[str], source: Module, scope: str) -> str | None:
    if names[0] not in {"self", "cls"} or len(names) != 2 or "." not in scope:
        return None
    qualified = scope.rpartition(".")[0] + "." + names[1]
    node = source.definitions.get(qualified)
    return node.id if node else None


def _member(module: Module, name: str, status: str) -> tuple[str | None, str]:
    if not name:
        return module_id(module.path), status
    node = module.definitions.get(name)
    return (node.id, status) if node else (None, "unresolved")


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

    def _module_import(
        self, module_name: str, suffix: list[str], source: Module
    ) -> tuple[str | None, str]:
        # import package.module binds package; consume the longest observed module prefix.
        for length in range(len(suffix), -1, -1):
            name = ".".join([module_name, *suffix[:length]])
            module, status = self.find_module(name, source)
            if module:
                return _member(module, ".".join(suffix[length:]), status)
        return None, "unresolved"

    def _symbol_import(
        self, module_name: str, imported: str, suffix: list[str], source: Module
    ) -> tuple[str | None, str]:
        module, status = self.find_module(module_name, source)
        if module:
            node = module.definitions.get(".".join([imported, *suffix]))
            if node:
                return node.id, status
        # `from package import member` can name a submodule instead of a symbol.
        submodule, substatus = self.find_module(f"{module_name}.{imported}".strip("."), source)
        if submodule:
            return _member(submodule, ".".join(suffix), substatus)
        return None, status if status == "ambiguous" else "unresolved"

    def target(self, expression_name: str, source: Module, scope: str) -> tuple[str | None, str]:
        names = expression_name.split(".")
        method = _method_candidate(names, source, scope)
        if method:
            return method, "ambiguous"  # The lexical method is only a possible dispatch target.
        for parent in _scopes(source, scope):
            if names[0] in source.bound.get(parent, set()):
                return None, "unresolved"  # Parameters/assignments shadow outer lexical names.
            qualified = ".".join(part for part in (parent, expression_name) if part)
            if qualified in source.definitions:
                node = source.definitions[qualified]
                count = sum(n.data.get("qualified_name") == qualified for n in source.nodes)
                return node.id, "ambiguous" if count > 1 else "resolved"
            binding = source.bindings.get(parent, {}).get(names[0])
            if binding:
                kind, module_name, imported = binding
                if kind == "module":
                    return self._module_import(module_name, names[1:], source)
                return self._symbol_import(module_name, imported, names[1:], source)
        return None, "unresolved"
