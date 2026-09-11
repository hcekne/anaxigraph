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
    legacy.update({item["path"]: item for item in policy.get("cohesive_exceptions", [])})
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
        issues.extend(_validate_cohesive_entries(root, policy))
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
            SizeIssue(
                path,
                lines,
                "warning",
                f"approaching the {hard_limit}-line ceiling",
                _boundary_advice(candidate),
            )
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
    suggestions = _boundary_advice(candidate)
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
                f"new implementation module exceeds the hard {hard_limit}-line ceiling; "
                "split it or record a reviewed cohesive exception",
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


def _validate_cohesive_entries(root: Path, policy: dict[str, Any]) -> list[SizeIssue]:
    """Hold a retained boundary to a claim someone can check, not a number.

    A cohesive exception says a split would be worse. That is only reviewable if it names
    the decision the module hides and the change tasks that would have to touch both halves,
    so both are required and an entry whose module no longer needs it is an error.
    """

    issues: list[SizeIssue] = []
    for item in policy.get("cohesive_exceptions", []):
        path = item["path"]
        candidate = root / path
        if not candidate.is_file():
            issues.append(SizeIssue(path, 0, "error", "cohesive exception names a missing file"))
            continue
        lines = _physical_lines(candidate)
        if len(str(item.get("hidden_decision") or "").split()) < 5:
            issues.append(
                SizeIssue(path, lines, "error", "cohesive exception states no hidden decision")
            )
        if len(item.get("crossing_tasks") or []) < 2:
            issues.append(
                SizeIssue(
                    path,
                    lines,
                    "error",
                    "cohesive exception names fewer than two change tasks that a split would "
                    "spread across two modules",
                )
            )
        if not str(item.get("reviewed_on") or "").strip():
            issues.append(SizeIssue(path, lines, "error", "cohesive exception is not dated"))
    return issues


def _boundary_advice(path: Path) -> tuple[str, ...]:
    """Judge a split by whether one change would cross it, not by which parts are longest.

    Extracting the longest definition is a size argument. It can leave two modules that
    must be edited together, which is harder to change than the one module it replaced.
    So the question asked here is whether any part of this module is reached from nothing
    else in it. If nothing is, the boundary is doing its job and the honest record is a
    reviewed exception rather than a split.
    """

    if path.suffix != ".py":
        return ("name the routes, renderers, or query families that change for different reasons",)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return ()
    groups = sorted(_reference_groups(tree), key=lambda group: (-len(group), sorted(group)))
    if len(groups) < 2:
        return (
            "no seam found: every definition here is reached from the others, so a split would "
            "spread one change across two modules; record a reviewed cohesive exception instead",
        )
    return tuple(
        f"seam: {', '.join(sorted(group)[:4])}"
        f"{' and more' if len(group) > 4 else ''} is reached from nothing else in this module"
        for group in groups[1:4]
    )


def _reference_groups(tree: ast.Module) -> list[set[str]]:
    """Group the module's own names by what reaches what, shared constants included."""

    defined: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            defined[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined[target.id] = node
    parent = dict.fromkeys(defined)

    def root(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for name in defined:
        parent[name] = name
    for name, node in defined.items():
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in defined and child.id != name:
                parent[root(child.id)] = root(name)
    groups: dict[str, set[str]] = {}
    for name in defined:
        groups.setdefault(root(name), set()).add(name)
    return list(groups.values())


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
