"""Module-level descriptions and coarse interfaces derived from Python facts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any


def module_summary(path: str, docstring: str, symbols: list[Any]) -> str:
    if docstring:
        return docstring.split("\n\n", 1)[0].replace("\n", " ")[:1_000]
    public = [symbol.name for symbol in symbols if not symbol.name.startswith("_")][:5]
    name = PurePosixPath(path).stem
    if public:
        return f"Python module {name} defining {', '.join(public)}"
    return f"Python module {name}"


def responsibilities(symbols: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for symbol in symbols:
        if symbol.name.startswith("_") or symbol.symbol_type == "method":
            continue
        if symbol.summary:
            result.append(f"{symbol.name}: {symbol.summary.splitlines()[0]}")
        else:
            result.append(f"Provide {symbol.symbol_type.replace('_', ' ')} {symbol.name}")
        if len(result) == 12:
            break
    return result


def interfaces(
    dependencies: Iterable[Any],
) -> tuple[list[str], list[str], list[str]]:
    targets = {dependency.target for dependency in dependencies}
    inputs: list[str] = []
    outputs: list[str] = []
    side_effects: list[str] = []
    if any(target.startswith(("fastapi", "flask", "django")) for target in targets):
        inputs.append("HTTP requests")
        outputs.append("HTTP responses")
    if any(token in target for target in targets for token in ("sqlalchemy", "sqlite", "psycopg")):
        side_effects.append("database access")
    if any(token in target for target in targets for token in ("httpx", "requests", "urllib")):
        side_effects.append("network access")
    if any(target.startswith(("pathlib", "os", "shutil")) for target in targets):
        side_effects.append("filesystem access")
    return inputs, outputs, side_effects
