"""Shared lexical vocabulary for bounded agent-scope ranking."""

from __future__ import annotations

import re

WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")

GOAL_STOPWORDS = frozenset(
    {
        "add",
        "and",
        "change",
        "create",
        "for",
        "from",
        "implement",
        "in",
        "of",
        "on",
        "the",
        "to",
        "update",
        "with",
    }
)


def split_camel(value: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
