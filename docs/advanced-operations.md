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
anaxigraph understand . --executor codex --model gpt-5.6-terra \
  --reasoning-effort medium --background
anaxigraph semantic-status .
```

`--executor auto` is the default and detects when Codex or Claude invoked the command. The local
executor is read-only and schema-constrained; AnaxiGraph records `provider: agent` plus the actual
executor, model, and reasoning effort as provenance. `--background` owns the complete queue outside
the invoking agent session and records its PID, log, index authority, and terminal result for
handoff through `semantic-status`. The shown model is only a per-run example. Pass `--model` and
`--reasoning-effort` to select current Codex runtime settings; executor, model, and effort are
deliberately excluded from semantic freshness. `--executor mcp`
deliberately performs planning only and returns an `agent_action_required` continuation contract
instead of claiming semantic work completed.

With no `--db`, the command first probes the configured/default loopback service and matches the
repository by canonical Git remote (or exact path for a host-local service). A match makes that
service the sole index authority: scanning/planning happen there, inference happens on the host,
and write-back goes through AnaxiMCP. If no service matches, the fallback is the stable
per-checkout database used by `anaxigraph up`, not the old shared global SQLite path. Results expose
`index.authority`, database/service location, and repository selector so another agent can resume
the exact same ledger.

## Hosted semantic worker

Agent-funded semantics is recommended because AnaxiGraph holds no model key. For unattended
scheduling, configure a hosted provider in `.anaxigraph.yml`:

```yaml
semantic:
  enabled: true
  provider: openai             # or anthropic
  model: your-model
  refresh: periodic            # manual | on_scan | watch | periodic
  reconcile_interval_minutes: 1440
  max_jobs_per_run: 100
  max_parallel_jobs: 2
  max_attempts: 3
  max_age_days: 0
  include: [src/**]
  exclude: [src/generated/**, vendor/**]
  taxonomy:
    enabled: true
    review_passes: 2
    max_areas: 6
    max_subsystems: 30
    stability_bias: 0.8
```

Taxonomy generation is on by default whenever semantic understanding is enabled. The provider
proposes a complete responsibility map, critic passes revise it, and deterministic checks repair
exact membership and bounds before finalization. Optional `map.hints` and
`map.locked_memberships` can express operator constraints, but neither is required and there is no
interactive approval gate:

```yaml
map:
  hints: [Keep persistence boundaries visible]
  locked_memberships:
    src/billing/ledger.py: billing-ledger
```

Keep credentials out of repository YAML. Export the matching key before creating the worker:

```bash
export OPENAI_API_KEY="..."       # or ANTHROPIC_API_KEY
docker compose -f compose.anaxigraph.yml --profile ai up -d
docker compose -f compose.anaxigraph.yml logs -f anaxigraph-semantic
```

The key must exist when Docker creates the container. Recreate the worker after changing its
environment.

## Local CLI or custom semantic worker

A host installation can use an already authenticated coding CLI:

```yaml
semantic:
  enabled: true
  provider: codex              # or claude
  refresh: manual
  max_jobs_per_run: 100
  max_parallel_jobs: 1
```

```bash
anaxigraph understand /path/to/repository
anaxigraph semantic-status /path/to/repository
```

The Codex adapter invokes non-interactive `codex exec` in an ephemeral read-only sandbox with a
strict output schema. The Claude adapter uses non-persistent, tool-free print mode. A `command`
provider can receive one JSON request on standard input and must return
`{"result": {...}, "usage": {...}}` on standard output. `dossier` remains accepted for existing
module-dossier integrations; taxonomy requests require the dynamic schema named by
`analysis_kind`.

The stock Docker image does not bundle Codex or Claude. Use the connected-agent workflow, a
hosted worker, or an operator-owned image rather than assuming host authentication is visible
inside the sidecar.

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

Repeated reconciliation of an unchanged repository creates no new source-reading jobs. Durable
jobs, attempts, leases, failures, token counts, and costs allow interrupted work to resume.

The semantic `include` and `exclude` patterns are source-egress controls as well as scheduling
rules. `max_jobs_per_run`, `max_parallel_jobs`, and `daily_budget_usd` bound work. Configure
`input_cost_per_million` and `output_cost_per_million` for the exact account/model if dollar
estimates matter; otherwise token usage remains recorded without inventing a price.

Source and comments are untrusted input. Model results remain versioned interpretations with
provider, model, prompt/schema, evidence, and confidence rather than replacing parser facts.

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

Generate them with the repository's normal test or CI command, then choose **Refresh scan**.

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
clients have the matching repository-scoped `ANAXIGRAPH_HISTORY_STATUS`,
`ANAXIGRAPH_HISTORY_IMPORT`, and `ANAXIGRAPH_HISTORY_CANCEL` tools.

Refresh on demand in the dashboard, or run the optional polling sidecar:

```bash
docker compose -f compose.anaxigraph.yml --profile watch up -d
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

Stop every process using the selected index before restoring, including the server, watcher, and
semantic worker. Restore validates the source before atomically replacing the index, retains the
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

The browser and MCP tools remain repository-scoped, but the service has no authentication or
per-user authorization. Keep it on loopback or behind an SSH tunnel. Anyone who can reach it can
inspect every registered repository and invoke enabled index workflows. See
[Docker operation](docker.md#experimental-multi-repository-service).

## Local CLI reference

Useful lower-level commands include:

```bash
anaxigraph scan /path/to/repository
anaxigraph update /path/to/repository
anaxigraph review /path/to/repository
anaxigraph scope /path/to/repository --goal "Add saved prompts"
anaxigraph impact /path/to/repository --target backend/app/services/chat.py
anaxigraph watch /path/to/repository
anaxigraph serve --repository /path/to/repository --scan-on-start --open
anaxigraph mcp --repository /path/to/repository --port 8765
```

The `serve` and `mcp` commands both expose the dashboard/API and Streamable HTTP MCP. Use `up` for
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
