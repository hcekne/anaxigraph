# Advanced AnaxiGraph operation

Start with the [four-step onboarding](onboarding.md). This guide covers alternatives that are
useful after the local agent-funded path works.

## Persistent host dashboard with uv

On Linux, a user service can run the dashboard and authenticated Codex/Claude executors under the
same account. This is convenient when the coding-agent logins already live on the host. Keep the
dashboard on loopback; existing authenticated CLI sessions are used for new noninteractive jobs.

The checked-in [service template](../examples/anaxigraph-dashboard.service) assumes this checkout
is at `~/repos/anaxigraph`, with `uv`, `codex` and `claude` in `~/.local/bin`. Adjust its paths if
your installation differs. Prepare the isolated environment and state directories:

```bash
UV_PROJECT_ENVIRONMENT="$HOME/.local/share/anaxigraph/dashboard-venv" uv sync --frozen --no-dev
mkdir -p ~/.config/anaxigraph ~/.config/systemd/user ~/.local/state/anaxigraph/dashboard
codex login status
claude auth status
```

Create `~/.config/anaxigraph/dashboard-repositories.yml` with absolute **host** checkout and policy
paths, following the [registry format](../repositories.example.yml). When moving an existing
service, retain its repository keys. Take a consistent SQLite backup using `Connection.backup`,
stop the Docker container, disable its restart policy, and copy that backup to
`~/.local/state/anaxigraph/dashboard/anaxi-index.db`. Update the existing `repositories.path` values
to the host checkouts in one SQLite transaction, preserving IDs and snapshots. Do this before the
host service's first start, or it can register duplicate repositories. Keep the Docker volume and
backup for rollback. Copy any existing `.workflows` settings directory beside the new database.

For a new index, the service's source watcher creates the initial structural map. To install and
start the service after the registry and index are ready:

```bash
cp examples/anaxigraph-dashboard.service ~/.config/systemd/user/
systemd-analyze --user verify ~/.config/systemd/user/anaxigraph-dashboard.service
systemctl --user daemon-reload
systemctl --user enable --now anaxigraph-dashboard
curl --fail http://127.0.0.1:8765/healthz
```

Open <http://127.0.0.1:8765/#workflows/mapping>. Check both repositories, saved coverage and the host
worker names before launching model work. Use **Configure → Try 2 jobs** for a bounded live check.
Model availability depends on the authenticated account; an installed CLI alone does not prove a
particular model call will succeed. Login or model errors appear in the selected step's saved errors.

Use `systemctl --user restart anaxigraph-dashboard` after updating Python source and
`journalctl --user -u anaxigraph-dashboard` for logs. The frozen uv environment uses this checkout;
run `uv sync --frozen --no-dev` with the same `UV_PROJECT_ENVIRONMENT` when dependencies change.
User lingering must be enabled for the service to remain up after logout; check
`loginctl show-user "$USER" -p Linger`. On this development host it is already enabled.

The 17 October 2026 migration retained repository IDs 1 and 2 and all 12,539 existing semantic
documents. The original Docker volume was kept, and its container was stopped with automatic
restart disabled. This is a development deployment of the current checkout, not a new package release.
The host-service smoke run completed two distinct AnaxiGraph intrinsic-description jobs concurrently:
job 105684 with `gpt-6-luna` and job 105654 with `claude-opus-5-5`, both on snapshot 1552, with one
attempt each. Saved worker settings were restored to the suggested four Luna workers afterward.
This verifies execution and provenance on the real service; two files are not a model-quality benchmark.

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
anaxigraph understand . --executor claude --model haiku --parallel-jobs 32 --background --json
anaxigraph semantic-status . --compact --json
```

Routine mapping writes one compact graph annotation per module: an overview sentence, a short
detail paragraph (normally 40–80 words), a behavior sentence for every supplied function, named
caller contracts, capabilities, evidence and confidence. Contracts bind obligations and invariants
to their functions once. It does not produce separate intrinsic/context essays or embedded
refactoring reports. Large source inputs can be partitioned into bounded annotation work and
reconciled before the module becomes current; successful work survives interruption.

Pattern and Fresh Eyes reviews are optional. An explicit Pattern workflow considers and rates every
loaded catalogue card (133 today), then independently reviews its assessment, including pros, cons
and plausible placements. Evidence gaps remain unresolved rather than suppressing the card.
`semantic.detailed_reviews: true` also requests Pattern work through the lower-level semantic
planner; dashboard Mapping keeps these reviews separate. This flag never restores the retired
two-description module writer. Original saved historical reviews remain readable.

Upgrading a map written by 0.5.x does not require paying to reread unchanged code.
For ordinary mapping, preparation recognizes that release's v5 evidence signatures
and re-links compatible saved understanding, taxonomy, and synthesis in place. It
also retires redundant pending jobs left by an earlier unsuccessful upgrade.
Original JSON and model provenance remain unchanged. Changed source or dependency
evidence, expired results, an explicit forced reread, or a genuinely incompatible annotation
contract can still require fresh work. Legacy prose remains an attributed archive rather than
being silently promoted to verified function contracts. Check `--plan-only --no-scan` against the saved
snapshot before launching workers when diagnosing an upgrade.

Model calls have no AnaxiGraph wall-clock cutoff by default (`semantic.timeout_seconds: null`).
The previous 300-second default could terminate a valid high-effort map review mid-response.
Set a positive number of seconds in policy, or use `--timeout-seconds` for a local executor run,
when a hard per-call deadline is wanted. Explicit deadlines remain enforced. Worker leases
continue to renew during long calls and expire after a worker crashes; a lease is not a model
deadline. This runtime setting does not invalidate saved descriptions or completed review passes.
Older repositories that explicitly set `timeout_seconds: 300` keep that limit until it is changed.

Calls use the executor's model-specific output allowance by default. AnaxiGraph does not inject
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` or put an output cap in the work packet unless
`semantic.max_output_tokens` is explicitly configured. Existing executor environment settings
are preserved. The concise writing instructions control style without cutting off complete JSON.
Source-aware mapping can use bounded evidence partitions; their sizing target is not an output
cap. Fresh Eyes is different: every functional packet stays inline. An oversized blind packet
fails its durable job with a reduce-scope/increase-input-limit remedy; it never exposes repository
files, evidence pages or tool-readable spill files to the blind worker.

Mapping step 5 saves each independent review batch as a durable job. Batches within a pass run
in parallel up to that pass's worker setting and the repository ceiling. Reconciliation combines
their findings before the next configured provider pass begins. Completed batches survive index
reopening; resuming retries failed or unfinished work. The workflow card shows saved/total batches,
active workers and elapsed seconds, and labels the last pass's global merge **Final reconciliation**.
Small maps that fit in one request keep a single whole-map review per pass.

Both `semantic.max_output_tokens` and `semantic.max_output_tokens_on_retry` default to `null`.
For an explicit per-call cap, set the first value to a token count. An optional higher retry ceiling
permits one extra call on confirmed truncation, with up to twice the initial headroom and both
calls' reported usage retained. Malformed shapes and unrelated errors do not trigger that extra
call. Native model limits still apply; aggregate usage can be higher across chunks, job attempts,
and calls inside the CLI. Incomplete results are never stored as successful descriptions.
Persistent provider or service errors remain visible and resumable.
The source-size threshold is unchanged: lowering it can create more chunk and reduction calls.

Execution continuity and remaining limits:

- `understand` with an actual executor drains the queue by default, including foreground runs.
  `--limit N` explicitly requests a sample; `--plan-only` and the manual MCP mode do not run a model.
  `max_jobs_per_run` remains a batch default for lower-level callers, not a ceiling on a full CLI
  run or the dashboard's Run Step. Healthy service preparation has no elapsed-time cutoff.
- Dashboard runs wait for live peer workers and shared slots. Remote workers refill slots after
  each saved result without waiting for their slowest peer. Concurrent workers share the
  repository's `max_parallel_jobs` ceiling; nested review calls share their worker's allocation.
- Run Step updates missing or stale prerequisites using each card's saved model settings, reuses
  current results, and stops at the selected card. Optional reviews also update their Mapping
  prerequisites. Different cards can be requested together; ready work overlaps while dependent
  work waits. Overlapping requests share one pool per card and cannot multiply its worker count.
  Progress distinguishes preparation, active model calls, shared-worker or retry waits, and final
  completion checks. A completed card stays complete during those checks.
- Remote packets advertise `ANAXIGRAPH_SEMANTIC_RENEW` and `renew_after_seconds`. Host executors
  renew while reading evidence, running a model, and submitting results. Manual executor clients
  must renew with the same job ID and lease token at that interval. Expired or replaced leases
  cannot renew, and results from a replaced owner remain rejected.
- The dedicated `/executor/mcp` route bypasses AnaxiGraph's 2 MiB control-request boundary.
  The installed MCP transport still has its own request limit (4 MiB in the locked SDK).
  Ordinary REST and normal MCP controls retain the 2 MiB boundary. JSON shape,
  source freshness, lease ownership, and evidence validation still apply to results.
- `max_attempts` bounds genuinely failed jobs. An explicit retry resets exhausted work once;
  repeated queue polls do not reset it indefinitely. Failed optional reviews are reported as
  failures even when the baseline map is ready.
- Optional per-call deadlines, output caps, and a daily spend ceiling remain opt-in. The workflow
  sidebar's **Execution limits** disclosure shows the effective values and concurrency ceiling.
  Provider account quotas, authentication, model context/output capacity, and availability still
  apply. Include/exclude rules determine which source may be sent, and pinned review stages
  require the selected executor family.

Transport and storage failures also remain bounded and reported: MCP initialization has a
20-second deadline and individual MCP operations have a 60-second deadline; these do not time
out the model call running on the host. Busy SQLite operations and failed transport waves have
finite retries. A disconnected or persistently unhealthy service can therefore end a run, with
saved results retained for resume. These conditions should appear as errors, not successful
completion or an endless preparation spinner.

`--executor auto` is the default and detects when Codex or Claude invoked the command. The local
executor is read-only and schema-constrained; AnaxiGraph records `provider: agent` plus the actual
executor, model, and reasoning effort as provenance on the run record and on every job and
document it produces. `--background` owns the complete queue outside
the invoking agent session and records its PID, log, index authority, and terminal result for
handoff through `semantic-status`. When the detached worker fails, `semantic-status` reports the
failing cause as `last_error` and the run log holds its traceback; set `ANAXIGRAPH_DEBUG=1` to
print that traceback for a foreground run. Select an authorized economical worker model explicitly
with `--model`; omitting it uses the CLI default, which may be expensive. The invoking agent's
conversation is not part of each job. Codex receives optional effort as `model_reasoning_effort`
and Claude as `--effort`, passed
through unvalidated so the executor itself rejects unknown levels. Executor, model, and effort are
deliberately excluded from semantic freshness. `--executor mcp` deliberately performs planning
only and returns an `agent_action_required` continuation contract instead of claiming semantic
work completed.

With no `--db`, the command first probes the configured/default loopback service and verifies the
exact checkout. Container aliases must match remote, branch, commit, worktree identity and working
file fingerprints; a common remote alone is insufficient. A match makes that
service the sole index authority: lightweight planning uses its current snapshot, inference happens
on the host, and write-back goes through AnaxiMCP. Structural scanning remains an explicit service
operation. If the default endpoint refuses the connection or a reachable
service has no matching repository, the fallback is the stable per-checkout database used by
`anaxigraph up`, not the old shared global SQLite path. A timeout or invalid service response fails
closed because the sidecar may merely be busy; it never silently selects a second index. Results
expose `index.authority`, database/service location, and repository selector so another agent can
resume the exact same ledger.

### One background run slot per executor

Background runs are keyed by repository and executor, so a Codex worker and a Claude worker own
separate run records, locks, and logs for the same repository and neither can corrupt the other:

```bash
anaxigraph understand . --executor codex --model '<worker-model>' --parallel-jobs 16 --background
anaxigraph understand . --executor claude --model haiku --parallel-jobs 16 --background
anaxigraph semantic-status . --compact --json
```

Replace `<worker-model>` with the Codex model selected for the run.

`semantic-status` reports every slot under `execution_runs`, running workers first, and keeps
`execution_run` as the most relevant single record for existing handoffs. A repeated launch returns
`already_running` and the existing run handle without starting another worker. Run records written
before per-executor slots existed stay readable for the
executor they name. Two workers only claim work at the same time when `semantic.max_parallel_jobs`
is 2 or more; the claim admission gate counts running leases for the whole repository, not per
executor.

Use as many concurrent jobs as the provider and repository policy support, including 32 or 48.
`--parallel-jobs` selects each executor's share of the common ceiling; for example, two executors
can each request 16 slots under `semantic.max_parallel_jobs: 32`. Existing queue work is joined
without repeating preparation. A busy preparation is waited out with backoff inside the runner;
the lock is scoped to the repository and shared by its executors. Startup preparation still busy
after ten minutes reports a service-health error instead of spawning more processes.

The calling LLM should launch once and return the run handle. Do not create supervisor scripts,
search for an `understand` process, or repeatedly restart a worker: the short-lived command hands
off to `anaxigraph.semantic_background`. Read progress on user request or after the returned
`poll_after_seconds` (normally 300). The MCP status tool defaults to compact counters, usage, and
actions; use `details=true` only for diagnostics. CLI `semantic-status --compact --json` also
includes host run records. REST offers `GET /api/semantic?compact=true`. No model is called to
schedule jobs, wait, or count progress. Avoid sending full logs or status documents back through
the expensive calling model. A started background run is not a completed semantic map.

A Fresh Eyes review can reserve its three proposal slots per functional scope
(`anaxigraph fresh-eyes . --start --proposals 3 --proposal-executors codex,claude,any`). The CLI
also accepts five alternatives. The family of
a claimant comes from its `cli:<family>:<pid>` worker identity, or from an explicit
`executor_family` argument on `ANAXIGRAPH_SEMANTIC_WORK`; a claimant with neither takes only
unpinned work. A worker offered nothing but another family's reserved slot receives the
non-terminal `waiting_for_executor` status naming that slot and the command that starts it, prints
that line once, and keeps polling, so `--until-complete` does not exit early. `--limit` still ends
the run as before. Release the reservation with `anaxigraph fresh-eyes . --unpin` when the second
executor will not be started; `--restart` remains refused while a review is unfinished.

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

The normal executor is `anaxigraph understand . --executor codex|claude`. Both native adapters use
strict structured output. For Fresh Eyes, each hierarchy, proposal, comparison and final review
receives only purpose/capability/subsystem requirements in a fresh context with repository access
and tools disabled by the requested executor settings. It never sees current source, paths,
frameworks, topology or Pattern judgments. The runtime checks supported isolation controls and
keeps execution isolation labelled **unverified** when it cannot independently establish it;
an external agent's self-report never becomes verification. Source-aware comparison and migration
belong to the separate Architecture Planning workflow, whose direction may be blank.

The functional result retains three alternatives per scope, explicit control/data/failure
boundaries, pros, cons and compatible proposed-parent identities. Comparison reports convergence
and unexplored directions honestly; repeated graph shapes alone do not establish equivalent
semantics. Read one scope with `fresh-eyes . --scope <scope-id>`, REST `scope_id`/`details=true`, or
`ANAXIGRAPH_GUIDE(intent="redesign", scope_id="<scope-id>", details=true)`. Implementation-only
changes can reuse an unchanged functional-brief revision. A changed requirement creates a new
generation; legacy source-aware Fresh Eyes results remain read-only original records.

An advanced `command` provider can receive
one JSON request on standard input and must return
`{"result": {...}, "usage": {...}}` on standard output. `dossier` remains accepted for existing
module integrations; new mapping uses the graph-annotation schema, and taxonomy requests require the schema named by
`analysis_kind`.

The stock Docker image deliberately bundles no coding CLI and accepts no hosted-model key. Run the
executor on the authenticated host or let the connected coding agent process bounded MCP work.

## Semantic cost, privacy, and refresh

Every scan first makes cheap deterministic comparisons. Semantic work is created only for missing,
failed/retried, age-expired, prompt-contract-stale, structurally changed, or context-invalidated
records:

- structural hashes decide when source needs to be read again;
- interface and relationship fingerprints refresh graph context without creating another prose copy;
- normalized intent changes invalidate affected parent synthesis;
- prompt, analyzer, enrollment policy, or an incompatible stage-contract change produces versioned
  work only at the affected stage;
- provider and model changes do not invalidate semantic work; they remain queryable provenance on
  jobs, documents, claims, usage, and cost records.

The reviewed taxonomy is not regenerated for every changed annotation. An incremental check
first requires the same included paths and map policy, then compares module-role
fingerprints with the last reviewed map. If the stable fraction meets
`semantic.taxonomy.stability_bias` (default `0.8`), AnaxiGraph carries that reviewed map forward and
refreshes only affected descendants and ancestors. A saved proposal that is still under review
can also be reused. Small additions, removals, or role changes within the stability threshold use
the latest saved candidate as the starting point for fresh reviews, without another proposal call.
Completed reviews are carried only when the proposal evidence is identical; reviews of older
evidence remain saved as history. Policy changes or responsibility drift beyond the threshold
queue a new proposal and its agent reviews.
`work_plan` reports current annotation, taxonomy, group, repository and review scopes before
model execution.

The workflow view separates current results, saved results needing refresh, and files with no
saved result. A source-update notice explains the transition; affected cards show refresh counts
and retain earlier proposal/review progress and failures. Open a card to inspect affected paths
and the earlier scan. **Update affected work** resumes the existing queue using the saved step
settings. Reading progress does not run models or mark old evidence as current.

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
rules. `max_parallel_jobs` bounds concurrent work, and `daily_budget_usd` optionally bounds spend.
Use `--limit` for a bounded sample; `max_jobs_per_run` is a lower-level batch default. Configure
`input_cost_per_million` and `output_cost_per_million` for the exact account/model if dollar
estimates matter; otherwise token usage remains recorded without inventing a price.

Source and comments are untrusted input. Model results remain versioned interpretations with
provider, model, prompt/schema, evidence, and confidence rather than replacing parser facts.

### Measured plan-transaction lock holds

Semantic planning takes one `BEGIN IMMEDIATE` write transaction over reconciliation, inventory,
graph annotation and downstream planning, and the search-projection refresh. Every plan measures
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

Detailed Git-history mapping is opt-in, not part of ordinary startup. History import is a durable
background job. The dashboard remains useful while it shows selected
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

### Repository records and scheduled runs

The tracked root `anaxigraph/` directory carries current understanding between cloud jobs and
local checkouts. Record v4 contains current compact graph annotations, reviewed architecture,
retained functional alternatives, selected Pattern reviews/plans, provenance and saved workflow
choices. It does not exchange the entire historical SQL cache, deterministic symbol/dependency
indexes, findings, Git history, metrics, active worker leases or pending queue payloads. Completed
stage manifests retain the identities needed for compatible reuse. Git is the portable history.

`record.json` marks the managed directory. `manifest.json` identifies source and analysis contracts,
readiness and checksums. Current graph annotations and modern review records remain readable JSONL;
large legacy results use bounded, checksummed compressed archive parts without changing their
original values. Small parts carry source file fingerprints and semantic results;
relative paths and logical identities survive a clone at a different absolute path. Readable
`mapping/architecture.json`, `architecture/plan.json`, `plan.md`, `current.mmd` and `target.mmd`
are bounded by the same byte/file limits. Each server owns its MCP service and local SQLite cache.

```bash
anaxigraph record save /path/to/repository --json
anaxigraph record load /path/to/repository --json
anaxigraph record status /path/to/repository --json
```

`record` and `plan` discover the service for the exact checkout when `--db` is omitted; their
responses identify the index authority. Use `--service-url` for an explicit server or `--db` to
select a local index. Headless `refresh` deliberately runs on the scheduling host, using that
checkout's local cache and authenticated worker CLIs; give it `--db` to share a custom local index.

Loading is automatic during startup scans and watcher refreshes. Each checkout gets its own local
SQLite cache. Relative source paths and logical references are translated into that cache; imports
do not replace the whole database or erase other repositories. Existing local workflow choices
take precedence over imported defaults. Supported file/analyzer/policy identities are checked before
reusing results; local edits create affected work without requiring another full model pass.

The folder is excluded from source analysis, source freshness and generated-code history evidence.
Publishing its files therefore does not invalidate its own map. Deliberate changes to planning
direction have separate fingerprints. An unrelated existing `anaxigraph/` directory is preserved
and reported rather than overwritten. Do not put unrelated source or runtime files in this reserved
directory after enabling the record.

An explicit dashboard workflow periodically checkpoints the shared record and saves again when it
finishes or stops. Headless refresh does the same and saves in its cleanup path:

```bash
anaxigraph refresh . --workflows mapping --json
anaxigraph refresh . --workflows mapping,patterns --json
anaxigraph refresh . --workflows mapping,patterns,fresh-eyes,architecture --json
```

These commands use saved or suggested per-step model pools. `--executor codex --model '<model>'`
or `--executor claude --model '<model>'` overrides them for that run. Direction may be omitted;
existing direction is retained. Use `--direction ''` to deliberately return target choice to the
agent. `--no-save` keeps the run local. Configure AI mapping and authenticate the executors under
the account running the job before scheduling it. No command here pushes Git or creates a schedule.

In Flowthink, pull a specific source revision and its prior record, run the desired refresh, then
commit/push changed architecture files through the workflow's authorized Git step. Arrange that
save/publish step to run after partial failures too. Exit code 1 means work remains or the record
could not be saved; the JSON distinguishes completed workflows from failed publication. A forced
process kill can lose work since the last shared checkpoint; keep the job's local index if you need
every completed result retained. Ignore artifact-only pushes in source-triggered automation.

Byte and file-count checks run before any output is written. Failed writes remove new partitions
and retain the last valid record. The manifest commits a checked set of content-addressed parts;
old partitions are removed after successful publication. Unchanged exports leave file bytes alone.
Current exclusions apply even when the old database still contains previously indexed runtime data.

Default storage policy in `.anaxigraph.yml`:

```yaml
storage:
  budget_bytes: 100000000
  record_bytes: 25000000
  index_bytes: 95000000
  record_files: 32
  comparison_checkpoints: 2
  detailed_history: false
```

The 100 MB total is a shared pool for steady retained state, not a reservation of each component's
maximum. The index may use up to 95 MB and a record up to 25 MB, but the retained database, SHM and
actual managed records across this index's registered checkouts must fit the same 100 MB. Each component ceiling must fit the configured
pool; their maxima need not add up to it. Explicit smaller index limits remain effective, and the
absolute physical ceiling stays 200 MB. Atomic SQLite rewrites temporarily need WAL space alongside
the database; this transient space is counted and bounded by that hard ceiling, then checkpointed.
Status reports actual physical bytes, steady bytes, transient bytes and pending WAL cleanup separately.
SQLite page limits reject index growth beyond its ceiling and roll back the write. Shared-pool
admission also checks projected database growth and actual portable
bytes. Export checks the proposed replacement before writing, preserving the last valid record if
it cannot fit; AnaxiGraph
does not silently drop a selected plan to make room. Status reports actual index/WAL/record bytes.
The active budget excludes installed tools and dependencies, Git's own history, and explicitly
retained recovery backups. Detached executors keep four recent runs per slot and trim logs to 1 MB.

Ordinary scans retain the current frame and two comparison checkpoints, materializing their state
before pruning older delta chains. Selected latest designs/reviews and reusable file descriptions
are retained as analysis-only records when their old graph is unnecessary. They do not become
empty historical maps or fabricated comparison baselines. Detailed Git mapping is opt-in: use
`--history-snapshots auto`, an explicit frame count, `anaxigraph history`, or
`storage.detailed_history: true`. The dashboard’s explicit **Import Git history** action also opts
in. A requested history import records that choice so later watcher scans do not immediately discard
its result. All retained state still fits its configured budget.

To migrate an existing index on the server that owns it, first stop ongoing scans/workers and set
its startup `--history-snapshots` or registry `history_snapshots` to `0` if it previously used the
old automatic default:

```bash
anaxigraph record compact /path/to/repository --db /path/to/anaxi-index.db --json
```

Compaction first makes one validated `*.before-current-storage.backup` recovery index, preserving
original AI documents, reviews, plans and provenance without copying historical structural graphs.
It is limited to 64 MB and its allowance is reserved against the 200 MB ceiling before writing.
The original index is left intact if saved understanding cannot fit that recovery budget.
It preserves selected original paid analyses and provenance, stores legacy results in a compressed
read-only archive, retains current annotations/reviews/plans and choices, prunes disposable history
and reclaims SQLite disk space. It exports v4 without loading a failed legacy export first.
The recovery backup is retained separately and its
path is reported; retire it after verifying migration. The existing `anaxigraph restore` command can
load it into a local index; a normal source scan rebuilds the graphs and reuses compatible file
analyses. If one index serves multiple repositories, compact each checkout against that same `--db`.
Compaction clears an implicit history opt-in; an explicit `storage.detailed_history: true` is
respected. A previously oversized index can remain
over budget when its selected analyses alone exceed the allocation; the receipt says so and new
analysis is refused until the operator reduces that state or changes budgets within the ceiling.

Start a fresh clone normally: its inexpensive source scan rebuilds deterministic indexes, validates
file and analyzer fingerprints and reuses compatible AI descriptions. Changed files are not labelled
current; older plans remain available with their original source. A record-only commit does not force
new AI calls. Compatible small v1 records remain readable; oversized legacy records must be compacted
from the server's original index before import. Local mapping, record export and Git delivery are
reported separately; `committed`/`pushed` are unknown unless the caller verifies Git publication.

Both uv and Docker services can read the folder. The default read-only Docker source mount cannot
publish changes into it: save from a writable host service, or explicitly mount only the reserved
`anaxigraph/` directory writable inside the container while retaining read-only application source.
An automatic save failure leaves local analysis intact and is reported in the workflow result.

Architecture plans retain a source snapshot and an agent-selected option. User direction and
selection are optional; preserving the current design and incremental evolution are required
alternatives. Agents can select an option through
`ANAXIGRAPH_GUIDE(intent="plan", target_option="<saved option>")`. Report a milestone with
`milestone`, `milestone_status="verified"` and `verification_evidence=[...]`, or use
`anaxigraph plan . --milestone <key> --status verified --evidence '<actual check result>'`.
Verification is attributed to its reporter and scan; AnaxiGraph does not claim it ran those tests.
The target remains available when code changes, with its older evidence labelled stale. A changed
milestone needs verification again; choosing another target does not reuse an unrelated option's
completion history.

### Full local backup and recovery

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

Impact returns short lists and compact file descriptions by default, with total and shown counts.
Use `impact --details` for full lists and descriptions, `details=true` with `ANAXIGRAPH_IMPACT`,
or `"details": true` in `/api/impact`. `ANAXIGRAPH_FILE` is compact by default; pass `details=true`
for deeper file evidence. `ANAXIGRAPH_GRAPH` pages module/function/interface/contract sentences and
typed neighborhoods; `ANAXIGRAPH_ENTITY` expands a stable entity ID into its saved paragraph,
function contracts, relevant tests and provenance without rereading source or calling a model.

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
