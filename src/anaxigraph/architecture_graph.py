"""Graph algorithms used by deterministic architecture analysis."""

from __future__ import annotations


def _strongly_connected(graph: dict[int, set[int]]) -> list[set[int]]:
    index = 0
    stack: list[int] = []
    indices: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    on_stack: set[int] = set()
    result: list[set[int]] = []

    def visit(node: int) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, set()):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component: set[int] = set()
            while stack:
                target = stack.pop()
                on_stack.remove(target)
                component.add(target)
                if target == node:
                    break
            result.append(component)

    all_nodes = set(graph) | {target for targets in graph.values() for target in targets}
    for node in all_nodes:
        if node not in indices:
            visit(node)
    return result
