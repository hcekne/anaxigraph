#!/usr/bin/env python3
"""Enforce physical-line ceilings and a shrinking legacy-module ratchet."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_POLICY = Path("quality/module-size-policy.json")


@dataclass(frozen=True, slots=True)
class SizeIssue:
    path: str
    lines: int
    level: str
    message: str
    suggestions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "lines": self.lines,
            "level": self.level,
            "message": self.message,
            "suggestions": list(self.suggestions),
        }


def check_repository(
    root: Path,
    *,
    policy_path: Path = DEFAULT_POLICY,
    paths: list[str] | None = None,
    today: date | None = None,
) -> list[SizeIssue]:
    root = root.resolve()
    policy = json.loads((root / policy_path).read_text(encoding="utf-8"))
    selected = paths if paths is not None else _tracked_files(root)
    legacy = {item["path"]: item for item in policy["legacy_exceptions"]}
    implementation_extensions = set(policy["implementation_extensions"])
    issues: list[SizeIssue] = []
    for raw_path in sorted(set(selected)):
        path = raw_path.replace("\\", "/")
        candidate = root / path
        if not candidate.is_file() or _excluded(path, policy):
            continue
        suffix = candidate.suffix.lower()
        if suffix in implementation_extensions:
            issues.extend(_check_implementation(candidate, path, policy, legacy.get(path)))
        elif suffix in {".css", ".html"}:
            issues.extend(_check_asset(candidate, path, policy))
    if paths is None:
        issues.extend(_validate_legacy_entries(root, policy, today or date.today()))
    return sorted(issues, key=lambda item: (item.level != "error", item.path, item.message))


def _check_implementation(
    candidate: Path,
    path: str,
    policy: dict[str, Any],
    exception: dict[str, Any] | None,
) -> list[SizeIssue]:
    lines = _physical_lines(candidate)
    test_file = _matches_any(path, policy["test_patterns"])
    limits = policy["limits"]
    hard_limit = limits["test_hard"] if test_file else limits["implementation_hard"]
    warning_limit = limits["test_warning"] if test_file else limits["implementation_warning"]
    issues: list[SizeIssue] = []
    if lines >= warning_limit and lines <= hard_limit:
        issues.append(
            SizeIssue(path, lines, "warning", f"approaching the {hard_limit}-line ceiling")
        )
    if lines <= hard_limit:
        if exception is not None:
            issues.append(
                SizeIssue(
                    path,
                    lines,
                    "error",
                    "legacy exception is stale; remove it now that the module is within policy",
                )
            )
        return issues
    suggestions = _extraction_suggestions(candidate)
    if test_file:
        issues.append(
            SizeIssue(
                path,
                lines,
                "error",
                f"test module exceeds the temporary {hard_limit}-line split threshold",
                suggestions,
            )
        )
    elif exception is None:
        issues.append(
            SizeIssue(
                path,
                lines,
                "error",
                f"new implementation module exceeds the hard {hard_limit}-line ceiling",
                suggestions,
            )
        )
    elif lines > int(exception["baseline_lines"]):
        issues.append(
            SizeIssue(
                path,
                lines,
                "error",
                f"legacy module grew above its {exception['baseline_lines']}-line ratchet",
                suggestions,
            )
        )
    elif lines < int(exception["baseline_lines"]):
        issues.append(
            SizeIssue(
                path,
                lines,
                "error",
                "module shrank; lower baseline_lines in the same change to preserve the ratchet",
                suggestions,
            )
        )
    return issues


def _check_asset(candidate: Path, path: str, policy: dict[str, Any]) -> list[SizeIssue]:
    lines = _physical_lines(candidate)
    warning = int(policy["limits"]["asset_warning"])
    hard = int(policy["limits"].get("asset_hard", 500))
    if lines > hard:
        return [
            SizeIssue(
                path,
                lines,
                "error",
                f"asset exceeds the hard {hard}-line ceiling",
                ("split the asset by responsibility and load the smaller parts explicitly",),
            )
        ]
    if lines < warning:
        return []
    return [
        SizeIssue(
            path,
            lines,
            "warning",
            f"asset bundle exceeds the {warning}-line review threshold",
        )
    ]


def _validate_legacy_entries(root: Path, policy: dict[str, Any], today: date) -> list[SizeIssue]:
    issues: list[SizeIssue] = []
    for item in policy["legacy_exceptions"]:
        path = item["path"]
        candidate = root / path
        if not candidate.is_file():
            issues.append(SizeIssue(path, 0, "error", "legacy exception points to a missing file"))
            continue
        expires = date.fromisoformat(item["expires_on"])
        if today > expires:
            issues.append(
                SizeIssue(
                    path,
                    _physical_lines(candidate),
                    "error",
                    f"legacy exception expired on {expires.isoformat()} ({item['removal_phase']})",
                )
            )
    return issues


def _extraction_suggestions(path: Path) -> tuple[str, ...]:
    if path.suffix == ".py":
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError):
            return ()
        boundaries = []
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                span = max(1, int(getattr(node, "end_lineno", node.lineno)) - node.lineno + 1)
                boundaries.append(
                    (span, type(node).__name__.removesuffix("Def").lower(), node.name)
                )
        return tuple(
            f"extract cohesive {kind} `{name}` ({span} lines)"
            for span, kind, name in sorted(boundaries, reverse=True)[:3]
        )
    return ("extract a cohesive route, renderer, state manager, or query family",)


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _excluded(path: str, policy: dict[str, Any]) -> bool:
    return any(fnmatch.fnmatchcase(path, item["pattern"]) for item in policy["exclusions"])


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode(errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def _staged_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode(errors="surrogateescape") for item in result.stdout.split(b"\0") if item]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--staged", action="store_true", help="Check staged implementation files")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    paths = _staged_files(root) if args.staged else None
    issues = check_repository(root, policy_path=args.policy, paths=paths)
    errors = [item for item in issues if item.level == "error"]
    if args.json:
        print(json.dumps({"errors": len(errors), "issues": [item.as_dict() for item in issues]}))
    else:
        for item in issues:
            print(f"{item.level.upper()}: {item.path}:{item.lines} — {item.message}")
            for suggestion in item.suggestions:
                print(f"  suggestion: {suggestion}")
        print(f"Module-size check: {len(errors)} error(s), {len(issues) - len(errors)} warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
