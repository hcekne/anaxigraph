#!/usr/bin/env python3
"""Write a deterministic dependency and license inventory for an installed environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any


def installed_distributions() -> list[dict[str, Any]]:
    records = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        name = metadata.get("Name")
        if not name:
            continue
        records.append(
            {
                "name": name,
                "version": distribution.version,
                "license_expression": metadata.get("License-Expression"),
                "license": metadata.get("License"),
                "license_files": metadata.get_all("License-File", []),
                "project_urls": metadata.get_all("Project-URL", []),
            }
        )
    return sorted(records, key=lambda record: record["name"].casefold())


def report() -> dict[str, Any]:
    return {
        "schema": "anaxigraph-installed-distributions-v1",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "distributions": installed_distributions(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rendered = json.dumps(report(), indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
