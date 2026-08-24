"""Coverage report availability diagnostics for API consumers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.config import AnaxiGraphConfig


def coverage_diagnostics(
    row: dict[str, Any],
    config: AnaxiGraphConfig,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    root = Path(row["path"]).resolve()
    inputs = []
    for configured in config.coverage_files:
        path = Path(configured)
        candidate = path if path.is_absolute() else root / path
        inputs.append(
            {
                "path": configured,
                "exists": candidate.is_file(),
                "format": (
                    "lcov"
                    if candidate.name == "lcov.info"
                    else candidate.suffix.lstrip(".") or "unknown"
                ),
            }
        )
    imported = coverage.get("line_coverage") is not None
    available = sum(1 for item in inputs if item["exists"])
    return {
        **coverage,
        "state": "imported" if imported else "unmatched" if available else "missing",
        "required": config.coverage_required,
        "configured_inputs": inputs,
        "available_inputs": available,
    }
