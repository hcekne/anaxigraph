#!/usr/bin/env python3
"""Gate total and changed executable-line coverage from a Cobertura report."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_ZERO_REVISION = re.compile(r"^0+$")


@dataclass(frozen=True, slots=True)
class CoverageResult:
    total_percent: float
    changed_percent: float | None
    changed_executable_lines: int
    changed_covered_lines: int
    target_percent: float
    total_floor_percent: float
    passed: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_percent": self.total_percent,
            "changed_percent": self.changed_percent,
            "changed_executable_lines": self.changed_executable_lines,
            "changed_covered_lines": self.changed_covered_lines,
            "target_percent": self.target_percent,
            "total_floor_percent": self.total_floor_percent,
            "passed": self.passed,
            "reason": self.reason,
        }


def check_changed_coverage(
    root: Path,
    *,
    report: Path,
    base: str | None,
    target: float = 85.0,
    total_floor: float = 80.0,
    source_prefix: str = "src/anaxigraph/",
) -> CoverageResult:
    root = root.resolve()
    report_path = report if report.is_absolute() else root / report
    tree = ET.parse(report_path)
    coverage_root = tree.getroot()
    total_percent = float(coverage_root.attrib.get("line-rate", 0)) * 100
    executable = _executable_lines(coverage_root, source_prefix)
    if not base or _ZERO_REVISION.fullmatch(base) or not _revision_exists(root, base):
        passed = total_percent >= total_floor
        return CoverageResult(
            total_percent,
            None,
            0,
            0,
            target,
            total_floor,
            passed,
            "No comparable Git base; total coverage floor applied.",
        )

    changed = changed_lines(root, base, source_prefix=source_prefix)
    measured = {
        (path, line): hits
        for path, lines in executable.items()
        for line, hits in lines.items()
        if line in changed.get(path, set())
    }
    covered = sum(1 for hits in measured.values() if hits > 0)
    count = len(measured)
    changed_percent = covered / count * 100 if count else None
    changed_passed = changed_percent is None or changed_percent >= target
    total_passed = total_percent >= total_floor
    if count:
        reason = f"{covered}/{count} changed executable lines are covered."
    else:
        reason = "The diff contains no changed executable Python lines in the measured package."
    return CoverageResult(
        total_percent,
        changed_percent,
        count,
        covered,
        target,
        total_floor,
        changed_passed and total_passed,
        reason,
    )


def changed_lines(root: Path, base: str, *, source_prefix: str) -> dict[str, set[int]]:
    command = [
        "git",
        "-C",
        str(root),
        "diff",
        "--unified=0",
        "--no-ext-diff",
        f"{base}...HEAD",
        "--",
        source_prefix,
    ]
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    result: dict[str, set[int]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.startswith("+++ b/"):
            current = line.removeprefix("+++ b/")
            result.setdefault(current, set())
            continue
        match = _HUNK.match(line)
        if current is None or match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        result[current].update(range(start, start + count))
    return result


def _executable_lines(root: ET.Element, source_prefix: str) -> dict[str, dict[int, int]]:
    result: dict[str, dict[int, int]] = {}
    for class_node in root.findall(".//class"):
        filename = str(class_node.attrib.get("filename") or "").replace("\\", "/")
        path = _coverage_path(filename, source_prefix)
        lines = result.setdefault(path, {})
        for line_node in class_node.findall("./lines/line"):
            lines[int(line_node.attrib["number"])] = int(line_node.attrib.get("hits", "0"))
    return result


def _coverage_path(filename: str, source_prefix: str) -> str:
    clean = filename.removeprefix("./")
    if clean.startswith(source_prefix):
        return clean
    package_prefix = source_prefix.removeprefix("src/")
    if clean.startswith(package_prefix):
        return f"src/{clean}"
    return f"{source_prefix}{clean}"


def _revision_exists(root: Path, revision: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{revision}^{{commit}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, default=Path("coverage.xml"))
    parser.add_argument("--base")
    parser.add_argument("--target", type=float, default=85.0)
    parser.add_argument("--total-floor", type=float, default=80.0)
    parser.add_argument("--source-prefix", default="src/anaxigraph/")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = check_changed_coverage(
        args.root,
        report=args.report,
        base=args.base,
        target=args.target,
        total_floor=args.total_floor,
        source_prefix=args.source_prefix,
    )
    if args.json:
        print(json.dumps(result.as_dict()))
    else:
        changed = (
            "not applicable"
            if result.changed_percent is None
            else f"{result.changed_percent:.1f}% (target {result.target_percent:.1f}%)"
        )
        print(
            f"Total coverage: {result.total_percent:.1f}% (floor {result.total_floor_percent:.1f}%)"
        )
        print(f"Changed-code coverage: {changed}. {result.reason}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
