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

## Pattern-intelligence calibration

Two versioned seven-case sets exercise correct and unnecessary abstractions, justified and
low-cohesion modules, dynamic plugin/dead-code traps, consolidation lookalikes, and costly
migrations. The synthetic source repository and labels are in
`benchmarks/fixtures/pattern-calibration`; the real AnaxiGraph labels are in
`benchmarks/pattern-calibration/anaxigraph.json`.

After the corresponding repository has a current semantic and pattern map, run:

```bash
uv run anaxigraph patterns . \
  --calibrate benchmarks/pattern-calibration/anaxigraph.json \
  --json
```

With no explicit `--db`, the command selects the matching active sidecar and reports that index
authority. The output is `pattern-calibration-report-v1`; automation should inspect `passed` and
the individual failures. Runtime model and prompt versions are report provenance, not manifest
policy, so changing models never requires editing or invalidating the calibration contract itself.
