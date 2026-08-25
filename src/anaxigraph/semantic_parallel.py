"""Bound independent model calls while preserving deterministic result order."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

_Input = TypeVar("_Input")
_Output = TypeVar("_Output")


def parallel_map(
    function: Callable[[_Input], _Output],
    values: Iterable[_Input],
    maximum: int,
) -> list[_Output]:
    items = list(values)
    workers = min(max(1, maximum), len(items))
    if workers <= 1:
        return [function(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(function, items))
