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
