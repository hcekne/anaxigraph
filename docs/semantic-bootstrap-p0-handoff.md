# P0 handoff: make semantic bootstrap finish reliably on a real repository

**Status:** source repair implemented and deterministically verified; paid MaxOS acceptance paused

**Recorded:** 25 August 2026 UTC

**Source repair landed:** 25 August 2026 UTC, through `2f05574`

**Primary reproduction:** MaxOS Agent Harness, 1,881 indexed modules

**Required outcome:** A coding agent of ordinary capability must be able to start or resume a
complete semantic baseline with one durable command, observe truthful progress, survive interruption,
and eventually reach `semantically_ready: true` without manually shepherding thousands of MCP calls.

This document is an implementation handoff, not a speculative roadmap. It records a reproduced
failure in the current service, the underlying causes, the smallest coherent repair sequence, and
the tests that must pass before the workflow can be called working.

## Resolution update

The source repair described below is complete. Queue planning is linear and stage-driven;
structural scans, semantic preparation, and model execution are separate; semantic runtime settings
do not change structural snapshot identity; service-backed runs report one configuration authority;
expired leases recover at claim time; and the detached executor records durable progress and stalled
state. A 2,000-module planning fixture and a restartable 200-module full lifecycle verify the repair
without model spending. The complete 532-test suite and all 16 browser contracts pass.

The one remaining acceptance item is the paid live MaxOS run in Slice 6. It is intentionally paused
at the operator's direction while unrelated defects are addressed. No semantic run should be
started merely to close this document. [Phase 6.9](feature-development-plan.md#69-make-repository-sized-semantic-bootstrap-operational)
records the current evidence and the exact live gate still outstanding. The incident analysis and
implementation checklist below are retained as the historical reproduction and acceptance record.

## Executive verdict

The current semantic subsystem has many individually tested components, but the repository-sized
execution path is not operationally usable. The MaxOS failure is not principally caused by a weak
coding model. The normal `anaxigraph understand` path performs expensive synchronous preparation
before opening the semantic work loop, exceeds its own timeout, leaves server work running, and can
then report a misleading conflict. Once work is available, MCP claim and submission calls repeatedly
re-plan the entire repository and perform quadratic snapshot reconstruction.

For a 1,881-module repository, those behaviors make an ordinary Codex MCP client likely to time out
before receiving work. Increasing model parallelism does not repair them. It can increase load while
the queue-control path remains the bottleneck.

The P0 repair is:

1. make semantic queue planning linear and run it only at stage boundaries;
2. separate structural scanning from semantic queue preparation;
3. remove semantic runtime settings from structural snapshot identity;
4. make the selected service configuration the unambiguous authority;
5. reclaim expired leases at the claim boundary;
6. make the detached host executor the default repository-sized workflow;
7. prove the whole path on a 2,000-module fixture and then on MaxOS.

Do not call this fixed merely because unit tests for leases, providers, or MCP serialization pass.
The exit condition is a completed end-to-end baseline.

## User-level contract

The supported primary workflow should be:

```bash
# Run in the repository that is being analyzed. Do not pin a model by default.
anaxigraph understand . --executor codex --background --json

# This must identify the same sidecar/index and report continuing or terminal progress.
anaxigraph semantic-status . --json
```

Expected behavior:

- the first command returns a durable run ID and log/status location within five seconds;
- an already-indexed repository does not undergo an implicit full structural rescan;
- the worker uses the authenticated local Codex CLI and its account allowance;
- the worker can be stopped, restarted, or disconnected without losing completed dossiers;
- expired work becomes reclaimable automatically;
- progress advances monotonically through intrinsic, context, taxonomy, synthesis, pattern
  assessment, and independent review stages;
- completion is reported only when all of the following are true:

```json
{
  "coverage": 1.0,
  "baseline_complete": true,
  "semantically_ready": true,
  "taxonomy": { "ready": true }
}
```

The direct MCP `WORK -> EVIDENCE -> SUBMIT` loop remains a bounded fallback. It must not be the
default instruction for a repository-sized baseline.

## Reproduced incident

### Starting state

The live loopback service was healthy at `http://127.0.0.1:8765` and indexed two repositories.
MaxOS was repository ID 2 and initially reported:

- snapshot 216;
- 1,881 modules;
- 9 intrinsic dossiers;
- 1,872 intrinsic dossiers pending;
- one job still marked `running` after its lease had expired the previous day;
- no repository dossier;
- no ready taxonomy;
- `baseline_complete: false`;
- `semantically_ready: false`.

The expired job was:

- job ID 13875;
- scope `scripts/repository_coverage.py`;
- lease expiry `2026-08-24T23:21:00Z`;
- still reported as `running` during the 25 August audit.

### Exact reproduction command

To isolate preparation from model behavior, the following existing command was run without invoking
a model:

```bash
uv run anaxigraph understand /home/hcekne/repos/maxos_agent \
  --config /home/hcekne/repos/maxos_agent/.anaxigraph.yml \
  --service-url http://127.0.0.1:8765 \
  --plan-only \
  --json
```

The command was silent for five minutes and then failed:

```text
anaxigraph: AnaxiGraph service returned HTTP 409:
{"detail":"semantic_refresh is already running"}
elapsed=5:01.13
```

The MCP executor had not begun. The failure happened during server-side semantic preparation.

### What the server actually did

The server admitted `semantic_refresh` at `07:39:16Z`. Its structural scan finished at
`07:43:49Z`:

| Measurement | Observed value |
|---|---:|
| Structural scan duration | 272.649 seconds |
| Discovered modules | 1,881 |
| Modules analyzed | 1,881 |
| Modules reused | 0 |
| Invalidation reason | `policy_changed` for all 1,881 |
| Relationships rebuilt | 15,404 |
| Findings produced | 1,307 |
| New snapshot | 220 |

Semantic planning then continued until approximately `07:45:51Z`, about another 122 seconds. The
complete server operation therefore took roughly 6 minutes 34 seconds.

The client has a 300-second preparation timeout. It timed out while the server continued working.
The retry reached the still-active operation and surfaced HTTP 409. This is why the command looked
like a transport hang and why server shutdown or later work could encounter a busy database.

After the abandoned client had exited, the server eventually completed preparation and reported:

- snapshot 220;
- 1,881 modules;
- 9 reusable intrinsic dossiers;
- 1,872 pending intrinsic jobs;
- no remaining stale `running` job for the old snapshot.

This proves the client result was false from the operator's perspective: it reported failure while
the server continued and eventually committed a new queue.

## Root causes

### P0.1: semantic settings invalidate the structural snapshot

`scan_preparation._config_json()` serializes the complete `AnaxiGraphConfig` and removes only
`config_path`. The resulting value participates in `analysis_signature()` and
`content_fingerprint()`.

Consequently, changing any of the following changes the structural scan identity:

- `semantic.enabled`;
- `semantic.max_parallel_jobs`;
- model timeout;
- lease duration;
- taxonomy review settings;
- model/provider execution details.

This was verified directly: changing only `semantic.enabled` changed the analysis signature, and
changing only `semantic.max_parallel_jobs` also changed it.

Those fields do not change parsed source, symbols, dependency facts, or architecture placement.
Treating them as structural policy forced all 1,881 MaxOS modules through `policy_changed` and
destroyed the fast unchanged-snapshot path.

This also violates the product's facts-versus-interpretations boundary. Semantic execution policy
must have its own fingerprints and invalidation rules; it must not masquerade as structural source
change.

#### Required correction

Introduce an explicit structural-analysis configuration projection. It should include only values
that can change discovery, parser output, deterministic relationships, or deterministic placement.
At minimum, review these domains separately:

| Configuration domain | Structural snapshot identity? | Handling |
|---|---|---|
| include/ignore/max file size | Yes | Changes discovered facts |
| language aliases/resolution aliases | Yes | Can change deterministic relationships |
| configured groups used for placement | Yes | Can change structural placement |
| semantic provider/model/limits/leases | No | Semantic planning/execution fingerprints only |
| semantic taxonomy settings | No | Taxonomy input/contract fingerprint only |
| agent payload limits | No | Query/runtime concern |
| attention-page and diagnostic display settings | No | Read-model concern |
| coverage report locations | No structural reparse | Refresh measurements on the current snapshot |
| finding thresholds/rules | No structural reparse | Re-evaluate findings on the current facts |

Add distinct names such as `structural_analysis_signature` and
`semantic_policy_signature`; avoid another generic “config hash.”

### P0.2: semantic planning is quadratic

`persistence.semantic_fact_references.semantic_fact_id()` calls
`reconstruct_files(connection, snapshot_id)` and then selects one artifact from the reconstructed
mapping.

Semantic planning already has `file_fact_id` in each inventory module. Nevertheless:

- `_ensure_job()` calls `semantic_fact_id()` while inserting each module job;
- `_upsert_state()` calls `semantic_fact_id()` while recording each module state.

For 1,881 modules, a single planning pass performs thousands of complete 1,881-file
reconstructions. The measured result was approximately 122 seconds of CPU-bound planning after the
structural scan had already finished.

#### Required correction

Pass the existing canonical `file_fact_id` through the planning record into `_ensure_job()` and
`_upsert_state()`. Group/repository scopes can continue using `None`. A migration/backfill helper
may reconstruct snapshots, but the live per-module planning path must not.

Add an instrumentation test that counts calls to `reconstruct_files`. A 2,000-module plan should
perform a bounded number of reconstructions independent of module count, not merely happen to pass
a generous wall-clock threshold on CI hardware.

### P0.3: the MCP agent path re-plans the whole repository for every job

`SemanticAgentService` currently does the following:

- `claim_agent_work()` calls the full repository planner before every claim;
- `submit_agent_work()` calls the full repository planner after every completed submission.

Even after removing the quadratic fact lookup, this is unnecessary repeated work. With the current
measured planner it is catastrophic: a manual MCP job can pay roughly two full planning passes, one
before claim and one after submit.

Codex's documented MCP configuration has a default tool timeout of 60 seconds. A real MaxOS
planning pass took about 122 seconds, so ordinary MCP calls are expected to time out before the
server returns. The server runs synchronous handlers in worker threads, so a client timeout does not
necessarily cancel the underlying database operation.

#### Required correction

Use queue-first, stage-boundary planning:

1. atomically reclaim expired leases and try to claim an existing current-snapshot job;
2. if a job exists, return it without planning the repository;
3. only when no claimable current-stage job exists, run one planning pass to open the next stage;
4. try one claim again;
5. return a truthful terminal/waiting/paused status if no job exists;
6. after submit, commit the result and return status without a full planning pass;
7. let the next `WORK` call detect the empty stage and plan the next stage once.

The configured-provider/local runner already plans by stage and then claims jobs directly. The MCP
agent path should use the same lifecycle rather than a more expensive special case.

### P0.4: `understand` performs a synchronous scan before remote execution

The remote command path is:

```text
cli_semantic_commands._understand_service
  -> semantic_service.prepare_semantic_service
  -> POST /api/semantic/refresh?wait=true
  -> api_semantic_routes._prepare
  -> RepositoryScanner.scan
  -> SemanticEngine.bootstrap(plan_only=True)
  -> open MCP session and claim work
```

This couples four different responsibilities into one request:

- source discovery and hashing;
- structural snapshot creation;
- semantic queue planning;
- model-backed semantic execution.

The request provides no progress to the CLI and cannot reliably cancel server work on client
disconnect. The worker never reached MCP during the reproduced five-minute failure.

#### Required correction

Separate these operations:

- **Scan:** explicit static source refresh with its own asynchronous progress and cancellation.
- **Prepare:** lightweight semantic reconciliation against the current snapshot; no source scan.
- **Execute:** claim and complete the durable queue.

Add a narrow service operation such as `POST /api/semantic/prepare`. It should require an existing
current snapshot, reclaim leases, and plan only the current semantic stage. `understand` should use
that operation by default when a matching sidecar already owns the repository.

If there is no current snapshot, return a specific `scan_required` result and start or direct the
caller to the asynchronous scan path. Do not silently turn a queue-resume command into a six-minute
blocking structural rebuild.

An explicit `--scan` or `--refresh-scan` option may request structural refresh. It must expose
progress and must not be the default resume behavior.

### P0.5: configuration authority is split

The MaxOS checkout currently has an untracked local policy:

```text
/home/hcekne/repos/maxos_agent/.anaxigraph.yml
```

The running Docker service does not use that file. Its registry selects:

```yaml
repositories:
  maxos-agent:
    path: /repo
    config: /config/policies/maxos-agent.anaxigraph.yml
```

`/config/policies` is a read-only bind mount of:

```text
/home/hcekne/repos/anaxigraph/examples
```

Therefore, the live authority is:

```text
/home/hcekne/repos/anaxigraph/examples/maxos-agent.anaxigraph.yml
```

At the same time, the host CLI loads and validates the checkout-local config before service
discovery. It can therefore reject an enabled service because the local file is disabled, or
proceed from a locally enabled policy only to be rejected by a disabled service policy.

The AnaxiGraph container cannot be the process intermittently rewriting the example file: the
mount is read-only and the runtime has no write path to it. The observed reversions came from host
workspace activity or Git operations. The product defect is that two plausible policy files exist
and the CLI does not make the actual authority obvious.

#### Required correction

- Discover the matching service before enforcing local semantic enablement.
- When a service is selected, the service's effective configuration is authoritative.
- Expose effective semantic execution limits and the exact service config source/hash in status and
  command results.
- Do not pretend a container path is directly editable on the host; report registry key and
  operator-owned source clearly.
- Prefer repository-local policy in ordinary generated registries, for example
  `config: /repo/.anaxigraph.yml`.
- Reserve external registry policy files for intentional centrally managed deployments.
- Make the CLI error name the authoritative config when semantic analysis is disabled.

The untracked MaxOS policy should either become the committed repository policy and registry
authority or be removed after the external policy is deliberately retained. Do not keep both as
competing instructions.

### P0.6: the control file is indexed as a module

The untracked `.anaxigraph.yml` increased the MaxOS module count. `.anaxigraph/**` is ignored, but
the root `.anaxigraph.yml` file is not.

The tool's own control file should not appear as an application module or receive an intrinsic
module dossier. Add it to the default ignore set, with a regression test for both tracked and
untracked control files.

### P0.7: expired leases are recovered only as a planning side effect

`SemanticLeaseService.reconcile()` can requeue expired work, but callers only reach it through the
full planner. `claim_next_job()` excludes expired workers from its concurrency count but does not
change their durable status. Read status can therefore continue to report old `running` jobs.

`SemanticRefreshCoordinator.start()` also refuses to start when status reports any running job,
without distinguishing a live lease from an expired one. One abandoned job can prevent normal
background refresh.

#### Required correction

- Reclaim expired current-snapshot jobs atomically at the claim boundary.
- Make stage planning use the same primitive.
- Report `running_live` and `running_expired` separately in diagnostics.
- Do not let an expired lease block the refresh coordinator.
- Preserve read-only semantics for ordinary status if desired, but provide an explicit truthful
  `reclaimable` count.

### P0.8: repository-sized MCP guidance points agents at the wrong workflow

Current server instructions and onboarding tell a connected coding agent to repeat
`WORK -> EVIDENCE -> SUBMIT` until the repository is complete. The packaged skill contains better
advice—it prefers the detached host executor—but an agent may have the MCP server without the
skill installed.

A finite coding chat should not manually consume thousands of queue items. It will eventually stop,
hit a tool timeout, encounter an approval boundary, or exhaust context. That is what happened in the
reported MaxOS attempt.

The current Codex MCP documentation lists tools, server instructions, Streamable HTTP, auth, and
elicitation support. It does not document server-initiated sampling as a supported Codex-client
feature. Therefore AnaxiGraph must not assume the MCP server can autonomously ask the connected
Codex client to perform thousands of model calls. This is an inference from the currently documented
feature list, and should be revisited only when a supported capability can be tested.

Reference: <https://learn.chatgpt.com/docs/extend/mcp.md>

#### Required correction

The first 512 characters of the MCP server instructions should say:

- use the durable host executor for a full baseline;
- use direct MCP work only for bounded/manual fallback;
- never report completion until semantic status is ready;
- never edit source while mapping.

Status and no-work responses should include a compact `recommended_action` when the remaining queue
is repository-sized. The command should omit `--model` unless the user explicitly chose a model.
This avoids failures from account-specific model availability.

### P0.9: detached-worker health is not durable enough

The background run record considers a `running` process active when its PID exists. During this
audit, an AnaxiGraph self-analysis worker had been externally sent `SIGSTOP`; its process state was
`T`, but `semantic-status` still regarded it as active. The record has no progress heartbeat.

This particular stop was caused by external test/operator activity, not by AnaxiGraph itself. The
product problem is that the status cannot distinguish healthy progress from a stopped or wedged
process.

#### Required correction

- record a heartbeat and last completed job/stage in the detached-run state;
- classify a live PID with an expired heartbeat as `stalled`, not `running`;
- make restart/resume idempotent after a stalled run;
- ensure transport errors release the current wave when possible and otherwise rely on bounded
  lease expiry;
- apply explicit MCP initialization and tool-call timeouts;
- ensure an abandoned Streamable HTTP client cannot prevent service shutdown.

## Existing parallel work in the checkout

Another coding agent was actively editing the main worktree during this audit. Its uncommitted work
includes, among other things:

- runtime `--parallel-jobs` and `--timeout-seconds` options;
- a `semantic_parallel.py` helper;
- parallel model execution in the local and remote workers;
- parallel taxonomy partitions;
- related tests and quality-baseline changes.

Preserve that work. Inspect `git status` and the complete diff before editing or rebasing.

That work may improve throughput after the queue-control path is repaired. It does not address the
six-minute synchronous preparation, structural invalidation from semantic settings, quadratic
fact lookup, per-claim full planning, or split configuration authority. Do not mark this incident
fixed based on parallel model calls alone.

Avoid an excessive default such as 30 concurrent model processes until rate-limit, memory, timeout,
and account behavior are measured. Repository policy should provide a safety ceiling; per-run
concurrency can select a lower value.

## Consecutive implementation plan

Merge and verify these slices in order. Later slices assume the earlier latency and authority
contracts.

### Slice 0 — freeze the failing contracts

Add characterization tests before changing behavior:

1. semantic-only config changes currently alter the structural signature;
2. a 2,000-module semantic plan currently performs repeated full reconstruction;
3. an agent claim currently plans before an already-pending job;
4. an agent submit currently re-plans the repository;
5. an expired lease remains visibly running until planning;
6. remote `understand` calls the blocking scan-and-plan endpoint;
7. service and checkout policy can disagree without a clear authority error;
8. root `.anaxigraph.yml` is discovered as a module.

Record the current timing fixture and hardware metadata. Assertions should primarily use work
counters and call counts so CI is not flaky.

### Slice 1 — make planning linear and stage-driven

1. Carry canonical `file_fact_id` from `semantic_inventory` into job and state persistence.
2. Remove live per-module calls to full `reconstruct_files`.
3. Add atomic expired-lease reclamation to job claim.
4. Change agent claim to queue-first, plan-on-empty, claim-once-more.
5. Remove unconditional planning after agent submit.
6. Make local-provider and agent-provider runners share the same stage-boundary semantics.

Exit gate:

- 2,000-module preparation is linear by instrumentation;
- pending-job `WORK` p95 is below two seconds on the benchmark host;
- `SUBMIT` p95 is below two seconds;
- opening a new stage is below ten seconds;
- all existing lease, retry, idempotency, taxonomy, and pattern contracts pass.

### Slice 2 — separate structural and semantic identities

1. Add a named structural config projection.
2. Exclude semantic, agent-query, and display-only policy from structural signatures.
3. Preserve semantic input invalidation through existing contract/evidence fingerprints.
4. Refresh finding and coverage interpretations without re-parsing source where possible.
5. Ignore `.anaxigraph.yml` as a source module.

Exit gate:

- changing only executor, timeout, concurrency, lease, or taxonomy-review settings keeps the same
  structural snapshot;
- unchanged MaxOS-like fixture scan reads/reuses rather than re-analyzes every file;
- changing a true discovery/parser/resolution input still invalidates conservatively;
- semantic contract or evidence changes still enqueue exactly the required semantic work.

### Slice 3 — establish one configuration authority

1. Discover an explicit/matching service before local semantic validation.
2. Add effective semantic policy/config provenance to the service status contract.
3. Use service limits for service-owned execution; keep CLI runtime overrides bounded by them.
4. Name the service config source in disabled/conflict errors.
5. Change generated/example registries to prefer `/repo/.anaxigraph.yml`.
6. Decide deliberately whether MaxOS commits its local policy or uses central operator policy.

Exit gate:

- no command needs two matching semantic blocks;
- service-backed execution succeeds when the service authority is enabled and no redundant local
  policy exists;
- disabled-service errors identify the authoritative file/registry key;
- the dashboard, REST, CLI, and MCP status agree on provider, enablement, limits, and config source.

### Slice 4 — make remote preparation nonblocking and resumable

1. Add lightweight semantic prepare/reconcile against the current snapshot.
2. Make remote `understand` use prepare, not synchronous scan.
3. Keep scan explicit/asynchronous with progress and cancellation.
4. Add bounded MCP initialization/tool-call timeouts.
5. Make detached-run state record heartbeat, stage, completed count, and last error.
6. Remove model IDs from the primary examples; let Codex choose its supported configured default.

Exit gate:

- background start returns within five seconds;
- no current-snapshot resume performs a structural scan;
- client interruption leaves no permanently active HTTP-operation gate;
- service shutdown completes promptly with a connected or failed worker;
- a killed worker can be relaunched and resumes from completed durable records.

### Slice 5 — correct agent guidance

1. Put the durable executor instruction first in MCP server instructions.
2. Align README, onboarding, Docker docs, and packaged skill.
3. Present manual MCP looping as a bounded fallback, not the primary full-baseline path.
4. Add truthful recommended actions and exact index/config authority to status.

Exit gate:

- a medium-capability agent given only MCP tools and server instructions chooses the durable command
  for a full map;
- it does not edit either repository to guess at policy authority;
- it does not claim completion from a partial coverage percentage;
- first-user documentation has one start path and one progress path.

### Slice 6 — prove complete execution

Run two different gates:

#### Deterministic CI gate

Use a real Streamable HTTP MCP server and a deterministic fake semantic provider:

- at least 200 modules for a complete semantic lifecycle;
- intrinsic and contextual dossiers;
- repository taxonomy proposal;
- two independent review passes;
- subsystem/area/repository synthesis;
- sparse pattern assessment and independent review;
- worker interruption and restart halfway through;
- an expired lease recovered automatically;
- final `coverage == 1.0`, `baseline_complete == true`, `semantically_ready == true`, and taxonomy
  ready;
- zero target-source writes;
- no duplicate current dossiers or unreleased running jobs.

Use a separate 2,000-module performance fixture to enforce linear planning and bounded tool latency
without paying for model output.

#### Paid/live MaxOS acceptance gate

After deterministic gates pass:

1. rebuild/restart the fixed sidecar;
2. verify MaxOS config authority once;
3. prepare snapshot 220 or a newer deliberate scan without re-reading unchanged source;
4. start one durable host executor without a model override;
5. confirm the command returns a durable run record within five seconds;
6. observe the first completed dossier and monotonic progress;
7. interrupt and restart once to prove resume;
8. let the run finish;
9. verify the four completion fields and finalized taxonomy;
10. record elapsed time, model provenance, input/output tokens, failures/retries, and final counts.

This live gate spends real model allowance and should not run on every CI build. It is mandatory
release evidence for the repair.

## Performance and reliability budgets

| Operation | Required budget on benchmark fixture |
|---|---:|
| `semantic-status` | p95 below 500 ms |
| Claim with pending work | p95 below 2 s |
| Submit a valid dossier | p95 below 2 s |
| Plan/open next stage for 2,000 modules | below 10 s |
| Start detached executor | below 5 s |
| Unchanged structural refresh, 2,000 modules | below 15 s |
| MCP/server shutdown after client cancellation | below 5 s |
| Full fake-provider lifecycle | bounded and non-interactive; exact threshold recorded by fixture |

The budgets should be ratified from the same runner used for baseline measurement. Work counters and
asymptotic assertions are binding across slower machines; absolute times are reference gates for the
recorded environment.

## Required test matrix

### Unit and component tests

- structural signature field inclusion/exclusion;
- root control-file ignore behavior;
- fact-reference propagation without snapshot reconstruction;
- queue-first claim;
- stage-boundary planning;
- submit without replan;
- expired lease reclaim;
- live-versus-expired running counts;
- refresh coordinator behavior with expired work;
- service-authoritative policy resolution;
- detached heartbeat/stalled status;
- model omission and runtime override validation;
- MCP read timeout and packet release on failure.

### Integration tests

- real REST service plus matching Docker-style Git identity;
- real Streamable HTTP MCP initialization, claim, evidence, submit, release, close;
- client timeout/cancellation does not leave an operation gate active;
- server restart between claims;
- background worker restart using the same sidecar index;
- config disagreement produces a precise authority error;
- unchanged semantic settings do not create a new structural snapshot.

### Regression gates

- full Python suite;
- Ruff and format checks;
- architecture, complexity, module-size, and self-analysis gates;
- packaging and first-user journey;
- Compose validation;
- browser contracts for semantic progress/failure/stalled states;
- changed-code coverage for the new orchestration branches.

## Immediate operational guidance for the current checkout

Until the P0 slices land:

1. Do not start another repository-sized manual MCP loop.
2. Do not treat increased `max_parallel_jobs` as the fix.
3. Do not toggle semantic policy repeatedly; in the current version it can force structural
   invalidation.
4. Do not run multiple preparation commands concurrently.
5. Inspect the active detached-run record and process state before starting a new worker. A stopped
   PID may currently look active.
6. Preserve the existing AnaxiIndex volume; completed dossiers are reusable.
7. Preserve the other agent's uncommitted worker/parallelism changes.
8. The current MaxOS snapshot 220 has already been prepared with 9 intrinsic dossiers reused and
   1,872 pending; avoid another structural refresh unless source actually changed.

## Non-solutions

The following changes may be useful later but do not close this incident:

- raising the preparation timeout above 300 seconds;
- telling users to raise Codex `tool_timeout_sec`;
- increasing concurrency to 30;
- adding more retry loops around HTTP 409;
- telling a coding chat to “keep calling WORK” more emphatically;
- adding another config file or hidden override;
- suppressing stale-running status without reclaiming the lease;
- testing only a ten-file repository;
- declaring success when intrinsic dossiers reach 100% but repository/taxonomy/pattern stages remain
  incomplete.

Longer timeouts conceal unbounded work. More parallel calls amplify it. The repair must remove the
unnecessary work and make authority/lifecycle explicit.

## Definition of done

This P0 is complete only when all statements below are true:

- A newly connected ordinary coding agent can identify the intended repository and policy without
  editing either checkout.
- One durable command starts or resumes the semantic baseline.
- The command returns immediately with durable status instead of blocking on a structural scan.
- Every MCP queue-control call completes comfortably within the documented client timeout.
- Planning work grows linearly with repository size.
- Semantic runtime changes do not create structural snapshots.
- Expired jobs heal on the next claim.
- A worker interruption and service restart do not lose completed work.
- MaxOS reaches 100% semantic coverage, repository synthesis, and a ready two-pass taxonomy.
- The dashboard, CLI, REST, and MCP report the same terminal truth.
- The complete deterministic suite and maintainability gates pass.
- The live MaxOS evidence is recorded in the roadmap/release notes.

Until that happens, AnaxiGraph has a promising semantic engine but not a dependable semantic
bootstrap product.
