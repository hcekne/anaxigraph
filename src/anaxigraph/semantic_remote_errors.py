"""Describe remote worker failures by their causes, never by task-group headers."""

from __future__ import annotations

import os
import sys
import traceback
from typing import NoReturn

from anaxigraph.semantic_background_progress import PROGRESS_PATH_ENV

DEBUG_ENV = "ANAXIGRAPH_DEBUG"
_SURFACED_LEAF_TYPES = (ValueError, RuntimeError, OSError)


def leaf_exceptions(error: BaseException) -> list[BaseException]:
    """Flatten nested exception groups down to the exceptions that were actually raised."""
    if isinstance(error, BaseExceptionGroup):
        return [leaf for member in error.exceptions for leaf in leaf_exceptions(member)]
    return [error]


def failure_summary(error: BaseException) -> str:
    """Name every leaf cause of a failure; the task-group header never appears."""
    return "; ".join(f"{type(leaf).__name__}: {leaf}" for leaf in leaf_exceptions(error))


def log_failure(error: BaseException) -> None:
    """Write the full traceback to stderr for detached runs and debug sessions."""
    if not (os.environ.get(PROGRESS_PATH_ENV) or _enabled(os.environ.get(DEBUG_ENV))):
        return
    sys.stderr.write("".join(traceback.format_exception(error)))
    sys.stderr.flush()


def raise_remote_failure(error: Exception) -> NoReturn:
    """Re-raise a remote execution failure as its single operational cause when it has one."""
    log_failure(error)
    leaves = leaf_exceptions(error)
    if len(leaves) == 1 and isinstance(leaves[0], _SURFACED_LEAF_TYPES) and str(leaves[0]):
        if leaves[0] is error:
            raise error
        raise leaves[0] from error
    raise RuntimeError(f"Remote semantic execution failed: {failure_summary(error)}") from error


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() not in {"", "0", "false", "no", "off"}
