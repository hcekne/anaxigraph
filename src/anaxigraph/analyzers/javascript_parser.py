"""Tree-sitter loading, source access, recovery diagnostics, and stable hashing."""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterator

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Tree


@dataclass(frozen=True, slots=True)
class ParsedSource:
    content: str
    encoded: bytes
    line_starts: tuple[int, ...]
    tree: Tree
    root: Node
    diagnostics: tuple[dict[str, Any], ...]
    comments: tuple[Node, ...]

    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.encoded[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    def excerpt(self, node: Node | None, limit: int = 500) -> str:
        return " ".join(self.text(node).split())[:limit]

    @property
    def parse_error(self) -> str | None:
        if not self.diagnostics:
            return None
        first = self.diagnostics[0]
        return (
            f"Tree-sitter recovered {len(self.diagnostics)} syntax issue(s); first "
            f"{first['kind']} at line {first['line']}, column {first['column']}"
        )


@lru_cache(maxsize=1)
def parser_languages() -> dict[str, Language]:
    javascript = Language(tree_sitter_javascript.language())
    return {
        "javascript": javascript,
        "javascriptreact": javascript,
        "typescript": Language(tree_sitter_typescript.language_typescript()),
        "typescriptreact": Language(tree_sitter_typescript.language_tsx()),
    }


def parse_source(language: str, content: str) -> ParsedSource:
    encoded = content.encode("utf-8", errors="replace")
    line_starts = (0, *(index + 1 for index, value in enumerate(encoded) if value == 10))
    tree = Parser(parser_languages()[language]).parse(encoded)
    root = tree.root_node
    nodes = tuple(walk(root))
    diagnostics = tuple(
        _diagnostic(node, encoded, line_starts) for node in nodes if _is_diagnostic(node)
    )[:20]
    comments = tuple(node for node in nodes if node.type == "comment")
    return ParsedSource(content, encoded, line_starts, tree, root, diagnostics, comments)


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def structural_hash(parsed: ParsedSource) -> str:
    digest = hashlib.sha256()
    for node in walk(parsed.root):
        if node.type == "comment" or node.children:
            continue
        digest.update(node.type.encode())
        digest.update(b"\0")
        digest.update(parsed.encoded[node.start_byte : node.end_byte])
        digest.update(b"\0missing\0" if node.is_missing else b"\0")
    return digest.hexdigest()


def source_metrics(parsed: ParsedSource) -> tuple[int, int]:
    masked = bytearray(parsed.encoded)
    comment_lines: set[int] = set()
    for comment in parsed.comments:
        start, _column = _byte_position(parsed.line_starts, comment.start_byte)
        end_row, end_column = _byte_position(parsed.line_starts, comment.end_byte)
        stop = end_row - (1 if end_column == 0 else 0)
        comment_lines.update(range(start + 1, max(start, stop) + 2))
        for index in range(comment.start_byte, comment.end_byte):
            if masked[index] not in {10, 13}:
                masked[index] = 32
    code = masked.decode("utf-8", errors="replace")
    return sum(1 for line in code.splitlines() if line.strip()), len(comment_lines)


def leading_comment(parsed: ParsedSource) -> str:
    values = []
    for node in parsed.root.named_children:
        if node.type != "comment":
            break
        start_row, _column = _byte_position(parsed.line_starts, node.start_byte)
        if start_row > 7:
            break
        values.append(_clean_comment(parsed.text(node)))
    return " ".join(value for value in values if value)[:1_000]


def adjacent_comment(parsed: ParsedSource, node: Node) -> str:
    nearest = None
    node_start_row, _column = _byte_position(parsed.line_starts, node.start_byte)
    for comment in parsed.comments:
        if comment.end_byte > node.start_byte:
            break
        comment_end_row, _column = _byte_position(parsed.line_starts, comment.end_byte)
        gap = node_start_row - comment_end_row
        if gap <= 1:
            nearest = comment
    return _clean_comment(parsed.text(nearest))[:1_000] if nearest is not None else ""


def node_key(node: Node) -> tuple[int, int, str]:
    return node.start_byte, node.end_byte, node.type


def node_span(parsed: ParsedSource, node: Node) -> tuple[int, int, int, int]:
    start_row, start_column = _byte_position(parsed.line_starts, node.start_byte)
    end_row, end_column = _byte_position(parsed.line_starts, node.end_byte)
    return (
        start_row + 1,
        max(start_row + 1, end_row + 1),
        start_column,
        end_column,
    )


def literal_value(parsed: ParsedSource, node: Node | None) -> str | None:
    if node is None or node.type not in {"string", "template_string"}:
        return None
    if node.type == "template_string" and any(
        child.type in {"template_substitution", "substitution"} for child in node.named_children
    ):
        return None
    value = parsed.text(node)
    if len(value) >= 2 and value[0] in {"'", '"', "`"} and value[-1] == value[0]:
        return value[1:-1]
    return value or None


def signature_text(parsed: ParsedSource, node: Node, *, limit: int = 1_000) -> str:
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    return " ".join(parsed.encoded[node.start_byte : end].decode(errors="replace").split())[:limit]


def node_complexity(node: Node) -> int:
    branches = {
        "catch_clause",
        "do_statement",
        "for_in_statement",
        "for_statement",
        "if_statement",
        "switch_case",
        "ternary_expression",
        "while_statement",
    }
    score = 1
    for child in walk(node):
        if child.type in branches or child.type in {"&&", "||", "??"}:
            score += 1
    return score


def logical_lines(parsed: ParsedSource, node: Node) -> int:
    return max(1, sum(1 for line in parsed.text(node).splitlines() if line.strip()))


def _is_diagnostic(node: Node) -> bool:
    return node.type == "ERROR" or node.is_missing


def _diagnostic(
    node: Node,
    encoded: bytes,
    line_starts: tuple[int, ...],
) -> dict[str, Any]:
    text = encoded[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    start_row, start_column = _byte_position(line_starts, node.start_byte)
    end_row, end_column = _byte_position(line_starts, node.end_byte)
    return {
        "kind": "missing" if node.is_missing else "error",
        "node_type": node.type,
        "line": start_row + 1,
        "column": start_column,
        "end_line": end_row + 1,
        "end_column": end_column,
        "evidence": " ".join(text.split())[:300] or node.type,
    }


def _byte_position(line_starts: tuple[int, ...], offset: int) -> tuple[int, int]:
    row = bisect_right(line_starts, offset) - 1
    return row, offset - line_starts[row]


def _clean_comment(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("//"):
        stripped = stripped[2:]
    elif stripped.startswith("/*") and stripped.endswith("*/"):
        stripped = stripped[2:-2]
    return " ".join(part.lstrip("* ") for part in stripped.splitlines()).strip()
