#!/usr/bin/env python3
"""Enforce production-size, function-complexity, and package-coupling ratchets."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from scripts.check_architecture import dependency_graph
    from scripts.quality_metrics import FunctionMetric, public_surface, scan_functions
else:
    from check_architecture import dependency_graph
    from quality_metrics import FunctionMetric, public_surface, scan_functions

DEFAULT_POLICY = Path("quality/maintainability-policy.json")


@dataclass(frozen=True, slots=True)
class QualityIssue:
    level: str
    issue_type: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "type": self.issue_type,
            "path": self.path,
            "message": self.message,
        }


def check_quality(
    root: Path,
    *,
    policy_path: Path = DEFAULT_POLICY,
    baseline: str | None = None,
    changed_paths: list[str] | None = None,
) -> list[QualityIssue]:
    """Return hard ratchet failures and review-level maintainability signals."""

    root = root.resolve()
    policy = json.loads((root / policy_path).read_text(encoding="utf-8"))
    metrics = scan_functions(root, policy)
    issues = _production_source_issues(root, policy)
    issues.extend(_function_issues(metrics, policy))
    graph = dependency_graph(
        root,
        source_root=Path(policy["source_root"]),
        package=policy["package"],
    )
    issues.extend(_coupling_issues(graph, policy))
    if baseline:
        paths = changed_paths if changed_paths is not None else _changed_paths(root, baseline)
        issues.extend(_interface_changes(root, baseline, paths, policy))
    return sorted(issues, key=lambda item: (item.level != "error", item.path, item.issue_type))


def _production_source_issues(root: Path, policy: dict[str, Any]) -> list[QualityIssue]:
    budget = policy.get("production_source_budget")
    if not budget:
        return []
    source_root = root / str(budget["root"])
    extensions = frozenset(str(item) for item in budget["extensions"])
    paths = sorted(
        path for path in source_root.rglob("*") if path.is_file() and path.suffix in extensions
    )
    current = sum(_physical_lines(path) for path in paths)
    baseline = int(budget["baseline_lines"])
    if current == baseline:
        return []
    issue_type = "production_source_growth" if current > baseline else "stale_source_baseline"
    direction = "grew above" if current > baseline else "fell below"
    return [
        QualityIssue(
            "error",
            issue_type,
            str(budget["root"]),
            f"production source is {current} lines and {direction} the {baseline}-line ratchet; "
            f"{'remove or simplify code' if current > baseline else f'lower baseline_lines to {current}'}",
        )
    ]


def _physical_lines(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for _line in handle)


def _function_issues(metrics: list[FunctionMetric], policy: dict[str, Any]) -> list[QualityIssue]:
    limits = policy["function_limits"]
    legacy = {
        tuple(identity.split("::", 1)): {
            "path": identity.split("::", 1)[0],
            "qualified_name": identity.split("::", 1)[1],
            "baseline_lines": values[0],
            "baseline_complexity": values[1],
        }
        for identity, values in policy.get("legacy_functions", {}).items()
    }
    current = {(item.path, item.qualified_name): item for item in metrics}
    issues: list[QualityIssue] = []
    for key, metric in current.items():
        exception = legacy.get(key)
        above_hard = (
            metric.lines > limits["hard_lines"] or metric.complexity > limits["hard_complexity"]
        )
        above_warning = (
            metric.lines > limits["warning_lines"]
            or metric.complexity > limits["warning_complexity"]
        )
        if exception is None and above_hard:
            issues.append(
                QualityIssue(
                    "error",
                    "function_budget",
                    metric.path,
                    f"{metric.qualified_name} is {metric.lines} lines / complexity "
                    f"{metric.complexity}; new functions are capped at "
                    f"{limits['hard_lines']} / {limits['hard_complexity']}",
                )
            )
        elif exception is None and above_warning:
            issues.append(
                QualityIssue(
                    "warning",
                    "function_budget",
                    metric.path,
                    f"{metric.qualified_name} is {metric.lines} lines / complexity "
                    f"{metric.complexity}; review cohesion before the hard ceiling",
                )
            )
        elif exception is not None:
            issues.extend(_legacy_function_issues(metric, exception, limits))
    for key, exception in legacy.items():
        if key not in current:
            issues.append(
                QualityIssue(
                    "error",
                    "stale_function_exception",
                    exception["path"],
                    f"remove stale exception for missing function {exception['qualified_name']}",
                )
            )
    return issues


def _legacy_function_issues(
    metric: FunctionMetric, exception: dict[str, Any], limits: dict[str, int]
) -> list[QualityIssue]:
    if metric.lines <= limits["hard_lines"] and metric.complexity <= limits["hard_complexity"]:
        return [
            QualityIssue(
                "error",
                "stale_function_exception",
                metric.path,
                f"remove stale exception for {metric.qualified_name}; it is now within policy",
            )
        ]
    if metric.lines > int(exception["baseline_lines"]) or metric.complexity > int(
        exception["baseline_complexity"]
    ):
        return [
            QualityIssue(
                "error",
                "function_growth",
                metric.path,
                f"{metric.qualified_name} grew above its {exception['baseline_lines']}-line / "
                f"complexity-{exception['baseline_complexity']} ratchet",
            )
        ]
    if metric.lines < int(exception["baseline_lines"]) or metric.complexity < int(
        exception["baseline_complexity"]
    ):
        return [
            QualityIssue(
                "error",
                "stale_function_baseline",
                metric.path,
                f"lower the recorded baseline for {metric.qualified_name} to "
                f"{metric.lines} lines / complexity {metric.complexity}",
            )
        ]
    return []


def _coupling_issues(graph: dict[str, set[str]], policy: dict[str, Any]) -> list[QualityIssue]:
    limits = policy["coupling_limits"]
    incoming = {module: 0 for module in graph}
    for targets in graph.values():
        for target in targets:
            incoming[target] += 1
    legacy = {
        module: {"fan_in": values[0], "fan_out": values[1]}
        for module, values in policy.get("legacy_coupling", {}).items()
    }
    issues: list[QualityIssue] = []
    for module, targets in graph.items():
        values = (incoming[module], len(targets))
        exception = legacy.get(module)
        if exception:
            baseline = (int(exception["fan_in"]), int(exception["fan_out"]))
            if values[0] > baseline[0] or values[1] > baseline[1]:
                issues.append(
                    QualityIssue(
                        "error",
                        "coupling_growth",
                        module,
                        f"fan-in/out {values[0]}/{values[1]} grew above {baseline[0]}/{baseline[1]}",
                    )
                )
            elif values != baseline:
                issues.append(
                    QualityIssue(
                        "error",
                        "stale_coupling_baseline",
                        module,
                        f"lower the fan-in/out baseline to {values[0]}/{values[1]}",
                    )
                )
        elif max(values) > limits["hard"]:
            issues.append(
                QualityIssue(
                    "error",
                    "coupling_budget",
                    module,
                    f"fan-in/out {values[0]}/{values[1]} exceeds the hard {limits['hard']} cap",
                )
            )
        elif max(values) > limits["warning"]:
            issues.append(
                QualityIssue(
                    "warning",
                    "coupling_budget",
                    module,
                    f"fan-in/out {values[0]}/{values[1]} is approaching the hard cap",
                )
            )
    for module in legacy.keys() - graph.keys():
        issues.append(
            QualityIssue("error", "stale_coupling_exception", module, "module no longer exists")
        )
    return issues


def _interface_changes(
    root: Path,
    baseline: str,
    paths: list[str],
    policy: dict[str, Any],
) -> list[QualityIssue]:
    package_root = f"{policy['source_root']}/{policy['package'].replace('.', '/')}"
    issues: list[QualityIssue] = []
    for path in sorted(set(paths)):
        if not path.startswith(f"{package_root}/") or not path.endswith(".py"):
            continue
        current_path = root / path
        current = (
            public_surface(current_path.read_text(encoding="utf-8"))
            if current_path.exists()
            else set()
        )
        previous_text = _git_text(root, baseline, path)
        previous = public_surface(previous_text) if previous_text is not None else set()
        added = sorted(current - previous)
        removed = sorted(previous - current)
        if added or removed:
            detail = f"public surface changed: +{len(added)} / -{len(removed)}"
            examples = [
                *(f"+ {item}" for item in added[:2]),
                *(f"- {item}" for item in removed[:2]),
            ]
            issues.append(
                QualityIssue(
                    "warning",
                    "public_interface_change",
                    path,
                    f"{detail}; {'; '.join(examples)}. Confirm compatibility and update contracts.",
                )
            )
    return issues


def _git_text(root: Path, revision: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def _changed_paths(root: Path, baseline: str, *, staged: bool = False) -> list[str]:
    command = ["git", "-C", str(root), "diff", "--name-only", "--diff-filter=ACMR"]
    command.extend(["--cached", baseline] if staged else [f"{baseline}...HEAD"])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout.splitlines()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--baseline", help="Git revision used for public-interface change reports")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    baseline = args.baseline or ("HEAD" if args.staged else None)
    changed = _changed_paths(root, baseline, staged=args.staged) if baseline else None
    issues = check_quality(
        root,
        policy_path=args.policy,
        baseline=baseline,
        changed_paths=changed,
    )
    errors = [item for item in issues if item.level == "error"]
    if args.json:
        print(json.dumps({"errors": len(errors), "issues": [item.as_dict() for item in issues]}))
    else:
        for item in issues:
            print(f"{item.level.upper()}: {item.path} — {item.message}")
        print(
            f"Code-quality check: {len(errors)} error(s), {len(issues) - len(errors)} warning(s)."
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
