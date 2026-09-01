# AnaxiGraph benchmark suite

This directory owns the reproducible Phase 0 performance and correctness baseline. Generated
repositories and SQLite indexes always live in temporary directories; only their generator, seed,
expected manifest, compact mixed-language fixtures, and measured JSON reports are committed.

Run the complete baseline from the repository root:

```bash
.venv/bin/python -m benchmarks.baseline \
  --repository . \
  --synthetic-files 3000 \
  --history-frames 8 \
  --output benchmarks/results/baseline-schema6.json
```

The command runs the Python suite with coverage and uses the installed Playwright browser to time
the initial dashboard and graph render. For a quick local correctness pass without those optional
measurements:

```bash
.venv/bin/python -m benchmarks.baseline \
  --repository . \
  --synthetic-files 120 \
  --history-frames 8 \
  --skip-tests \
  --skip-dashboard \
  --output /tmp/anaxigraph-baseline-quick.json
```

Wall-clock and memory results describe the recorded environment and do not fail solely because one
machine is slower. Exact fixture counts do fail when generated history or indexed facts drift. CI
uses the 120-file smoke profile; release/performance work uses the complete 3,000-file profile.

The committed report is a baseline, not a performance promise. Phase 0 ratifies future regression
targets from ratios and measured work avoided; it does not encode this server's absolute duration
as a universal laptop threshold.

## Core coding loop at repository scale

The Phase 9 matrix repeats one placement task at 120, 1,000, and 3,000 files. It requires the same
eight relevant primary files, no unrelated primary files, a bounded scope packet with its
before-change record intact, the expected task path and placement, and the expected reverse impact.
It then changes one file to introduce a dependency cycle and changes that file again to resolve the
cycle. Each update must analyze one file and the comparison must classify both transitions.

```bash
uv run pytest tests/test_core_loop_scale.py

for size in 120 1000 3000; do
  uv run python -m benchmarks.baseline \
    --repository . --synthetic-files "$size" --history-frames 1 \
    --skip-tests --skip-dashboard \
    --output "/tmp/anaxigraph-core-loop-${size}.json"
done
```

The retained measurements are in
[`results/core-loop-scale-2026-08-25.json`](results/core-loop-scale-2026-08-25.json). Absolute time
is runner-specific. Candidate accuracy, unexpected files, payload bounds, baseline presence, and
one-file incremental work are the regression contracts.

## JavaScript and TypeScript parser selection

The Phase 11 feasibility benchmark parses representative browser JSX, Node CommonJS, monorepo ESM,
decorator/generic TypeScript, TSX, and malformed recovery input with the exact runtime and grammar
pins. It also parses an approximately 1 MB TypeScript input. Absolute duration is descriptive; root
shape, valid/error classification, grammar identity, and successful recovery are contracts.

```bash
uv run python -m benchmarks.parser_selection \
  --iterations 300 \
  --output benchmarks/results/phase11-parser-selection-2026-09-01.json
```

The repository-scale companion measures cold scan, unchanged reuse, one-file incremental scan, and
three-frame history import across 120, 1,000, and 3,000 parser-backed source files. Its correctness
contract requires zero parser errors, zero unchanged re-analysis, one-file incremental work, and
history analysis proportional to changed files rather than repository size.

```bash
uv run python -m benchmarks.javascript_analysis \
  --output benchmarks/results/phase11-javascript-analysis-2026-09-01.json
```

## First-user time to value

The Phase 3 gate exercises the assembled local product rather than timing helper functions. Each
trial creates a fresh Git repository, runs `anaxigraph up` with project-scoped Codex connection and
agent-funded semantics, waits for dashboard health, connects over real Streamable HTTP MCP, claims
semantic work, fetches every requested evidence page, and submits the first validated dossier.

```bash
uv run python -m benchmarks.first_user \
  --runs 3 \
  --output /tmp/anaxigraph-first-user.json
```

The gate requires a median below five minutes to a usable dashboard and below ten minutes to the
first stored dossier. The deliberately generous product budgets catch hangs and catastrophic
first-run regressions; the report retains actual sub-step durations for tighter future ratchets.

The companion container contract builds the current Dockerfile, generates a real sidecar, reaches
health and AnaxiMCP, and inspects the running container's read-only mount, read-only root,
capability drop, no-new-privileges, and loopback binding:

```bash
uv run python scripts/smoke_container_sidecar.py
```
