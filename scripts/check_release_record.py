#!/usr/bin/env python3
"""Check release claims against their ledger; optionally verify publication with PyPI."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import yaml

GATES = {
    "publication": ("pending", "published"),
    "artifacts": ("pending", "verified"),
    "protected_merge": ("pending", "verified", "bypassed"),
    "production": ("pending", "verified", "failed", "rolled_back"),
}
COMPLETE = {"published", "verified"}
PENDING_LANGUAGE = re.compile(
    r"release candidate|do not interpret this draft|publication (?:is )?(?:still )?pending",
    re.IGNORECASE,
)


def check_release_record(root: Path, *, verify_pypi: bool = False) -> list[str]:
    root = root.resolve()
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
        version = project["version"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", version):
            raise ValueError("Invalid project.version for release record")
        lock = tomllib.loads((root / "uv.lock").read_text())
        versions = [item["version"] for item in lock["package"] if item["name"] == project["name"]]
        errors = [] if versions == [version] else ["uv.lock must match project.version exactly."]
        path = root / "docs" / "releases" / f"{version}.md"
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"{path.relative_to(root)} needs release-status front matter")
        metadata, body = text[4:].split("\n---\n", 1)
        record = yaml.safe_load(metadata)
        if not isinstance(record, dict) or record.get("version") != version:
            raise ValueError("release record version must match project.version")
        errors.extend(_gate_errors(root, record))
        if record.get("publication") == "published" and PENDING_LANGUAGE.search(body):
            errors.append(
                "Published release notes still contain draft/publication-pending language."
            )
        if verify_pypi:
            published = pypi_published(version)
            if published != (record.get("publication") == "published"):
                errors.append(
                    f"PyPI publication contradicts the {version} release record; update it."
                )
        return errors
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        return [f"Cannot verify release record: {exc}"]


def _gate_errors(root: Path, record: dict) -> list[str]:
    errors = []
    ledger = (root / record["ledger"]).resolve()
    if not ledger.is_relative_to(root) or not ledger.is_file():
        return ["Release ledger must be an existing file inside the repository."]
    text = ledger.read_text(encoding="utf-8")
    for gate, choices in GATES.items():
        status = record.get(gate)
        if status not in choices:
            errors.append(f"Unknown {gate} status {status!r}; expected one of {choices}.")
            continue
        evidence = record.get(f"{gate}_evidence", "")
        if status != "pending" and not re.fullmatch(r"https://[^\s/]+/\S+", str(evidence)):
            errors.append(f"{gate}={status} requires an HTTPS evidence link.")
        checkboxes = re.findall(
            rf"^- \[([ xX])\] <!-- release:{gate} -->", text, flags=re.MULTILINE
        )
        if len(checkboxes) != 1 or (checkboxes[0].lower() == "x") != (status in COMPLETE):
            errors.append(f"Ledger checkbox for {gate} must match status {status!r} exactly once.")
    return errors


def pypi_published(version: str) -> bool:
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", version):
        raise ValueError("Invalid release version for PyPI lookup")
    url = f"https://pypi.org/pypi/anaxigraph/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            value = json.load(response)
        if value["info"]["version"] != version:
            raise ValueError("PyPI returned a different version")
        return bool(value["urls"])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--verify-pypi", action="store_true")
    args = parser.parse_args(argv)
    errors = check_release_record(args.root, verify_pypi=args.verify_pypi)
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Release record check: {len(errors)} error(s).")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
