"""Keep portable descriptions short and remove currently excluded path evidence."""

from __future__ import annotations

from typing import Any

PATH_COLLECTIONS = {"evidence", "counter_evidence", "members", "paths", "owners", "affected_files"}


def concise_module(value: dict[str, Any]) -> dict[str, Any]:
    def statement(text: Any, maximum: int) -> str:
        text = str(text)
        return text if len(text) <= maximum else text[: maximum - 1].rstrip() + "…"

    return {
        "summary": statement(value.get("summary", ""), 600),
        **{
            name: [statement(item, 240) for item in value.get(name, [])[:count]]
            for name, count in (("responsibilities", 8), ("public_contracts", 12), ("evidence", 8))
        },
        "confidence": value.get("confidence", 0.5),
    }


def filter_excluded(value: Any, config: Any, field: str = "") -> Any:
    if isinstance(value, list):
        return [
            clean
            for item in value
            if not (
                field in PATH_COLLECTIONS
                and isinstance(item, str)
                and config.is_ignored(item.split(":", 1)[0])
            )
            if (clean := filter_excluded(item, config)) is not None
        ]
    if isinstance(value, dict):
        path = value.get("path")
        if isinstance(path, str) and config.is_ignored(path):
            return None
        return {key: filter_excluded(item, config, key) for key, item in value.items()}
    return value
