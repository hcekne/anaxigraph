# AnaxiGraph benchmark suite

## Repository reader tasks (opt-in model run)

`understandability` compares three maintenance tasks across two behaviorally equivalent synthetic
implementations: locate validation, trace an invalid order, and add express shipping. Every trial
uses a fresh ephemeral Codex CLI session with user configuration ignored. It receives only one
implementation and the same thin glossary, decision, and navigation docs; expected answers and
change checks are withheld. Generated changes run in a restricted Docker container with no network
or writable host mount. The image must already exist locally; its resolved image ID is recorded.

```bash
uv run python -m benchmarks.understandability \
  --model YOUR_MODEL --reasoning-effort YOUR_EFFORT --trials 3 \
  --verification-image YOUR_LOCAL_PYTHON_IMAGE \
  --output /tmp/anaxigraph-reader-trials.json
```

The report retains each answer, correctness, errors, reported token usage, and reader/total time.
Compare correctness first and effort across successful repeated trials with the same runtime.
All fixture source is supplied, so this is a bounded maintenance experiment rather than a search
or navigation study. It establishes neither a universal code-quality score nor production reader
performance. Unit tests verify the harness and behavioral checks; they are not model trial results.

## Architectural judgment (opt-in model run)

`architecture_judgment` evaluates ten controlled positive, negative, and uncertain
cases through the production pattern-assessment and independent-review contracts.
The agent-specific cases cover retaining a sufficient five-field map, withholding code changes
when relevant context is missing, and recognizing a callable strategy without adding a hierarchy.
Expected answers are withheld from the model. Protocol unit tests do not establish
model accuracy; retain a real run before claiming the architecture gate passed:

```bash
uv run python -m benchmarks.architecture_judgment \
  --model gpt-6-astra --reasoning-effort max --parallel 2 \
  --output /tmp/anaxigraph-agent-judgment.json
```

The report records known-positive misses, unsupported change advice, covered scope
levels, case-level rationale, duration, request bytes, and reported or unknown token
usage. Monetary cost remains unknown unless supplied by the executor. These small
synthetic cases test judgment under stated facts, not recognition of every pattern
or the correctness of all production recommendations. Candidate-selection and
representative-evidence tests are separate deterministic checks.
The saved 0.5.0 result covers the original seven cases, not the three additions. A new model run
requires an explicit budget and a fresh output path; this fixture update is not a passing result.

## Real architecture tasks, graded blind (opt-in model run)

`architecture_tasks` asks real questions this repository actually faced, at the revision it
faced them, under the same output-token budget the recorded answer was written to. A real
answer is prose, so it is not graded by matching a label. Each task carries a recorded
reference answer and the key points a knowledgeable answer would name.

Running the tasks writes two files. The grading sheet holds the question, the key points,
and both answers under the labels `answer-1` and `answer-2`; nothing in it says which answer
came from where. The answers file holds that mapping. Grade the sheet without opening the
answers file, then assemble the report:

```bash
uv run python -m benchmarks.architecture_tasks run \
  --model YOUR_MODEL --reasoning-effort YOUR_EFFORT \
  --sheet /tmp/anaxigraph-task-sheet.json \
  --answers /tmp/anaxigraph-task-answers.json

uv run python -m benchmarks.architecture_tasks report \
  --sheet /tmp/anaxigraph-task-sheet.json \
  --output /tmp/anaxigraph-task-report.json
```

Labels come from a digest of the task id and revision, so the same task is labelled the same
way on every run and the model does not sit in the same slot across tasks. A grade that
names a key point nobody recorded is not counted.

The report leads with what each answer covered and what it missed, names every unsupported
claim, and lists the tasks the grader was unsure about. It withholds any headline rate while
a task was already acted on, while a reference answer was not written by a human, or while
the grader was unsure. The committed fixture is in exactly that state today: four real tasks,
one human reference answer, none of them held out, because the repository has already changed
in response to all four. That makes it a rehearsal of the protocol and not a measurement.
Recording a held-out task with a human reference answer before the work is done is what turns
it into one.

## Performance and mechanical correctness

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
