"""Shared lexical vocabulary for bounded agent-scope ranking."""

from __future__ import annotations

import re

WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")

GOAL_STOPWORDS = frozenset(
    {
        "add",
        "and",
        "change",
        "code",
        "create",
        "file",
        "for",
        "from",
        "implement",
        "in",
        "make",
        "making",
        "more",
        "of",
        "on",
        "only",
        "repository",
        "that",
        "the",
        "to",
        "update",
        "whether",
        "with",
        "without",
    }
)

GOAL_TERM_GROUPS = (
    frozenset({"plan", "roadmap"}),
    frozenset({"architecture", "structure", "structural"}),
    frozenset({"compare", "comparison", "verification", "verify"}),
    frozenset({"better", "improve", "improved", "improvement"}),
    frozenset({"large", "larger", "oversized", "size"}),
    frozenset({"coupling", "cycle", "dependency", "tangle", "tangled"}),
    frozenset(
        {
            "cost",
            "duration",
            "elapsed",
            "measurement",
            "metric",
            "report",
            "spend",
            "status",
            "telemetry",
            "timing",
            "token",
            "usage",
        }
    ),
)

DOCUMENTATION_INTENT_TERMS = frozenset(
    {"changelog", "docs", "document", "documentation", "guide", "manual", "readme", "roadmap"}
)
TEST_INTENT_TERMS = frozenset({"test", "testing"})


def split_camel(value: str) -> str:
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return re.sub(r"[_-]+", " ", words)


def goal_terms(value: str) -> set[str]:
    """Return one normalized form per useful goal word plus small product-language aliases."""

    terms = set()
    for raw in WORD_PATTERN.findall(split_camel(value)):
        word = _singular_goal_word(raw.lower().replace("-", "_"))
        if word not in GOAL_STOPWORDS and len(word) > 1:
            terms.add(word)
    for group in GOAL_TERM_GROUPS:
        if terms & group:
            terms.update(group)
    return terms


def _singular_goal_word(word: str) -> str:
    if len(word) <= 4:
        return word
    if word.endswith("ies"):
        return f"{word[:-3]}y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def goal_artifact_type(value: str) -> str | None:
    """Recognize goals that explicitly name documentation or test work."""

    terms = goal_terms(value)
    matches = {
        artifact_type
        for artifact_type, intent_terms in (
            ("documentation", DOCUMENTATION_INTENT_TERMS),
            ("test", TEST_INTENT_TERMS),
        )
        if terms & intent_terms
    }
    return next(iter(matches)) if len(matches) == 1 else None
