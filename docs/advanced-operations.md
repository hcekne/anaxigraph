# Advanced AnaxiGraph operation

Start with the [four-step onboarding](onboarding.md). This guide covers alternatives that are
useful after the local agent-funded path works.

## Manual Compose review

Generate configuration without starting containers:

```bash
uvx anaxigraph init .
```

Review `.anaxigraph.yml` and `compose.anaxigraph.yml`, then start the sidecar:

```bash
docker compose -f compose.anaxigraph.yml up -d
docker compose -f compose.anaxigraph.yml ps
docker compose -f compose.anaxigraph.yml logs -f anaxigraph
```

The initializer never replaces existing files unless `--force` is explicit. It keeps the target
mount read-only and the index in a named volume. See [Docker operation](docker.md) for the complete
hardening and lifecycle contract.

## State, ports, and endpoints

The local `up` command stores one stable index per checkout under:

- `$XDG_STATE_HOME/anaxigraph` or `~/.local/state/anaxigraph` on Linux;
- `~/Library/Application Support/AnaxiGraph` on macOS; or
- `ANAXIGRAPH_STATE_HOME` when explicitly set.

Override one index with `--db` or `ANAXIGRAPH_DB`. A generated sidecar instead uses its named
Docker volume. Host and container databases are different unless an operator deliberately mounts
the same file; a host worker cannot update an unrelated named volume.

Run multiple isolated sidecars on different loopback ports:

```bash
ANAXIGRAPH_PORT=8766 docker compose -f compose.anaxigraph.yml up -d
```

The agent endpoint depends on where the client runs:

- same host: `http://127.0.0.1:8765/mcp`;
- generated Compose network: `http://anaxigraph:8765/mcp`;
- another host: an explicitly secured reachable or forwarded URL.

Set it deliberately during client setup:

```bash
anaxigraph init . --semantic agent --connect codex \
  --mcp-url http://anaxigraph:8765/mcp
```

Credentials and URL fragments are rejected rather than written into client configuration.

## Shared module search

Use the same ranked module discovery that backs the dashboard, AnaxiMCP, and architecture guidance:

```bash
anaxigraph search "invoice reconciliation" .
anaxigraph search "BillingCalculator" . --limit 10 --json
```

The query searches the current repository snapshot only. Exact paths, filenames, and symbols are
boosted deterministically; current AI descriptions and inferred responsibilities remain tagged in
the result provenance. Search is bounded by SQLite FTS before related graph files are considered,
so a normal query does not reread source files or every saved AI description.

## Remote Linux server and local browser

When AnaxiGraph and the coding agent run on a remote Linux server, the agent reaches the loopback
MCP endpoint directly on that server. Only the browser needs SSH forwarding:

```text
Codex on server ── http://127.0.0.1:8765/mcp ──→ AnaxiMCP
Local browser   ── SSH port forward ───────────→ dashboard :8765
```

From the local computer, create a tunnel such as:

```bash
ssh -L 8765:127.0.0.1:8765 user@example-server
```

Then open <http://127.0.0.1:8765> locally. If the coding agent itself runs locally, it can use the
forwarded MCP URL only while that tunnel remains active.

## Durable coding-agent executor

When an authenticated Codex or Claude CLI is available, one command can execute the entire
`provider: agent` queue without an API key in AnaxiGraph:

```bash
anaxigraph understand . --executor codex --background
anaxigraph semantic-status .
```

`--executor auto` is the default and detects when Codex or Claude invoked the command. The local
executor is read-only and schema-constrained; AnaxiGraph records `provider: agent` plus the actual
executor, model, and reasoning effort as provenance on the run record and on every job and
document it produces. `--background` owns the complete queue outside
the invoking agent session and records its PID, log, index authority, and terminal result for
handoff through `semantic-status`. When the detached worker fails, `semantic-status` reports the
failing cause as `last_error` and the run log holds its traceback; set `ANAXIGRAPH_DEBUG=1` to
print that traceback for a foreground run. The command omits a model so the executor uses its
supported configured default. Pass `--model` and `--reasoning-effort` only for an explicit runtime
override; Codex receives the effort as `model_reasoning_effort` and Claude as `--effort`, passed
through unvalidated so the executor itself rejects unknown levels. Executor, model, and effort are
deliberately excluded from semantic freshness. `--executor mcp` deliberately performs planning
only and returns an `agent_action_required` continuation contract instead of claiming semantic
work completed.

With no `--db`, the command first probes the configured/default loopback service and matches the
repository by canonical Git remote (or exact path for a host-local service). A match makes that
service the sole index authority: lightweight planning uses its current snapshot, inference happens
on the host, and write-back goes through AnaxiMCP. Structural scanning remains an explicit service
operation. If the default endpoint refuses the connection or a reachable
service has no matching repository, the fallback is the stable per-checkout database used by
`anaxigraph up`, not the old shared global SQLite path. A timeout or invalid service response fails
closed because the sidecar may merely be busy; it never silently selects a second index. Results
expose `index.authority`, database/service location, and repository selector so another agent can
resume the exact same ledger.

The local index still scans by default before it plans. Pass `--no-scan` to plan against the saved
local map instead: a missing or stale map returns `status=scan_required` with the same guidance and
`map_status` the service path returns, and a current map plans without rereading source. Flipping
that default, so the local path scans only when asked, is a named follow-up rather than part of this
option.

## Taxonomy policy and custom executors

Taxonomy generation is on by default whenever agent-funded semantic understanding is enabled. The
coding agent proposes a complete responsibility map, critic passes revise it, and deterministic
checks repair exact membership and bounds before finalization. Optional `map.hints` and
`map.locked_memberships` express operator constraints without adding an interactive approval gate:

```yaml
map:
  hints: [Keep persistence boundaries visible]
  locked_memberships:
    src/billing/ledger.py: billing-ledger
```

The normal executor is `anaxigraph understand . --executor codex|claude`. The Codex adapter invokes
non-interactive `codex exec` in an ephemeral read-only sandbox with a strict output schema; the
Claude adapter uses non-persistent, tool-free print mode. An advanced `command` provider can receive
one JSON request on standard input and must return
`{"result": {...}, "usage": {...}}` on standard output. `dossier` remains accepted for existing
module-dossier integrations; taxonomy requests require the dynamic schema named by
`analysis_kind`.

The stock Docker image deliberately bundles no coding CLI and accepts no hosted-model key. Run the
executor on the authenticated host or let the connected coding agent process bounded MCP work.

## Semantic cost, privacy, and refresh

Every scan first makes cheap deterministic comparisons. Semantic work is created only for missing,
failed/retried, age-expired, prompt-contract-stale, structurally changed, or context-invalidated
records:

- structural hashes decide when source needs to be read again;
- interface and relationship fingerprints can refresh context without rereading unchanged source;
- normalized intent changes invalidate affected parent synthesis;
- prompt, analyzer, enrollment policy, or an incompatible stage-contract change produces versioned
  work only at the affected stage;
- provider and model changes do not invalidate semantic work; they remain queryable provenance on
  jobs, documents, claims, usage, and cost records.

The reviewed taxonomy is not regenerated for every changed context dossier. An incremental check
first requires the same included paths and map policy, then compares intrinsic module-role
fingerprints with the last reviewed map. If the stable fraction meets
`semantic.taxonomy.stability_bias` (default `0.8`), AnaxiGraph carries that reviewed map forward and
refreshes only affected descendants and ancestors. An inventory or policy change, or responsibility
drift beyond that boundary, automatically queues a new taxonomy proposal and its agent reviews.
`work_plan` reports the current file, context, taxonomy, group, repository, and pattern scope before
model execution.

`semantic.refresh: on_scan` is the default once AI mapping is enabled. It prepares the saved work;
with `provider: agent`, it does not silently run a model. A connected agent can explicitly request
the same behavior with `ANAXIGRAPH_SCAN(refresh_semantics=true)`, and the CLI equivalent is
`anaxigraph update . --prepare-semantics`. The response lists structurally changed files, text-only
changes that reused their meaning, affected neighboring files and groups, omitted counts, and the
next action. It reports `full_repository_rerun_required: false` for an ordinary partial code
change. A repository-wide edit, changed prompt/analysis contract, age policy, or explicit full
review can honestly make that field true.

Repeated reconciliation of an unchanged repository creates no new source-reading jobs. Durable
jobs, attempts, leases, failures, token counts, and costs allow interrupted work to resume.
Successful and failed model attempts contribute token totals when the executor reports usage. A
process killed before it emits usage remains explicitly unreported rather than being recorded as a
zero-token call. `semantic-status` names that state per job: `reported` usage came from the
executor, `estimated` usage is AnaxiGraph's own substitute for a configured provider that returned
none, and `unknown` usage was never reported by anyone. Cached prompt tokens are reported beside
the total they belong to, never added to it, and each action also lists the efforts that produced
it, with no entry when the executor's default was used.

The semantic `include` and `exclude` patterns are source-egress controls as well as scheduling
rules. `max_jobs_per_run`, `max_parallel_jobs`, and `daily_budget_usd` bound work. Configure
`input_cost_per_million` and `output_cost_per_million` for the exact account/model if dollar
estimates matter; otherwise token usage remains recorded without inventing a price.

Source and comments are untrusted input. Model results remain versioned interpretations with
provider, model, prompt/schema, evidence, and confidence rather than replacing parser facts.

### Measured plan-transaction lock holds

Semantic planning takes one `BEGIN IMMEDIATE` write transaction over reconciliation, inventory,
module, context, and downstream planning, and the search-projection refresh. Every plan measures
what that write lock cost and stores the running total for the current snapshot; `semantic status`
reports it under `telemetry.lock_holds` beside the action totals:

- `measured_transactions` — plan transactions measured for this snapshot;
- `total_hold_ms`, `maximum_hold_ms` — time the granted write lock was held, measured from the
  grant to the last statement before the commit, so the commit itself is not counted;
- `waiting_transactions` — plans whose `BEGIN IMMEDIATE` waited at least a millisecond for the lock;
- `total_lock_wait_ms`, `maximum_lock_wait_ms` — that measured wait;
- `locked_transactions` — plans the write lock refused after the 30-second `busy_timeout`; a refused
  plan raises and records no wait and no hold.

These are measurements of what happened, not budgets, limits, or thresholds, and nothing changes
behaviour when they grow. A plan that fails for any other reason rolls back and records nothing.
Read `maximum_hold_ms` against the 30-second busy timeout before concluding that concurrent writers
are being starved: only a hold above that timeout can make peers fail rather than wait.

## Optional test coverage

AnaxiGraph imports existing Cobertura `coverage.xml` and LCOV `lcov.info` reports. It deliberately
does not execute target tests. Missing coverage is **No report**, not measured 0%.

Add generated report paths to `.anaxigraph.yml`:

```yaml
coverage:
  files:
    - backend/coverage.xml
    - frontend/coverage/lcov.info
```

Generate them with the repository's normal test or CI command, then choose **Refresh scan**. The
dashboard starts this structural refresh asynchronously, reports its current phase and file counts,
and changes the button to **Cancel scan** while it is active. Closing the browser does not stop the
scan; cancellation is cooperative at safe per-file and persistence checkpoints, so the previous
current snapshot remains valid.

## History, refresh, and cancellation

History import is a durable background job. The dashboard remains useful while it shows selected
and completed frames, current commit, analyzed/reused work, elapsed time, and estimated remaining
time. Closing a tab does not cancel it.

```bash
anaxigraph history /path/to/repository --status
anaxigraph history /path/to/repository --cancel
anaxigraph history /path/to/repository --limit auto
```

Cancellation happens between atomic frames. Restarting resumes compatible completed work. MCP
clients can read repository-scoped progress through the History REST endpoint and dashboard; explicit import and
cancellation remain operator actions in the dashboard and CLI.

Refresh on demand in the dashboard, or let the generated polling sidecar keep the map current:

```bash
docker compose -f compose.anaxigraph.yml up -d
```

The equivalent service API is deliberately split from semantic execution:

```text
POST /api/scan          start a structural refresh and return a scan ID immediately
GET  /api/scan          read phase, completed/total files, and terminal result
POST /api/scan/cancel   request cancellation at the next safe checkpoint
POST /api/semantic/prepare  reconcile semantic work against the current snapshot without scanning
```

## Back up and restore AnaxiIndex

`backup` is safe while AnaxiGraph is running: it uses SQLite's online-backup API, includes committed
WAL state, validates integrity and schema version, and refuses to overwrite an existing file.

```bash
anaxigraph backup \
  --db ~/.local/state/anaxigraph/anaxi-index.db \
  --output ./anaxi-index-2026-08-25.backup \
  --json
```

Stop every process using the selected index before restoring, including the AnaxiGraph service and
any explicitly started compatibility CLI process. Restore validates the source before atomically replacing the index, retains the
source backup, and upgrades any supported older schema when it opens the restored database.

```bash
anaxigraph restore ./anaxi-index-2026-08-25.backup \
  --db ~/.local/state/anaxigraph/anaxi-index.db \
  --yes \
  --json
anaxigraph doctor --db ~/.local/state/anaxigraph/anaxi-index.db --json
```

For the generated Docker sidecar, first create the online backup in the named volume and copy it
to independent host storage. Use a new filename for each backup.

```bash
mkdir -p .anaxigraph-backups
docker compose -f compose.anaxigraph.yml exec anaxigraph \
  anaxigraph backup --db /state/anaxi-index.db \
  --output /state/anaxi-index-2026-08-25.backup --json
docker compose -f compose.anaxigraph.yml cp \
  anaxigraph:/state/anaxi-index-2026-08-25.backup \
  .anaxigraph-backups/anaxi-index-2026-08-25.backup
```

To restore that sidecar, stop all profiles while retaining the named volume, run a one-off local
restore with the host backup mounted read-only, then start the service again.

```bash
docker compose -f compose.anaxigraph.yml down
docker compose -f compose.anaxigraph.yml run --rm --no-deps \
  -v "$PWD/.anaxigraph-backups:/recovery:ro" \
  anaxigraph restore /recovery/anaxi-index-2026-08-25.backup \
  --db /state/anaxi-index.db --yes --json
docker compose -f compose.anaxigraph.yml up -d
```

Schema upgrades use the same validated backup primitive automatically and record the recovery
path, checksum, byte size, and version transition in the index. `doctor` verifies that migration
record and its retained recovery image. See
[AnaxiIndex schema evolution](data-model.md#schema-evolution-and-compatibility).

## Integrity and environment diagnostics

Opening an older index uses the backed-up migration contract and never edits repository source.
Inspect a generated sidecar:

```bash
docker compose -f compose.anaxigraph.yml exec anaxigraph \
  anaxigraph doctor /repo \
    --db /state/anaxi-index.db \
    --service-url http://127.0.0.1:8765 \
    --json
```

From the coding-agent host, add `--client codex` or `--client claude`, its connection scope, and
the expected MCP URL. The report covers database integrity, foreign keys, snapshot lineage,
bounded reconstruction, migration backup, semantic provenance, repository readability, index
writeability, service health, MCP initialization, and client configuration.

## Several repositories

The safest current arrangement is one loopback sidecar and isolated AnaxiIndex per developer and
repository. Different ports let several run concurrently.

An experimental operator deployment can instead clone AnaxiGraph once and allowlist multiple
read-only mounts in `repositories.yml`:

```bash
git clone https://github.com/hcekne/anaxigraph.git
cd anaxigraph
cp .env.example .env
cp repositories.example.yml repositories.yml
# Edit both files, then:
docker compose up --build -d
```

The multi-repository service is a trusted-local operator boundary. Keep it on loopback or behind an
SSH tunnel; reachability grants access to every registered repository and enabled index workflow. See
[Docker operation](docker.md#experimental-multi-repository-service).

## Local CLI reference

Useful lower-level commands include:

```bash
anaxigraph scan /path/to/repository
anaxigraph update /path/to/repository
anaxigraph review /path/to/repository
anaxigraph guide /path/to/repository --intent build --goal "Add saved prompts"
anaxigraph impact /path/to/repository --target backend/app/services/chat.py
anaxigraph serve --repository /path/to/repository --scan-on-start --open
anaxigraph serve --repository /path/to/repository --no-watch
anaxigraph mcp --repository /path/to/repository --port 8765
```

The `serve` and `mcp` commands expose the dashboard/API and Streamable HTTP MCP and supervise
repository watching by default. Use `--no-watch` only for a deliberately frozen map. Use `up` for
the assembled first-run lifecycle unless you need to operate these pieces independently.

## Upgrade, stop, or reset

```bash
docker compose -f compose.anaxigraph.yml pull
docker compose -f compose.anaxigraph.yml up -d
docker compose -f compose.anaxigraph.yml down
```

`down` retains the named index volume. `down --volumes` permanently removes that sidecar's entire
AnaxiIndex and imported history; use it only for an intentional reset after checking the target
Compose project.
