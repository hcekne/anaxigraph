"""Map named code parts onto AI-described file responsibilities."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "by",
    "code",
    "file",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "through",
    "to",
    "with",
}


def responsibility_slices(
    responsibilities: list[str],
    contracts: list[str],
    symbols: list[dict[str, Any]],
    destinations: list[str],
) -> tuple[list[dict[str, Any]], list[str], float]:
    """Group a symbol only when its own name or summary matches a described job."""

    grouped: list[list[dict[str, Any]]] = [[] for _ in responsibilities]
    unassigned = []
    for symbol in symbols[:100]:
        scores = [
            _overlap(responsibility, _symbol_text(symbol)) for responsibility in responsibilities
        ]
        best = max(scores, default=0)
        if best == 0 or scores.count(best) > 1:
            unassigned.append(str(symbol.get("name") or ""))
        else:
            grouped[scores.index(best)].append(_compact_symbol(symbol))
    slices = [
        {
            "job": responsibility,
            "symbols": selected[:30],
            "contracts_to_preserve": [
                contract for contract in contracts if _overlap(responsibility, contract)
            ],
            "destination": _matched_destination(responsibility, destinations),
        }
        for responsibility, selected in zip(responsibilities, grouped, strict=True)
        if selected
    ]
    coverage = (sum(len(group) for group in grouped) / len(symbols)) if symbols else 0.0
    return slices, unassigned[:30], coverage


def ordered_slices(path: str, slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract lower-contract jobs first and retain the caller-facing anchor."""

    anchor = max(
        range(len(slices)),
        key=lambda index: (
            len(slices[index]["contracts_to_preserve"]),
            len(slices[index]["symbols"]),
        ),
    )
    slices[anchor]["destination"] = {
        "status": "remain_in_file",
        "path": path,
        "reason": "Keep the job with the most caller-facing behavior in the original file.",
    }
    ordered = [item for index, item in enumerate(slices) if index != anchor] + [slices[anchor]]
    for index, item in enumerate(ordered, start=1):
        item["extraction_order"] = index
    return ordered


def destination_paths(
    semantic: dict[str, Any], assessment: dict[str, Any], current: str
) -> list[str]:
    values = [
        *(_strings(assessment.get("candidates"), 12)),
        *(_strings(semantic.get("similar_modules"), 12)),
    ]
    return [value for value in dict.fromkeys(values) if value != current and "/" in value]


def _matched_destination(responsibility: str, paths: list[str]) -> dict[str, str]:
    matches = sorted(
        ((_overlap(responsibility, PurePosixPath(path).stem), path) for path in paths),
        reverse=True,
    )
    if matches and matches[0][0] > 0:
        return {
            "status": "existing_module",
            "path": matches[0][1],
            "reason": "Its file name matches words in this responsibility.",
        }
    return {
        "status": "new_file_candidate",
        "path": "",
        "reason": (
            "No supplied existing module matches this job. Create a focused sibling file only "
            "after checking the architecture map for an honest extension point."
        ),
    }


def _compact_symbol(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(value.get("name") or "")[:300],
        "type": str(value.get("symbol_type") or "")[:100],
        "start_line": int(value.get("start_line") or 0),
        "end_line": int(value.get("end_line") or 0),
    }


def _symbol_text(value: dict[str, Any]) -> str:
    return " ".join(str(value.get(key) or "") for key in ("name", "signature", "summary"))


def _overlap(left: str, right: str) -> int:
    return len(_tokens(left) & _tokens(right))


def _tokens(value: str) -> set[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value)).replace("_", " ")
    return {word.lower() for word in _WORD.findall(expanded) if word.lower() not in _STOPWORDS}


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item)[:1_000] for item in value if str(item).strip()][:limit]
