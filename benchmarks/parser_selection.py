"""Reproducible feasibility benchmark for the Phase 11 parser decision."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

REPORT_VERSION = "parser-selection-v1"

CASES = {
    "browser-jsx": (
        "javascriptreact",
        "import React from 'react'; export const View = ({items}) => "
        "<main>{items.map(x => <p key={x.id}>{x.name}</p>)}</main>;",
        False,
    ),
    "node-commonjs": (
        "javascript",
        "const fs = require('node:fs'); module.exports = async function load(path) { "
        "try { return await fs.promises.readFile(path, 'utf8'); } "
        "catch (error) { throw error; } };",
        False,
    ),
    "monorepo-esm": (
        "javascript",
        "export {Client as ApiClient} from '@workspace/api'; "
        "import('./lazy.js').then(({start}) => start());",
        False,
    ),
    "decorators-typescript": (
        "typescript",
        "@injectable() export class Service<T extends Entity> implements Runner<T> { "
        "constructor(private readonly repo: Repo<T>) {} async run(value: T): Promise<T> { "
        "return this.repo.save(value); } }",
        False,
    ),
    "component-tsx": (
        "typescriptreact",
        "type Props = { title: string }; export function Card({title}: Props): JSX.Element { "
        "return <section aria-label={title}>{title}</section>; }",
        False,
    ),
    "recovery-typescript": (
        "typescript",
        "export interface Broken { value: string;\n"
        "export const usable = (x: number): number => x + 1;",
        True,
    ),
}


def _languages() -> dict[str, Language]:
    javascript = Language(tree_sitter_javascript.language())
    return {
        "javascript": javascript,
        "javascriptreact": javascript,
        "typescript": Language(tree_sitter_typescript.language_typescript()),
        "typescriptreact": Language(tree_sitter_typescript.language_tsx()),
    }


def measure_parser_selection(*, iterations: int = 100, large_repetitions: int = 5_000) -> dict:
    """Measure parser viability without asserting machine-specific speed budgets."""

    if iterations < 1 or large_repetitions < 1:
        raise ValueError("iterations and large_repetitions must be positive")
    languages = _languages()
    parsers = {name: Parser(language) for name, language in languages.items()}
    cases: dict[str, Any] = {}
    for name, (family, source, expects_recovery) in CASES.items():
        encoded = source.encode()
        durations = []
        root = None
        for _ in range(iterations):
            started = time.perf_counter_ns()
            root = parsers[family].parse(encoded).root_node
            durations.append((time.perf_counter_ns() - started) / 1_000_000)
        assert root is not None
        cases[name] = {
            "language": family,
            "source_bytes": len(encoded),
            "median_ms": round(statistics.median(durations), 4),
            "p95_ms": round(_percentile(durations, 0.95), 4),
            "has_error": root.has_error,
            "expects_recovery": expects_recovery,
            "root_type": root.type,
            "named_children": root.named_child_count,
            "passed": root.type == "program" and root.has_error == expects_recovery,
        }

    large_source = ((CASES["decorators-typescript"][1] + "\n") * large_repetitions).encode()
    large_durations = []
    large_root = None
    for _ in range(min(iterations, 5)):
        started = time.perf_counter_ns()
        large_root = parsers["typescript"].parse(large_source).root_node
        large_durations.append((time.perf_counter_ns() - started) / 1_000_000)
    assert large_root is not None
    report = {
        "report_schema_version": REPORT_VERSION,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "tree_sitter": version("tree-sitter"),
            "tree_sitter_javascript": version("tree-sitter-javascript"),
            "tree_sitter_typescript": version("tree-sitter-typescript"),
        },
        "grammars": {
            name: {
                "abi_version": language.abi_version,
                "semantic_version": language.semantic_version,
            }
            for name, language in languages.items()
        },
        "iterations": iterations,
        "cases": cases,
        "large_typescript": {
            "source_bytes": len(large_source),
            "median_ms": round(statistics.median(large_durations), 4),
            "has_error": large_root.has_error,
            "root_type": large_root.type,
        },
    }
    report["passed"] = all(item["passed"] for item in cases.values()) and not large_root.has_error
    return report


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--large-repetitions", type=int, default=5_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = measure_parser_selection(
        iterations=args.iterations,
        large_repetitions=args.large_repetitions,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
