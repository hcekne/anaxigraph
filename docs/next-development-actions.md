# Next development actions: trustworthy multi-model architecture review

**Status:** proposal for the next roadmap increment (candidate Roadmap 4.3 / Phase 12). Not admitted.

**Prepared:** 3 September 2026, from the snapshot-1058 three-model fresh-eyes experiment.

**Execution rule:** unchanged from [`feature-development-plan.md`](feature-development-plan.md). Roadmap
4.2 is closed; nothing below is unfinished 4.2 work, and nothing reopens Phase 10.2. Each item names
the promise it serves, cites the current source, states the smallest coherent change, and carries a
gate that one change can fail. Every claim of "already exists" or "does not exist" below was checked
against the working tree at commit `b6f6a9a`.

## Why this increment

On 2 and 3 September 2026 the fixed fresh-eyes recipe (§10.7) ran three times on this repository
with the identical behavior-only Capability Brief (fingerprint `6d575ba2…`): twice with Codex and
once with Claude Fable 5.1. The reviews agreed on one confirmed defect, each found real issues the
other missed, and all three led with a hazard that the source shows cannot occur. The experiment
also exposed defects in how AnaxiGraph itself records, compares, and reruns such reviews.

| Generation | Executor and model | Effort | Snapshot | Review output tokens | Kept / rejected | Review confidence | Documents |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | Codex `gpt-5.6-terra` | medium | 1039 | 1,785 | 3 / 2 | 0.90 | 6657–6661 |
| 2 | Codex `gpt-5.6-sol` | not recorded | 1058 | 8,515 | 5 / 5 | 0.92 | 6897–6901 |
| 3 | Claude `claude-fable-5-1` | xhigh, via environment variable, not recorded | 1058 | 21,513 | 7 / 11 | 0.70 | 6902–6906 |

Per-stage wall time was similar (generation 2: 205, 232, 339, 431, 232 s; generation 3: 210, 212,
323, 555, 317 s), but recorded input tokens are not comparable: generation 2's comparison stage
recorded 235,690 and every generation-3 stage recorded 2, because the Claude adapter ignores cached
prompt tokens. The lesson the experiment teaches is not "ask two models." It is that the value lives
in the adjudication and verification layer: truthful provenance, enumerable generations, explicit
disagreement, and a deterministic check of whether a recommendation still matches the source.

### What the reviews got right and wrong

- **Confirmed by both providers:** the 1 MB agent submission limit counts Python characters, not
  bytes (`src/anaxigraph/semantic_agent_contracts.py:30` and `:76`).
- **Confirmed by one provider:** two AI request builders duplicate the four target-file safety checks
  (`semantic_requests.py:72-87`, `semantic_pattern_requests.py:118-127`); module identity is derived
  twice without a shared helper (`ir.py:45-94`, `ir_serialization.py:245-251`); a live working-tree
  scan has no post-read consistency check; an unknown graph snapshot id returns a plausible empty
  graph over HTTP.
- **Shared misjudgment:** every generation ranked a TEMP-table read-interference hazard first.
  `AnaxiIndex.connect()` opens a new connection per call (`storage.py:33-39`) and projections are
  connection-local TEMP tables (`persistence/snapshot_projection.py:209-231`), so the hazard cannot
  occur. The packet's own coherence note about temporary rows seeded it, and nothing lets a principal
  declare it settled.
- **Stale in part:** one recommendation asked for a prepare route that already exists
  (`api_semantic_routes.py:26` and `:43`); the local-index `understand` path, however, still scans
  unconditionally (`cli_semantic_commands.py:165-169`).

### Defects in AnaxiGraph surfaced by running the experiment

| Observation | Where |
|---|---|
| Claude effort cannot be set and is not recorded; only `--model` is forwarded | `semantic_execution.py:119-120`, `semantic.py:178-193` |
| Claude input tokens recorded as 2 per stage; cache categories and `modelUsage` ignored | `semantic.py:221-227` |
| A second host worker is told `complete` while a peer still runs fresh-eyes stages | `semantic_agent_protocol.py:184-189` |
| `cross_provider` can never be true in agent mode because provider is the constant `agent` | `semantic_fresh_eyes_review.py:405`, `semantic_runner.py:245-247` |
| `fresh-eyes --restart` timed out at a fixed 30 s during a database-lock stall and reported failure while the sidecar kept planning | `semantic_service.py:216-238`, `:429-430` |
| The Codex worker failed twice with `unhandled errors in a TaskGroup` and no traceback | `semantic_remote_worker.py:56-61`, `semantic_background.py:261-263` |
| MCP `redesign` cannot request a rerun although CLI and REST can | `mcp_core.py:192-247`, `api_models.py:18` |
| Generation 2 is reachable only by SQL; status exposes one generation and a bare `previous_review` pointer | `semantic_fresh_eyes_review.py:110-116`, `:176-197` |
| Nothing marks a review or Charter as produced from a dirty checkout | `operational_health.py:17-56`, `semantic_fresh_eyes_review.py:200-247` |

## Admission test

An item enters this increment only if it improves an **Understand**, **Guide**, or **Keep
coherent** decision, or repairs **operational trust** (provenance, reproducibility, legible failure)
in the existing bounded semantic path. Reuse the existing AnaxiIndex, job kinds, service, and
product surfaces before adding another abstraction. The nice-to-have list in the roadmap still
applies: no new provider, executor, scheduler, orchestration framework, workflow DAG, table family,
top-level journey, or MCP tool beyond the ten-tool normal profile.

Sizes: **S** is under a day in one or two modules; **M** is several days across modules, tests, and
docs; **L** is phase-sized with schema, API, dashboard, and docs. Several modules sit at or near the
500-line ceiling (`semantic_fresh_eyes_review.py` 472, `semantic_fresh_eyes_plan.py` 484,
`semantic_scope_plan.py` 489, `semantic_background.py` 499, `semantic_remote_worker.py` at the
ceiling by physical lines, `dashboard/index.html` exactly at the 500-line asset ceiling). Every item
below names where new code lives so those modules do not grow.

## Preconditions

These are not features. Nothing in the tiers below can merge until they are done.

| # | Action | Why |
|---:|---|---|
| P1 | Admit this document as a roadmap section with per-item promises and gates, and ratify a new exact `production_source_budget` baseline (currently 58,346 in `quality/maintainability-policy.json`) with acceptance evidence | The roadmap closing paragraph requires a separately admitted item, and the ratchet fails on any growth |
| P2 | Write `docs/adr/0007` covering the schema-11 usage and effort provenance columns and the widened MCP submit/fail/work contract | The cross-phase Maintainability gate requires an ADR for schema and public API decisions; drafted as [`adr/0007`](adr/0007-semantic-usage-and-executor-provenance.md) (Proposed), pending acceptance |
| P3 | Commit or drop `docs/capabilities.md`, `docs/capabilities-brief.md`, and the `examples/maxos-agent.anaxigraph.yml` semantic block | Items below cite them; the example's `max_parallel_jobs: 1` also makes a second host worker impossible wherever two executors are documented |
| P4 | Retain the snapshot-1058 experiment as an evidence record beside `docs/releases/0.4.0.md` and `docs/maxos-agent.md`: generations, executors, effort, stage durations, token caveats, defects surfaced, document ids | The roadmap admits work on retained run records; the facts currently live only in a sidecar SQLite file and a background-run JSON |

## Tier 1 — now: confirmed defects and trust gaps (all S)

Independent commits, each with its own test. Order within the tier is by user-visible harm.

### 1.1 Count the agent submission limit in encoded bytes

**Promise:** operational trust. **Evidence:** `semantic_agent_contracts.py:30` declares
`_MAX_SUBMISSION_BYTES = 1_000_000`; `:76` compares `len(json.dumps(dossier, ensure_ascii=False))`,
a character count; `:77` hand-writes "1 MB"; `api_limits.py:8` caps the wire body at 2 MiB, which is
why the gap is small in practice. **Smallest change:** encode as UTF-8 before measuring and derive
the message from the constant. **Acceptance:** a dossier under 1,000,000 characters but over
1,000,000 UTF-8 bytes is refused; 999,000 ASCII characters pass; a test pins the semantic limit at or
below the wire limit (rename the constant public or accept the private import).

### 1.2 One guard for reading a planned target file

**Promise:** keep coherent. **Evidence:** `semantic_requests.py:72-75` and `:84-87` versus
`semantic_pattern_requests.py:118-121` and `:126-127` implement resolve, `is_relative_to(root)`,
`is_file()`, `is_symlink()`, and the saved SHA-256 comparison with different messages and a
different open/hash order; `history_discovery.py:361-373` is a third, unresolved-path sibling with
its own policy. **Smallest change:** a leaf module `semantic_target_source.py` with
`read_mounted_source` and `require_unchanged_source`, called from both builders; leave discovery's
policy as is but record the difference. **Acceptance:** both job kinds refuse an outside path, a
deleted target, a symlink escaping the tree, and a changed file with the same messages; a search for
`is_relative_to` under `src/` finds only the helper.

### 1.3 One module-identity derivation, test first

**Promise:** keep coherent. **Evidence:** `ir.py:45-55` and `:75-94` (`module_identity`,
`canonical_python_module`, aliases) versus `ir_serialization.py:245-251` (`_derived_identity`, called
at `:139`, `:170`, `:171`); `ir_serialization.py` does not import `ir.py`, and `ir.py` lazily imports
`ir_serialization` at `:123` and `:133`, so a direct import would create a cycle. **Smallest
change:** commit a parametrised equality test first (`__init__.py`, nested packages, Windows
separators, TypeScript, Markdown); it passes on the current code. Then move the three functions to a
new leaf `ir_identity.py`, re-export from `ir.py`, and shrink `_derived_identity` to a call.
**Acceptance:** the equality test passes before and after; self-analysis reports no new dependency
cycle; the temporal-fact compaction and scanner tests pass unchanged.

### 1.4 Count Claude cached prompt tokens

**Promise:** operational trust. **Evidence:** `semantic.py:221-227` reads only `usage.input_tokens`
and `usage.output_tokens`; the envelope also carries `cache_creation_input_tokens`,
`cache_read_input_tokens`, thinking tokens, and a `modelUsage` map; nothing in `src/`, `tests/`, or
`docs/` mentions any of them. The Claude path also calls `validated_semantic_response` directly
instead of `_validated_with_usage` (`:285-303`), so a validation failure or non-zero exit loses the
usage it had. **Smallest change:** a `semantic_usage.py` module with a `ProviderUsage` value and
`claude_usage(envelope)` / `codex_usage(events)` parsers; both providers delegate to it; capture one
real `claude --print --output-format json` envelope and one Codex `turn.completed` event as fixtures
before asserting field names. **Acceptance:** an envelope with `input_tokens: 2`,
`cache_creation_input_tokens: 9000`, `cache_read_input_tokens: 30000` yields 39,002 prompt tokens; a
missing `usage` key falls back to `modelUsage`; a Claude validation failure carries the summed usage
into `fail_job`; the existing 70/50 test still passes.

### 1.5 Accept and forward effort for the Claude executor

**Promise:** operational trust. **Evidence:** `semantic_execution.py:119-120` rejects
`--reasoning-effort` unless the executor is Codex; `semantic.py:192-193` appends only `--model`;
Claude CLI 2.1.259 accepts `--effort low|medium|high|xhigh|max`; the run-level record already stores
`reasoning_effort` and per-job rows store executor and model (`semantic_lease_claim.py:186-201`).
**Smallest change:** drop the Codex-only guard, reword the flag help and the configured-provider
error (keep the `agent-funded` substring that `tests/test_semantic_execution.py:77` matches), and
append `("--effort", value)` in the Claude adapter, passing values through unvalidated exactly as the
Codex path does. Update README, onboarding, advanced operations, and the plugin skill. Per-job effort
columns belong to item 2.1. **Acceptance:** `understand --executor claude --reasoning-effort medium`
spawns a command containing `--effort medium`; the Codex path still emits
`model_reasoning_effort="medium"`; the background record shows the effort.

### 1.6 Report `busy`, not `complete`, while a peer worker holds a fresh-eyes job

**Promise:** operational trust. **Evidence:** `agent_no_work_status` in
`semantic_agent_protocol.py:184-189` returns `complete` whenever `semantically_ready` is true before
it checks running jobs, and `semantic_status.py:134` excludes fresh-eyes scopes from readiness. Any
second host worker that finds a peer running a review stage is told the queue is complete and exits,
so every two-executor run silently degrades to one worker. **Smallest change:** check running and
pending jobs before readiness; `busy` is already non-terminal for the remote worker. **Acceptance:**
a contract test with one running fresh-eyes job and `semantically_ready: true` returns `busy`, and
`understand --until-complete` keeps polling until it claims adjudication. The test fails on `main`.

### 1.7 Compute proposal diversity from executor family

**Promise:** operational trust. **Evidence:** `semantic_fresh_eyes_review.py:405` sets
`cross_provider` to `len(providers) > 1`, but in agent mode the recorded provider is always `agent`
(`semantic_runner.py:245-247`), so a genuine Codex-plus-Claude run is still labelled "not
cross-provider agreement" (`:447`); the adjudication packet duplicates the computation in
`semantic_fresh_eyes_requests.py:170-187`. **Smallest change:** one `proposal_diversity(documents)`
in a new `semantic_fresh_eyes_diversity.py` used by both, deriving `executor_families` from the
`cli:<family>:<pid>` prefix and reporting `unspecified` for opaque MCP agent ids; keep the
`fresh-eyes-review-v1` key names. **Acceptance:** documents with `cli:codex:11` and `cli:claude:22`
yield `cross_provider: true` and families `['claude', 'codex']` in REST, CLI, MCP, and the dashboard;
two `cli:codex:*` ids still yield false with the existing caveat; the packet block equals the status
block.

### 1.8 Guard claim, complete, and fail writes by status and worker

**Promise:** operational trust. **Evidence:** the claim `UPDATE` at `semantic_lease_claim.py:185-202`
is not conditional on the observed status; the internal runner never re-validates its lease before
`complete_job` (`semantic_runner.py:234-252`); `_finish_job` and `fail_job` write by id alone
(`semantic_results.py:196-212`, `:334-351`). The agent path is narrower than it looks: a reclaim
overwrites `lease_token_hash`, so a stale MCP submit already fails validation. **Smallest change:**
append `AND status = ?` to the claim update and return `None` when `rowcount != 1`; guard finish and
fail with `AND status = 'running' AND worker_id = ?`; raise a `SemanticLeaseLost` from
`semantic_job_state.py`; do not null `lease_token_hash` (the `already_completed` path depends on it).
**Acceptance:** a stale worker's `complete_job` after a reclaim raises, inserts no document, and
leaves the new claimant's executor id; a barrier-synchronised two-connection claim test never
returns the same job id across 20 rounds.

### 1.9 Legible operational failures

**Promise:** operational trust. Two paired edits to error-path text.

- **Surface TaskGroup leaf errors.** `semantic_remote_worker.py:56-61` prints the group header;
  `anyio` 4.14.2 wraps a single body exception as `ExceptionGroup('unhandled errors in a TaskGroup
  (1 sub-exception)')`, and the MCP client wraps it again, so flattening must be recursive. The
  detached wrapper then overwrites the progress-supplied `last_error` with `Semantic command exited
  with status N` (`semantic_background.py:261-263`). New `semantic_remote_errors.py` with
  `leaf_exceptions`, `failure_summary`, and a traceback writer for detached runs; keep a non-empty
  progress `last_error`. **Acceptance:** a body that raises `database is locked` produces that text
  in `semantic-status.execution_run.last_error` and a traceback in the run log; the header text
  appears nowhere.
- **A start timeout that is neither misleading nor tied to the busy window.**
  `semantic_service.py:216-238` uses a fixed `timeout=30` for both the start POST and the status
  GET, equal to `storage.py:38`'s `busy_timeout`; a response-wait timeout surfaces as
  `OSError('timed out')` (`:429-430`) and the CLI reports failure while the sidecar keeps planning.
  Add `--timeout-seconds` to `fresh-eyes` (default above the busy window), keep a shorter GET
  timeout, and print "may still be planning" with no automatic second POST. **Acceptance:** a
  timed-out start issues exactly one POST, exits 2, and names the status command; the default is
  strictly greater than `busy_timeout`.

### 1.10 Retry every sidecar write-back on `database is locked`

**Promise:** operational trust. **Evidence:** only `_submit` retries locks
(`semantic_remote_worker.py:387-406`); `_claim_wave` (`:326-351`) runs outside the wave `try` and is
immediately fatal; fail and release (`:421-457`) are absorbed only because releases are gathered with
`return_exceptions=True`. **Smallest change:** move the existing retry loop into a new
`semantic_remote_calls.py` helper and use it for claim, submit, fail, and release; this shrinks the
worker module. Server-side retry is deferred until item 2.6 measures lock holds. **Acceptance:** a
fake session returning one locked error then success completes for all four tools; a non-lock error
raises immediately with no sleep.

### 1.11 Rerun parity for the MCP redesign journey

**Promise:** guide. **Evidence:** `api_models.py:18` accepts `restart`; `cli_agent_commands.py`
exposes `--restart`; `mcp_core.py:192-204` and `:226-247` accept only `proposal_count` and
`retry_failed`, breaking the §10.7 acceptance that MCP and CLI expose the same review operation.
**Smallest change:** add `restart` to `ANAXIGRAPH_GUIDE(intent="redesign")` and handle non-current
plan states in the journey result; update the plugin skill. **Acceptance:** MCP restart and CLI
restart produce identical generation numbers, document ids, and states in
`tests/test_fresh_eyes_transports.py`.

### 1.12 Make column additions reach a live same-version index

**Promise:** operational trust. **Evidence:** `persistence/index_initialization.py:36-45` returns
early when the stored version equals `SCHEMA_VERSION` without running `migrate_schema`, so
`_ensure_legacy_columns` (`migrations.py:76-106`, `:182-190`) never executes on a live version-10
index; tests on fresh or version-2 fixtures pass while production fails with `no such column`.
**Smallest change:** either run the column reconciliation on the same-version path or codify the
"every column addition bumps the version" rule with a live-version-10 fixture test. Decide before
item 2.1. **Acceptance:** opening a copy of a version-10 index after a column addition yields every
column named in `_ensure_legacy_columns`, and `complete_job` succeeds on it.

### 1.13 A two-executor fresh-eyes test fixture

**Promise:** enabling test infrastructure. **Evidence:** `tests/test_semantic_fresh_eyes.py:14-48`
and `tests/test_fresh_eyes_transports.py:16-36` claim with `f"{prefix}-{index}"` agent ids and stop
on `complete`; no test uses two executor families. Items 1.6, 1.7, 2.2, 3.4, and 2.1 all need one
harness that drives a review with `cli:codex:1` and `cli:claude:2` identities and independent claim
loops. **Acceptance:** the shared helper exists in `tests/fresh_eyes_support.py`, and 1.6 and 1.7
use it.

## Tier 2 — next: make reviews reproducible and comparable

### 2.1 Schema 11: semantic usage and executor provenance (M)

**Promise:** operational trust. Bundle three column additions under one version bump, one backup,
one ADR (P2), and one migration test, after item 1.12 settles the mechanics. **Evidence:** token
columns are `INTEGER NOT NULL DEFAULT 0` (`persistence/schema.py:180-181`, `:207-209`);
`usage_reported` is inferred from `tokens > 0` (`semantic_results.py:290-296`) and `actual_cost`
from that (`:307`); `_action_totals` hardcodes the summed keys (`semantic_status.py:326-343`);
`docs/data-model.md:108` says unreported use stays zero while `docs/advanced-operations.md:183` and
the plugin skill say it is unknown. **Change:** add `cache_read_input_tokens`,
`cache_creation_input_tokens`, `usage_source TEXT NOT NULL DEFAULT 'unknown'` (values `reported`,
`estimated`, `unknown`, with a clearly labelled heuristic backfill), and `executor_effort` to
`semantic_jobs` and `semantic_documents`; extend `SemanticResult`, `SemanticAnalysisError`, the
remote worker payload, the MCP submit/fail/work arguments (optional, backward compatible), status
sums and action totals, and the three documents. Cache-aware pricing is a named follow-up.
**Acceptance:** a Claude fresh-eyes stage persists summed prompt tokens with a non-zero cache split
and `usage_source = 'reported'`; an agent submit without usage stores `unknown` and a `NULL` cost;
the exact `SUPPORTED_SCHEMA_VERSIONS` test and the future-version test are updated in the same
commit; a backup of the live index precedes the upgrade.

### 2.2 Enumerate generations and their stage telemetry (M)

**Promise:** understand. **Evidence:** the write side preserves the generation in the plan token
(`proposals:generation`), in every stage manifest, and in the document predecessor column, but
`status()` reads only the latest snapshot's plan row (`semantic_fresh_eyes_review.py:110-116`) and
hard-codes `previous_review` (`:176-197`); completed job metadata is compacted to `{retention, stage,
slot, input_manifest, information_boundary}` (`semantic_results.py:320-334`), and generation-1 jobs
carry empty metadata, so a legacy fallback to the plan token is required; an implementation-only
rescan reuses proposal and adjudication documents without new jobs (`semantic_fresh_eyes_plan.py:322-333`),
so bundles must be derived from surviving scope states or manifest chaining, not from jobs alone.
**Change:** a new `semantic_fresh_eyes_generations.py` that lists bundles per repository with state
(`current`, `superseded`, `failed`), snapshot, executor models, and a per-stage telemetry block from
a new `semantic_fresh_eyes_telemetry.py`: duration from `started_at` to `completed_at`, output bytes
as `length(value_json)`, tokens with a plausibility caveat against `estimated_input_tokens`, and
`attempts_observed` (attempts are decremented on release and reset on explicit retry, so the metric is
a floor, not a retry count). Render the current generation's telemetry on the existing stage cards
(`dashboard/fresh-eyes-view.js:140-149`). **Acceptance:** after two restarts the payload lists
generations 1, 2, 3 with disjoint stage document ids, executor models matching each run, exactly one
bundle `current`, and per-stage `duration_ms >= 0`, `output_bytes == len(value_json)`,
`attempts_observed >= 1`.

### 2.3 Select a generation in REST, CLI, MCP, and the dashboard (M)

**Promise:** understand. **Evidence:** `GET /api/fresh-eyes` takes only `repository_id`
(`api_agent_routes.py:125-130`) and lacks the `ValueError` to 400 wrapper its siblings have
(`:143-144`, `:161-162`); the CLI has no `--generation`; the dashboard fetches without parameters,
although `dashboard-core.js:132-140` already serialises extra query parameters. **Change:** a
`generation` argument on `FreshEyesReviewService.status` that builds a `superseded` payload from the
bundle's documents (the current `_stage_payloads` and `_input_manifests` key off scope-state rows and
cannot be reused unchanged), a query parameter, a CLI flag, an `ANAXIGRAPH_GUIDE` argument, and one
selector in the existing Fresh eyes sub-view. Depends on 2.2. **Acceptance:** `?generation=2`
returns generation 2's recommendations, rejected ideas, and manifests with state `superseded`;
`?generation=99` returns 400 naming the available generations; REST, CLI, and MCP agree.

### 2.4 Snapshot provenance and a dirty-checkout caveat (M)

**Promise:** operational trust. **Evidence:** `working_tree_fingerprint` and `dirty` are read from
`metadata_json` only in `operational_health.py:17-56`; the scan writes them at
`scan_persistence.py:44-51`; fresh-eyes and Charter payloads carry neither. **Change:** a new
`snapshot_provenance.py` with `snapshot_provenance(row)` and `dirty_snapshot_caveat(provenance)`,
attached to the fresh-eyes payload, the Charter, and the dashboard header. **Acceptance:** every
fresh-eyes and Charter payload carries `snapshot.commit_sha`, `snapshot.dirty`, and
`snapshot.working_tree_fingerprint`; a review from the dirty fixture checkout prepends a dirty
caveat that disappears after commit and rescan; REST and MCP blocks are equal
(`tests/test_fresh_eyes_transports.py:80-81`).

### 2.5 Gate and offload the fresh-eyes start route (M)

**Promise:** operational trust. **Evidence:** `AgentRoutes.start_fresh_eyes` is a synchronous
handler with no operation gate (`api_agent_routes.py:132-144`), unlike `prepare`
(`api_semantic_routes.py:57-68`); planning can wait a full busy window behind a writer; the MCP start
path (`mcp_core.py:236-247`) is a second, already-offloaded caller; `admit_operation` applies a 5 s
cooldown (`api_context.py:67`, `:77-82`), so a quick `--start` then `--restart` would receive 429.
**Change:** admit under `fresh_eyes_start`, run in a thread, and accept `wait: false` to return after
the `requested` transaction; the next claim plans only when the queue is otherwise empty
(`semantic_agent.py:58`, `:265-267`), which the acceptance must state. **Acceptance:** an in-flight
start appears in `/api/operations`; a sleeping planner does not block a concurrent status GET;
`wait: false` returns `plan_stage: deferred` within one short transaction.

### 2.6 Measure lock holds before splitting any transaction (S)

**Promise:** operational trust. **Evidence:** `SemanticPlanningService.plan` holds one
`BEGIN IMMEDIATE` across reconcile, inventory, module and context planning, downstream planning, and
the search projection refresh (`semantic_scope_plan.py:109-154`); `busy_timeout` is 30 s. The
roadmap lists lock-wait time as a runtime metric but nothing measures it. **Change:** record
plan-transaction duration and locked-retry counts in semantic-status telemetry and add a 30-job
parallel write-back fixture. **Acceptance:** the fixture shows non-zero retries and a measured
maximum hold; no phased-transaction item is admitted without this evidence.

### 2.7 Declared context reaches the as-built comparison and mission filter (M)

**Promise:** keep coherent. **Evidence:** corrections saved through `charter --correct-section` are
overlaid only on the human and agent Charter read model (`architecture_charter.py:212-241`); the
comparison packet uses the raw Charter document (`semantic_fresh_eyes_evidence.py:34`, `:43-59`), no
manifest mentions declared facts, and `read_charter_corrections` keeps one document per key
(`architecture_charter_corrections.py:127-131`). **Change:** add bounded `declared_context` to the
comparison and review packets and a fingerprinted manifest entry, so adding or withdrawing a
correction re-queues only comparison and review; echo the included keys in the review payload.
Refutation dispositions (3.5) and Charter-synthesis feedback (not now) are separate. **Acceptance:**
a saved correction appears in the comparison request and not in proposal or adjudication packets;
withdrawing it changes the comparison fingerprint; with no corrections every existing fingerprint is
byte-identical.

### 2.8 Fail loud on unknown graph snapshot ids over HTTP (M)

**Promise:** keep coherent. **Evidence:** `persistence/graph_index.py:23-25` and `:43-45` return an
empty payload when an explicit snapshot id does not resolve, while `:59-64` raises for a missing
delta baseline but not a missing target; the dashboard already shows "No saved scan"
(`history-controller.js:106`), and the CLI export cannot reach an unscanned repository because
`ensure_current` scans first (`cli_common.py:39-48`), so the gap is REST and export only.
**Change:** raise for an explicit unknown or foreign id (mapped to 400) and add an additive
`availability: unscanned` key for the implicit empty case; leave MCP untouched. **Acceptance:**
`?snapshot_id=999999` and a foreign repository's id return 400 on graph, neighbors, and delta
target; an unscanned registered repository returns 200 with `snapshot: null` and
`availability: unscanned`; the contract version stays `graph-query-v2`.

### 2.9 Bound working-tree drift during a live scan (M)

**Promise:** operational trust. **Evidence:** `scanner.py:98` computes repository metadata once
before discovery (`:108-127`); working-tree discovery cannot carry unchanged files
(`history_discovery.py:61-72`), so every file is read after the fingerprint was taken;
`insert_snapshot` builds its metadata inline (`scan_persistence.py:45-54`) and `GitMetadata`
(`models.py:100-108`) has no consistency field. **Change:** a new `scan_consistency.py` with
`working_tree_drift(before, after)` and a bounded rediscovery (two attempts); on persistent drift
store `scan_consistency: changed_during_scan` and report `uncertain` in `served_map_status`. Revision
and non-git scans call the fingerprint zero extra times. This is the cheap form of the Codex lead;
copying the tree is not proposed. **Acceptance:** a progress hook that edits a tracked file during
the first discovery yields one rediscovery and a verified fingerprint; persistent drift is recorded
and surfaced; the unchanged-scan short-circuit (`scanner.py:126-141`) still fires.

### 2.10 An explicit no-scan option for the local-index `understand` path (S)

**Promise:** guide. **Evidence:** `_understand_local` scans unconditionally with
`run_type='semantic_bootstrap'` (`cli_semantic_commands.py:165-169`), even for `--plan-only`, while
the service path returns `scan_required` (`:212-213`, `:264-284`); the handoff design envisioned an
explicit `--scan` with a no-scan default (`docs/semantic-bootstrap-p0-handoff.md:321-322`).
**Change:** add `--no-scan` with service-path parity now, and name the default flip as a follow-up.
**Acceptance:** `--no-scan` on a fresh or stale local index returns `scan_required`; on a current map
it proceeds and reads no files.

### 2.11 Exposure notice for non-loopback binds (S)

**Promise:** operational trust. **Evidence:** `--host` defaults to `127.0.0.1`
(`cli_server_commands.py:49`), MCP constrains Host headers (`mcp_runtime.py:48-52`), the dashboard
and README warn statically (`index.html:457-459`, `README.md:248-249`), but a hand-run
`serve --host 0.0.0.0` prints nothing, `--host ::` prints `http://:::8765` (`:95-97`), and `--host`
has no help text. **Change:** a pure `bind_exposure_notice(host, port, allowed_hosts, allow_scan)`
printed once to stderr, plus the URL and help fixes. **Acceptance:** non-loopback hosts print a
notice mentioning reachability, no login, and agent-triggered scans when enabled; loopback hosts print
nothing; `anaxigraph up` output is unchanged.

### 2.12 A second host executor beside the background worker (S)

**Promise:** operational trust. **Evidence:** the per-repository lock refuses a second background
run (`semantic_background.py:101-118`); the record already names its executor (`:160-174`,
`:388-390`); the foreground `--until-complete` path is the same command undetached (`:44-56`).
**Change:** make the refusal name the foreground alternative when a different executor is active,
and state in the docs that two host processes need `semantic.max_parallel_jobs >= 2`. Per-executor
run slots are item 3.4. **Acceptance:** the different-executor refusal message names
`--until-complete`; two concurrent host workers both claim work when the limit allows.

## Tier 3 — later: features that need Tier 2 data

### 3.1 Deterministic cross-generation alignment (M)

**Promise:** keep coherent. Classify recommendations of two generations as aligned, conflicting, or
unmatched using lexical signals only: normalised-token Jaccard over title, affected contracts, and
mission capability, shared file tokens, and action agreement, reusing the existing `_tokens` and
`_jaccard` helpers (`semantic_taxonomy_identity.py:175-181`) and the stopword handling in
`agent_decomposition_mapping.py:12-22`. A rejected idea on one side that matches a recommendation on
the other is `conflicting`. The result names its method as `lexical` and carries a fingerprint.
Depends on 2.2 and 2.3. **Acceptance:** pure and stable; a shared target with actions `split`
versus `refactor` is never `aligned`; swapping sides swaps the unmatched lists.

### 3.2 Side-by-side generation view (M)

**Promise:** understand. A compare mode inside the existing Fresh eyes sub-view: a second selector
and a new `fresh-eyes-compare.js` asset rendering two columns of recommendations, rejected ideas,
disagreements, diversity, and stage telemetry. `index.html` is exactly at the 500-line asset ceiling
and the production budget includes assets, so the asset needs a ratified baseline. Telemetry is a soft
dependency. **Acceptance:** two mocked payloads render two columns in rank order; the same generation
on both sides shows a notice; the asset stays under the ceiling; the 390-pixel viewport contract
holds.

### 3.3 Deterministic grounding report per recommendation (M)

**Promise:** operational trust. Extract checkable identifiers from `current_evidence`,
`affected_contracts`, `expected_deletions`, and `smallest_change` (paths, symbols, findings, commits,
routes, declared keys), resolve them against the reviewed snapshot, and label each recommendation
`confirmed`, `needs_test`, `already_satisfied`, or `stale`, writing exactly one `fresh_grounding`
document per review. Grounding is heuristic and must prove itself first on the stored generation-3
"prepare AI work without a new scan" recommendation, which the existing route makes
`already_satisfied`. `_finish_plan` runs on every planning pass (`semantic_fresh_eyes_plan.py:160-171`),
so the writer must be idempotent, and `status()` must perform zero writes. **Acceptance:** the stored
generation-3 recommendation is labelled `already_satisfied`; a recommendation with no checkable
identifier is `needs_test`; repeated `status()` calls write nothing.

### 3.4 Cross-provider proposals inside one run (M each, in order)

**Promise:** operational trust. Achievable today through per-executor generations (2.2 to 2.3), so
this is later work. In order: (a) record a per-slot executor assignment in the plan token
(`count:generation:codex,claude`) and derive `required_executor` per slot from the token, because
completed job metadata is compacted and `_reuse_job` never rewrites metadata
(`semantic_records.py:192-211`); (b) filter claims by executor family in Python over a small candidate
page (no `json_extract` dependency exists in `src/`), with an optional `executor_family` argument on
`ANAXIGRAPH_SEMANTIC_WORK`; (c) a non-terminal `waiting_for_executor` status naming the exact command
to start, plus a mandatory abandon-or-unpin path because `--restart` refuses while a plan is not
current; (d) per-executor background run slots in a new `semantic_background_slots.py`. Note that
executor identity already enters the reference fingerprint through `document_identity`
(`semantic_fresh_eyes_evidence.py:116-126`). **Acceptance:** with slot a pinned to Codex and slot b
to Claude, a Codex claimant receives only slot a, a Claude claimant only slot b, and the review
reports `cross_provider: true`; a worker with the other slot pending is told to wait, not that the
queue is complete.

### 3.5 A `refute` disposition for inferred Charter claims (M)

**Promise:** understand. Add an optional `disposition` (`correct` default, `refute`) to the
correction value (`architecture_charter_corrections.py:49-57`) and overlay it in
`architecture_charter.py:231`, surfacing it in the dashboard (`overview-view.js:106`, `:119`) and,
through 2.7, in fresh-eyes packets. Architecture guidance never reads `coherence_concerns`, so no
guidance change is proposed. **Acceptance:** a refuted concern stays visible with its rationale and
never reappears as a fresh-eyes hazard without new evidence; existing corrections load unchanged.

### 3.6 Server-side busy retry and phased planning transactions

Admit only when 2.6 shows holds longer than `busy_timeout`. Server-side retry around `work` can
re-run a full plan, so it is not a free change.

## Not now

- **An AI consensus-adjudication job kind across generations.** A fifth job kind plus route, CLI,
  and MCP surface for the fixed recipe collides with the roadmap's complexity exclusions, and a third
  model's agreement is still not correctness. Re-admit only after 3.1 has run on two real generation
  pairs and its unmatched output shows where lexical matching fails.
- **Stable evidence ids and citation validation.** Every fresh-eyes schema is
  `additionalProperties: false` (`semantic_fresh_eyes_contract.py:39-45`), and the stage contracts
  are two hash-bearing string tables (`semantic_fresh_eyes_plan.py:35-40`,
  `semantic_fresh_eyes_requests.py:44-49`), so a v2 contract supersedes every stored comparison and
  review. Unjustified until 3.3 measures a false-confirmation rate that ids would remove.
- **Feeding corrections into Charter synthesis.** As designed it changes the synthesis input hash,
  demotes the Charter to stale, and flips `semantically_ready` to false on every correction
  (`semantic_status.py:157-167`). Ship 2.7 alone and measure whether corrections change review output.
- **Splitting branch-heavy functions because a count exceeds a threshold**, storing all source in
  the index, one reader object for every path, per-scan deletion, a rebuild-findings command, or
  moving every cap into settings. The mission filter rejected these with repository-specific reasons
  and this document agrees.

## Exit gate for the increment

- A second host executor started with a different `--executor` while a peer holds a running
  fresh-eyes job receives `busy`, not `complete`, and keeps polling; the contract test fails on
  `main` today.
- A fresh-eyes stage executed through `--executor claude` persists summed prompt tokens from a
  captured real envelope fixture, and a Claude validation failure persists the same summed usage on
  the failed attempt.
- Two proposal documents from `cli:codex:*` and `cli:claude:*` yield `cross_provider: true` on every
  surface; two `cli:codex:*` documents still yield false with the caveat.
- `understand --executor claude --reasoning-effort medium` spawns `--effort medium`; the Codex path
  is unchanged.
- Opening a version-10 index copy after any column addition yields every reconciled column, and the
  exact supported-version test is updated in the same commit as any bump, with ADR 0007 merged first.
- MCP and CLI reruns produce identical generation numbers, document ids, and states.
- After two restarts, status lists generations 1, 2, and 3 with disjoint document ids, one `current`
  bundle, and per-stage duration, output volume, and attempts; `?generation=2` returns generation 2.
- A stale worker's completion after a reclaim raises, writes no document, and never claims a job
  another connection holds across 20 barrier-synchronised rounds.
- A remote-worker failure shows its leaf message in `execution_run.last_error` and a traceback in
  the run log; the TaskGroup header appears nowhere.
- A timed-out fresh-eyes start issues exactly one POST and says the sidecar may still be planning;
  the default timeout exceeds `busy_timeout`.
- Every fresh-eyes and Charter payload carries commit, dirty flag, and working-tree fingerprint, and
  a dirty checkout produces a visible caveat that a commit and rescan remove.
- The grounding report labels the stored generation-3 prepare recommendation `already_satisfied`
  and performs no writes on read.
- `scripts/check_module_size.py` passes with no implementation module above 500 lines and the
  remote-worker and background modules no larger than today; `scripts/check_code_quality.py` passes
  against a ratified new exact production baseline recorded with acceptance evidence.
- The immediate implementation queue in `feature-development-plan.md` gains one row per admitted
  item, each naming its promise and its section here, and no row without one.
