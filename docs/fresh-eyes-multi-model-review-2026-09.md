# Fresh-eyes multi-model review, September 2026

On 2 and 3 September 2026 the fixed fresh-eyes recipe ran three times against this repository in
the Docker sidecar: twice with Codex and once with Claude Fable 5.1. This document retains the run
as an evidence record beside [`releases/0.4.0.md`](releases/0.4.0.md) and
[`maxos-agent.md`](maxos-agent.md). The numbers were copied from the sidecar's AnaxiIndex
(`semantic_jobs` and `semantic_documents`) and the background run records; the readings of the
review content are grep-level inspections of the source at commit `b6f6a9a`, not test runs. What
to do about the findings is decided in
[`next-development-actions.md`](next-development-actions.md), not here.

## Setting

- **Repository:** `anaxigraph`, `repository_id` 1, served by the sidecar at
  `http://127.0.0.1:8765` from `/state/anaxi-index.db`; scanner version 0.4.0.
- **Recipe:** the roadmap's fixed fresh-eyes recipe (§10.7): two independent clean-sheet
  proposals, a blind adjudication, an as-built comparison, and a mission filter (the review).
- **Brief:** the identical behavior-only Capability Brief, fingerprint
  `6d575ba27a7877e7434081537bf97677286ed418e2bd2d9c80d60e9117745315`, fed all three generations.
- **Snapshots:** 1039 for generation 1; 1058 for generations 2 and 3. Snapshot 1058 was scanned
  from commit `b6f6a9a34a58eb42a00e086bf355c6cab1e40721` with a dirty working tree, fingerprint
  `ee9a3a2d1b120b161042a2bab8c29e81a6de1746b385b80740e0d693b95db225`.
- **Executors:** one background host worker per generation, started with
  `anaxigraph understand --executor codex|claude --background`. Each worker claims through the
  sidecar's MCP surface, so every job records `provider: agent` with executor id
  `cli:<executor>:<pid>`. No repository source was edited by any generation.

## The three generations

| Generation | Snapshot | Executor id | Model | Effort | Run id | Started (UTC) | Finished (UTC) | Wall clock | Kept / rejected | Review confidence | Documents |
|---:|---:|---|---|---|---|---|---|---|---:|---:|---|
| 1 | 1039 | `cli:codex:140478` | `gpt-5.6-terra` | medium (run record only) | not retained | 2026-09-02 22:02:10 | 22:06:47 | 4 min 37 s | 3 / 2 | 0.90 | 6657–6661 |
| 2 | 1058 | `cli:codex:522987` | `gpt-5.6-sol` | not recorded | `655a8f7d-3731-44ed-a8f5-a956a14d1e13` | 23:26:54 | about 23:49:30 | about 22 min 36 s | 5 / 5 | 0.92 | 6897–6901 |
| 3 | 1058 | `cli:claude:580214` | `claude-fable-5-1` | `xhigh` via `CLAUDE_CODE_EFFORT_LEVEL`, not recorded | `3bdefed4-05b0-4d9f-8d8f-c238d3d3f7e2` | 23:51:12 | 2026-09-03 00:16:30 | 25 min 18 s | 7 / 11 | 0.70 | 6902–6906 |

Generation 2 was started by another agent against the same sidecar; its finish time comes from its
run record and is approximate. Generation 3 ran with 4 parallel jobs and a 1,200-second per-call
timeout. All fifteen stage jobs completed on their first attempt.

## Stage telemetry

Seconds are `completed_at - started_at` of the job row. Token counts are the values stored on the
job and copied to its document. Document bytes are `length(value_json)`.

### Generation 1: Codex `gpt-5.6-terra`, snapshot 1039

| Stage | Job | Document | Started | Completed | Seconds | Input tokens | Output tokens | Document bytes |
|---|---:|---:|---|---|---:|---:|---:|---:|
| Proposal A | 24578 | 6657 | 22:02:39 | 22:03:24 | 46 | 16,966 | 2,298 | 11,602 |
| Proposal B | 24579 | 6658 | 22:02:39 | 22:03:30 | 52 | 34,090 | 2,476 | 11,141 |
| Blind adjudication | 24580 | 6659 | 22:03:46 | 22:04:57 | 70 | 21,839 | 3,679 | 17,244 |
| As-built comparison | 24581 | 6660 | 22:05:11 | 22:05:58 | 48 | 234,433 | 2,302 | 12,416 |
| Mission filter | 24582 | 6661 | 22:06:10 | 22:06:47 | 37 | 19,505 | 1,785 | 8,943 |
| **Total** | | | | | **252** | **326,833** | **12,540** | |

### Generation 2: Codex `gpt-5.6-sol`, snapshot 1058

| Stage | Job | Document | Started | Completed | Seconds | Input tokens | Output tokens | Document bytes |
|---|---:|---:|---|---|---:|---:|---:|---:|
| Proposal A | 24920 | 6897 | 23:27:12 | 23:30:37 | 205 | 16,781 | 11,165 | 18,038 |
| Proposal B | 24921 | 6898 | 23:27:12 | 23:31:04 | 232 | 16,781 | 12,682 | 17,154 |
| Blind adjudication | 24922 | 6899 | 23:31:28 | 23:37:07 | 339 | 24,210 | 18,588 | 33,393 |
| As-built comparison | 24923 | 6900 | 23:37:19 | 23:44:31 | 431 | 235,690 | 20,055 | 22,382 |
| Mission filter | 24924 | 6901 | 23:45:05 | 23:48:57 | 232 | 21,137 | 8,515 | 18,430 |
| **Total** | | | | | **1,439** | **314,599** | **71,005** | |

### Generation 3: Claude `claude-fable-5-1`, snapshot 1058

| Stage | Job | Document | Started | Completed | Seconds | Input tokens | Output tokens | Document bytes |
|---|---:|---:|---|---|---:|---:|---:|---:|
| Proposal A | 24925 | 6902 | 23:51:34 | 23:55:04 | 210 | 2 | 14,302 | 19,429 |
| Proposal B | 24926 | 6903 | 23:51:34 | 23:55:06 | 212 | 2 | 17,150 | 20,236 |
| Blind adjudication | 24927 | 6904 | 23:55:33 | 00:00:56 | 323 | 2 | 26,358 | 44,754 |
| As-built comparison | 24928 | 6905 | 00:01:18 | 00:10:32 | 555 | 2 | 40,178 | 56,602 |
| Mission filter | 24929 | 6906 | 00:10:45 | 00:16:02 | 317 | 2 | 21,513 | 30,016 |
| **Total** | | | | | **1,617** | **10** | **119,501** | |

The generation-3 input tokens are an adapter defect, not usage: the Claude adapter reads only
`usage.input_tokens` and ignores the cache-creation and cache-read categories, so every stage
recorded 2. The comparison stage alone carried about 235,000 prompt tokens in the Codex run on the
same packet. Claude output tokens include thinking tokens. Generation-1 jobs carry no generation
number; generations 2 and 3 carry `review_generation` 2 and 3.

## Defects in AnaxiGraph surfaced by running the experiment

Observed while operating AnaxiGraph itself and verified against the source at `b6f6a9a`.

- **Claude effort cannot be set and is not recorded.** `understand --executor claude
  --reasoning-effort` is rejected as Codex-only (`semantic_execution.py:119-120`) and the adapter
  forwards only `--model` (`semantic.py:192-193`). Setting `CLAUDE_CODE_EFFORT_LEVEL=xhigh` in the
  launch environment worked (0 thinking tokens at `low` versus 352 at `xhigh` on the same prompt),
  but no job, document, or run record stores that effort.
- **Claude input tokens are under-reported.** `semantic.py:221-227` reads `usage.input_tokens` and
  `usage.output_tokens` only; `cache_creation_input_tokens`, `cache_read_input_tokens`, and the
  `modelUsage` map are ignored, so every generation-3 stage persisted `input_tokens = 2` and,
  because 2 is greater than 0, counts as fully reported usage.
- **The CLI's fixed 30-second client timeout stranded a restart.** During a sidecar "database is
  locked" stall, `fresh-eyes --restart` reported "timed out" while the plan stayed at generation 2
  (`semantic_service.py` uses `timeout: float = 30` for the start POST). A direct `POST
  /api/fresh-eyes` with a long timeout succeeded.
- **The Codex baseline worker failed twice with an opaque error.** Both runs ended with `Remote
  semantic execution failed: unhandled errors in a TaskGroup (1 sub-exception)` and no traceback in
  the run log; one failure coincided with a sidecar database-lock exception and a container restart
  at 23:10 UTC. The third attempt completed.
- **Restart serialization works as designed.** `--restart` answered HTTP 400 while the other agent's
  review was unfinished, which sequenced generation 2 ahead of generation 3; the per-repository
  background lock likewise refused a second background worker.
- **A second worker would be told the queue is complete.** `agent_no_work_status` returns `complete`
  when the baseline is ready before it checks running jobs (`semantic_agent_protocol.py:184-189`).
- **`cross_provider` can never be true in agent mode.** It is `len(providers) > 1`
  (`semantic_fresh_eyes_review.py:405`) over a provider column that is always the constant `agent`
  for host executors.

## What the reviews found

### Generation 3 recommendations and spot checks

Ranked as the mission filter ranked them. The outcome column is a grep-level reading of the source
at `b6f6a9a`; none of these checks ran tests.

| Rank | Recommendation | Confidence | Outcome | Where |
|---:|---|---:|---|---|
| 1 | Give each read its own view of one scan so a second read cannot swap TEMP rows underneath it | 0.72 | Closed on inspection: `AnaxiIndex.connect()` opens a new connection per call and projections are connection-local TEMP tables | `storage.py:33-38` |
| 2 | Prepare AI work from an existing scan without a new scan | 0.66 | Partly confirmed: the local-index path scans unconditionally; the service path already returns `scan_required` and `POST /api/semantic/prepare` exists | `cli_semantic_commands.py:165-169` |
| 3 | Count the agent submission limit in encoded bytes, as its constant says | 0.90 | Confirmed: the constant is `_MAX_SUBMISSION_BYTES` and the comparison counts characters | `semantic_agent_contracts.py:30`, `:76` |
| 4 | Save unknown coding-agent token use as unknown instead of zero | 0.70 | Partly confirmed: token columns are `NOT NULL DEFAULT 0`, `usage_reported` is inferred from tokens greater than 0, and three documents disagree | `persistence/schema.py`, `semantic_results.py:290` |
| 5 | Refuse an AI result that cites evidence not found in the job's pages | 0.60 | Not viable as specified: evidence fields are free-text string arrays | `semantic_contract.py` |
| 6 | Share the four target-file safety checks between the two AI request builders | 0.65 | Confirmed duplication | `semantic_requests.py:72-87`, `semantic_pattern_requests.py:118-127` |
| 7 | Use one path-to-module-name function for new analysis and saved rows | 0.55 | Confirmed duplication; `ir_serialization.py` does not import `ir.py` and `ir.py` imports it lazily, so a cycle is the risk | `ir.py:45-94`, `ir_serialization.py:245-251` |

Generation 3 rejected eleven clean-sheet ideas with repository-specific reasons: refusing instead
of repairing file-group replies, storing all source text in the index, one reader object for every
path, a pending scan row with start-up cleanup, removing file watching, a delete-one-scan command, a
single settings file for every cap, a rebuild-findings command, splitting six branch-heavy functions
on a count alone, removing a possibly unused import that is a deliberate re-export, and cosmetic
service-lookup and import rewiring. Several rejections overrule its own adjudicated reference
design.

### Cross-generation reading

A 15-agent workflow (3 readers, 1 synthesizer, 11 skeptics) verified 8 of 11 cross-generation
claims against the source documents; the three refutations concerned the wording of "convergent"
themes and are reflected in the table.

| Theme | Gen 1 | Gen 2 | Gen 3 | Verified reading |
|---|---|---|---|---|
| Count the submission limit in bytes, not characters | — | #1 | #3 | The only cross-provider agreement on a concrete change, and a real defect |
| Isolate reads from connection-local TEMP rows | #1 | #3 | #1 | All three recommend it and all three gate it on inspection; inspection closes it. A shared misjudgment seeded by the packet's own coherence note, not a shared discovery |
| Keep the product; do not rebuild to the smaller reference | #3 | rejected ideas | rejected ideas | Same conclusion in different form |
| Split branch-heavy functions | #2 | — | declined | A direct disagreement on the same six functions |
| Prepare AI work without a hidden rescan | — | — | #2 | Claude only; half done on the service path |
| Unknown token use is not zero | — | — | #4 | Claude only; a real document conflict |
| Share the four file-safety checks; one module-identity function | — | — | #6, #7 | Claude only; confirmed duplication |
| Scan live folders from a temporary copy and recheck | — | #2 | rejected | Codex only; the premise holds but it is the most expensive item in any generation |
| Explicit reply for a missing scan instead of an empty graph | — | #3 | — | Codex only; partly justified |
| Two-connection tests for worker claims; guard before binding a non-loopback address | — | #4, #5 | — | Codex only; not independently verified by a skeptic |

Both generations on snapshot 1058 independently noticed that a "current" pointer must be kept per
repository, the one design detail with genuine cross-provider agreement. Generation 3 named about
fifteen files, commit `b856bce`, and a benchmark; generation 2 named no files by design; generation
1 named one function. Generation 2 ranked the verified bug first; generation 3 ranked by mission
promise, so a probable non-issue at 0.72 sits above a certain fix at 0.90. Generation 3 reported the
lowest confidences and they fit the outcome best. All three adjudications disclosed that same-model
agreement is not independent confirmation. After checking, generation 1 yields no code change,
generation 2 one certain fix, one clarity fix, and one tests-only item, and generation 3 the same
certain fix, one CLI option, one safety-motivated consolidation, one test-first consolidation, and
one documentation decision.

## Caveats

- **Same-model proposals.** Both proposals inside a generation came from one model in one session,
  so agreement within a generation is one model's opinion counted twice, and agreement between
  generations 1 and 2 is one provider counted twice. Generation 3 disclosed same-session execution
  and that its proposal workers could see a host `git status` header.
- **Dirty snapshot.** Snapshot 1058 was scanned from an uncommitted working tree at `b6f6a9a`, so
  the reviewed source is not exactly the committed source, and nothing in the review or Charter
  payload marks it.
- **Effort gap.** Effort was `medium` for generation 1 (run record only), unrecorded for
  generation 2, and `xhigh` through an environment variable for generation 3. Effort is not stored
  per job or document, so part of the depth gap between generations is budget rather than model and
  cannot be audited from the index.
- **Token-recording gap.** Claude prompt tokens were recorded as 2 per stage and Claude output
  tokens include thinking, so the stored rows do not support a cost comparison across generations;
  the 2-token rows passed as reported usage because reporting state is inferred from magnitude.
- **Different packets.** Generation 1 read snapshot 1039's evidence packet; generations 2 and 3
  read snapshot 1058's.
- **Generation 2 provenance.** It was run by another agent; its run log is not retained here and
  its finish time is approximate.
- **Reachability.** Fresh-eyes status shows one generation and a bare `previous_review` pointer, so
  generation 2 is reachable only through SQL until generations are enumerated.
- **Spot checks are readings, not tests.** Every outcome above is a grep-level inspection.

## Where the raw facts live

- Sidecar AnaxiIndex `/state/anaxi-index.db` (Docker volume `anaxigraph_anaxi_index`):
  `semantic_jobs` ids 24578–24582, 24920–24929; `semantic_documents` ids 6657–6661, 6897–6906;
  `snapshots` 1039 and 1058. The stage tables above are re-derived with:

  ```sql
  SELECT id, snapshot_id, scope_key, executor_id, executor_model,
         input_tokens, output_tokens, started_at, completed_at
  FROM semantic_jobs
  WHERE snapshot_id IN (1039, 1058) AND job_kind LIKE 'fresh_%'
  ORDER BY id;
  ```

- Background run records under `~/.local/state/anaxigraph/semantic-runs/<index hash>/latest.json`
  on the host that launched each worker, carrying the run id, executor, model, requested effort
  (Codex only), PID, log path, and terminal result.
- `anaxigraph fresh-eyes . --json --service-url http://127.0.0.1:8765` returns generation 3 with
  documents 6902–6906.

## How to rerun

```bash
SERVICE=http://127.0.0.1:8765

# 1. Plan a new generation. The request is refused with HTTP 400 while another review is
#    unfinished, and the CLI's fixed 30 s client timeout can report "timed out" while the sidecar
#    keeps planning: check the status before posting again, and post at most once.
anaxigraph fresh-eyes . --restart --json --service-url "$SERVICE"
anaxigraph fresh-eyes . --json --service-url "$SERVICE"

# 2. Drive every stage with the Claude CLI. At b6f6a9a --reasoning-effort is rejected for Claude,
#    so effort must come from the environment, and it is not recorded: write it down with the run.
CLAUDE_CODE_EFFORT_LEVEL=xhigh anaxigraph understand . --executor claude --background --json \
  --service-url "$SERVICE"

# 3. Follow progress; the run record, its PID, and its relaunch command are in semantic-status.
anaxigraph semantic-status . --json --service-url "$SERVICE"
anaxigraph fresh-eyes . --json --service-url "$SERVICE"
```

For a Codex generation replace step 2 with `anaxigraph understand . --executor codex
--reasoning-effort medium --background --json --service-url "$SERVICE"`; the effort is stored in the
run record only. Before comparing a new generation with the three above, confirm that the Capability
Brief fingerprint in its stage input manifests still equals `6d575ba2…`; a changed brief makes the
generations incomparable, and a dirty working tree should be noted with the run.
