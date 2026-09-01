"""Small JSON-with-comments reader shared by configuration analyzers."""

from __future__ import annotations

import json
import re
from typing import Any


def load_json_document(content: str) -> Any:
    """Parse JSON or common JSONC without executing repository tooling."""

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return json.loads(jsonc_to_json(content))


def jsonc_to_json(content: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", _without_comments(content))


def _without_comments(content: str) -> str:
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(content):
        if state == "code":
            state, quote, advance = _code_character(content, index, output)
        elif state == "string":
            state, quote, advance = _string_character(content, index, output, quote)
        elif state == "line_comment":
            state, advance = _line_comment_character(content, index, output)
        else:
            state, advance = _block_comment_character(content, index)
        index += advance
    return "".join(output)


def _code_character(content: str, index: int, output: list[str]) -> tuple[str, str, int]:
    char = content[index]
    following = content[index + 1] if index + 1 < len(content) else ""
    if char in {'"', "'"}:
        output.append(char)
        return "string", char, 1
    if char == "/" and following in {"/", "*"}:
        return ("line_comment" if following == "/" else "block_comment"), "", 2
    output.append(char)
    return "code", "", 1


def _string_character(
    content: str, index: int, output: list[str], quote: str
) -> tuple[str, str, int]:
    char = content[index]
    output.append(char)
    if char == "\\" and index + 1 < len(content):
        output.append(content[index + 1])
        return "string", quote, 2
    if char == quote:
        return "code", "", 1
    return "string", quote, 1


def _line_comment_character(content: str, index: int, output: list[str]) -> tuple[str, int]:
    if content[index] == "\n":
        output.append("\n")
        return "code", 1
    return "line_comment", 1


def _block_comment_character(content: str, index: int) -> tuple[str, int]:
    if content[index : index + 2] == "*/":
        return "code", 2
    return "block_comment", 1
