# ADR 0007: Record semantic usage and executor effort as explicit provenance

- Status: Proposed
- Date: 3 September 2026
- Owners: AnaxiGraph maintainers
- Related: [`next-development-actions.md`](../next-development-actions.md) items 1.4, 1.5, 1.12,
  and 2.1; evidence record
  [`fresh-eyes-multi-model-review-2026-09.md`](../fresh-eyes-multi-model-review-2026-09.md)

## Context

AnaxiGraph records who produced each semantic result but not how much it cost to produce or how
hard the executor was asked to think. `semantic_jobs` and `semantic_documents` carry
`input_tokens`/`output_tokens INTEGER NOT NULL DEFAULT 0` and `executor_id`/`executor_model`
(`persistence/schema.py:180-181`, `:207-209`, `:218-219`); nothing records a cached-prompt split, a
reasoning effort, or whether a token count was reported at all. The September 2026 three-model
fresh-eyes review made three consequences visible in one index:

- **Usage state is inferred from magnitude.** `_completion` sets
  `usage_reported = result.input_tokens > 0 or result.output_tokens > 0`
  (`semantic_results.py:290`). For a configured `command`, `codex`, or `claude` provider that
  reported nothing it silently stores `max(1, estimated_input_tokens)` and
  `max(1, len(json) // 4)` in the token columns and leaves `actual_cost_usd = NULL` as the only
  marker (`:292-307`); `fail_job` accumulates tokens with no state at all (`:196-212`). Status
  telemetry derives `token_counts_reported` and `token_counts_missing` from `input_tokens > 0`
  (`semantic_status_queries.py:232-235`) while the `token_note` promises that a missing count means
  unknown usage, not a free call (`semantic_status.py:269-273`). `docs/data-model.md:108` says
  unreported use "remains zero"; `docs/advanced-operations.md:182-184` and the plugin skill say it
  is unknown. The promise has no column behind it.
- **Claude usage was recorded as 2 tokens per stage.** The Claude adapter reads only
  `usage.input_tokens` and `usage.output_tokens` (`semantic.py:221-227`) and ignores
  `cache_creation_input_tokens` and `cache_read_input_tokens`. Every generation-3 stage of the
  review persisted `input_tokens = 2` while the Codex comparison stage on the same packet recorded
  235,690. Because 2 is greater than 0, the rows count as fully reported. Item 1.4 fixes the parser;
  once it sums the categories into `input_tokens`, the cached/uncached split is lost at the
  persistence boundary unless a column keeps it, and terminal fresh-eyes job metadata is compacted
  to five keys (`semantic_results.py:326-334`), so `metadata_json` cannot hold it.
- **Effort is neither settable for Claude nor recorded per job.** `--reasoning-effort` is rejected
  unless the executor is Codex (`semantic_execution.py:119-120`) and the Claude adapter forwards
  only `--model` (`semantic.py:192-193`). The requested effort lives only in the run-level record
  (`cli_semantic_commands.py:184`, `semantic_background.py:176`); `claim_job` writes
  `executor_id`/`executor_model` and nothing else (`semantic_lease_claim.py:186-201`). Generation 2
  of the review ran at an unrecorded effort and generation 3 at `xhigh` through
  `CLAUDE_CODE_EFFORT_LEVEL`; no row distinguishes either from a default-effort run, so the
  diversity summary cannot tell two proposals that differed by effort from two that differed by
  model.

Two mechanics constrain the fix. The MCP tools `ANAXIGRAPH_SEMANTIC_WORK`,
`ANAXIGRAPH_SEMANTIC_SUBMIT`, and `ANAXIGRAPH_SEMANTIC_FAIL` are registered from Python signatures
through `server.add_tool` (`semantic_mcp.py:116-127`), so their parameters are the published
contract: `submit` and `fail` take `input_tokens: int = 0` (`:209-216`, `:248-255`), which makes an
agent that omits usage indistinguishable from one reporting zero, and `work` takes
`agent_id`/`agent_model` only
(`:168-171`). Columns added through `_ensure_legacy_columns` (`persistence/migrations.py:76-106`,
`:182-190`) run only inside `migrate_schema`, which `initialize_index` skips when the stored version
already equals `SCHEMA_VERSION` (`persistence/index_initialization.py:36-45`); tests on fresh and
schema-2 fixture indexes pass while every live schema-10 index would fail with `no such column`.
Commit `6ddd3f2` bumped 9 to 10 for the same reason when it added `executor_id`/`executor_model`,
and every upgrade first writes a backup of the live index (`:47-49`). The cross-phase
Maintainability gate requires an ADR for schema and public API decisions
(`feature-development-plan.md:4748`).

## Decision

### Schema 11: four provenance columns on jobs and documents

`SCHEMA_VERSION` becomes 11 in one change that adds the same four columns to `semantic_jobs` and
`semantic_documents`:

| Column | Type | Meaning |
|---|---|---|
| `cache_read_input_tokens` | `INTEGER NOT NULL DEFAULT 0` | Prompt tokens served from the provider's cache |
| `cache_creation_input_tokens` | `INTEGER NOT NULL DEFAULT 0` | Prompt tokens written to the provider's cache |
| `usage_source` | `TEXT NOT NULL DEFAULT 'unknown'` | `reported`, `estimated`, or `unknown` |
| `executor_effort` | `TEXT` | The effort requested for the run; `NULL` means executor default |

- `input_tokens` keeps meaning the complete prompt: uncached plus cache creation plus cache read.
  The two cache columns are a breakdown of that total, never an addition to it, so existing sums,
  cost arithmetic, and history stay comparable, and
  `cache_read_input_tokens + cache_creation_input_tokens <= input_tokens` holds on every row.
  Providers that report no cache categories store zero.
- `usage_source` is written by the completion and failure paths from an explicit `usage_reported`
  flag on `SemanticResult` and `SemanticAnalysisError`, set only when a provider parsed a usage
  object (Claude: `usage` or `modelUsage`; Codex: a usage event; command adapter: a `usage` key in
  the envelope). `reported` means the executor returned usage, zero included. `estimated` means a
  configured provider returned none and AnaxiGraph substituted its own estimate, as `_completion`
  already does. `unknown` means an agent-funded submission carried no usage; its token columns stay
  0 and `actual_cost_usd` stays `NULL`. Afterwards no code path derives reporting state from
  `input_tokens = 0`.
- `executor_effort` is the value the caller asked for: the local runner passes `reasoning_effort`
  through `claim_job`, the MCP `work` tool passes `agent_effort`, and the document copies the
  completing job's value at insert. It is never inferred; an executor default, including one set by
  `CLAUDE_CODE_EFFORT_LEVEL` in the caller's environment, is stored as `NULL` and rendered as
  "executor default", not "unknown effort". Effort names are executor-specific, so "the same
  effort" across Codex and Claude is nominal and readers say so.
- The migration backfills `usage_source` on existing rows of both tables with a heuristic labelled
  as such in the migration code and in `docs/data-model.md`: `reported` where
  `actual_cost_usd IS NOT NULL` (only a reported completion sets it), `estimated` where the row is
  completed, `provider != 'agent'` and `actual_cost_usd IS NULL`, and `unknown` otherwise, including
  every failed attempt and every zero-token agent submission. Token totals do not change.
- `SUPPORTED_SCHEMA_VERSIONS`, the version set in `_requires_materialized_frame_migration`
  (`migrations.py:28`, `:229`), the exact-set and `== 10` assertions, the schema-2 fixture
  assertion, and the parametrised future version in `tests/test_migrations.py:39-40`, `:63`, `:76`
  change in the same commit as the bump. `create_schema_backup` runs once for the whole change; the
  retained sidecar index exceeds 25 MB, which is one more reason to ship the three column families
  together rather than as three bumps.
- Cache-aware pricing (`cache_read_cost_per_million` and `cache_creation_cost_per_million` on
  `SemanticConfig`, used by `_cost`) is a named follow-up. Until it lands, `_cost` prices the whole
  prompt at the input rate exactly as today.

### The same-version column reconciliation rule

Item 1.12 must settle before this bump, and this ADR records the rule it settles:

- `_ensure_legacy_columns` is the single list of additive columns and also runs on the same-version
  open path in `initialize_index`, beside the idempotent reconciliations that already run there
  (coverage reference retirement, checkpoint policy, terminal metadata compaction, search
  projections). One `PRAGMA table_info` per table is cheap, and a live index whose stored version
  already matches can no longer fail with `no such column`.
- A version bump remains mandatory whenever a change gives existing rows a new meaning or rewrites
  them, because the bump is what triggers the backup and the supported-version audit. Schema 11
  bumps because of the `usage_source` backfill. A purely additive, defaulted column with no backfill
  may ship through reconciliation alone once a test opens a copy of a live-version index, finds
  every reconciled column, and completes a job on it.
- The exact `SUPPORTED_SCHEMA_VERSIONS` test stays exact so that no version enters the supported
  set without a deliberate edit.

### Widened, backward-compatible MCP arguments

The three completion tools gain optional arguments and keep their names, count, and annotations,
so the bounded ten-tool profile is unchanged:

- `ANAXIGRAPH_SEMANTIC_SUBMIT` and `ANAXIGRAPH_SEMANTIC_FAIL`: `input_tokens` and `output_tokens`
  become `int | None = None`; supplying both means `reported`, zero included, and omitting them
  means `unknown`. New `cache_read_input_tokens: int = 0` and `cache_creation_input_tokens: int = 0`
  carry the split. Integers already sent by existing agents keep working unchanged.
- `ANAXIGRAPH_SEMANTIC_WORK`: new `agent_effort: str = ""`, cleaned like `agent_model` and stored on
  the claimed job.
- The remote host executor (`semantic_remote_worker.py`) sends every new key on claim, submit, and
  fail; its argument builders move to a new `semantic_remote_payloads.py` because the module is at
  the 500-physical-line ceiling.
- `SemanticEngine.claim_agent_work`, `submit_agent_work`, `fail_agent_work`, and
  `validate_submission` accept the same optional values. CLI, REST, MCP, and the dashboard read the
  same columns, so every surface reports the same usage state and effort.

Semantic status exposes both cache sums per action and in totals (`_action_totals`,
`semantic_status.py:326-343`), replaces the magnitude-derived counts with
`SUM(usage_source = 'reported')` and `SUM(status = 'completed' AND usage_source = 'unknown')`, adds
`token_counts_estimated` and an `efforts` list per action, and rewrites the `token_note`. Fresh-eyes
provenance and diversity blocks gain `executor_effort`. `docs/data-model.md`,
`docs/advanced-operations.md`, `docs/onboarding.md`, `docs/capabilities.md` (once committed), and
the plugin skill describe the three usage states and the effort column with one wording.

## Consequences

- Every live index is backed up once and upgraded once to schema 11. Indexes at schema 2 and 6
  still migrate through the existing fixtures. This ADR is accepted before the bump merges, as the
  increment's exit gate requires.
- Token telemetry becomes truthful and comparable across executors: a Claude stage shows its full
  prompt with a visible cache split, an agent that omits usage is counted as `unknown`, and an
  AnaxiGraph estimate is labelled `estimated` instead of passing as reported. In the retained
  sidecar index at the time of writing, 3,166 of 6,359 Codex-executed jobs are completed with zero
  tokens and will be labelled `unknown`, which is the reading the `token_note` always promised.
- The backfill is a heuristic over rows written before the column existed and is documented as
  such; it is not ground truth about past model calls.
- Third-party agents that send integer token counts see no change. An agent that omitted usage now
  produces an `unknown` row rather than a `reported` zero; that is a labelling change, not a
  refusal. The FastMCP-published schemas of three tools change additively.
- Recorded effort is the requested effort. The Claude envelope does not echo the effective value, so
  a `NULL` must never be read as "no effort was applied".
- Executor, model, effort, and usage remain excluded from semantic freshness fingerprints; changing
  any of them never makes a saved document stale.
- `_completion`, `_finish_job`, `_insert_document`, `fail_job`, `_action_totals`, and the status
  query each grow by the same four fields; where a touched module approaches the ceiling the plan
  names the destination (`semantic_completion.py`, `semantic_status_telemetry.py`).
- Cache-aware pricing, per-generation stage telemetry, and dashboard rendering of token facts are
  separate items and are not decided here.
- Removing or renaming any of the four columns, or narrowing a widened MCP argument, requires a new
  ADR and a new schema version.

## Alternatives rejected

- **Nullable token columns, with `NULL` meaning unknown.** Distinguishes unknown from zero but
  cannot express `estimated`, forces `NULL` handling into every `SUM`, `COALESCE`, `+=`
  accumulation, cost formula, and reader, and turning `NOT NULL DEFAULT 0` into a nullable column in
  SQLite means rebuilding both tables. One explicit state column keeps the numeric columns
  arithmetic-safe and adds the third state.
- **Per-provider usage tables** (for example `semantic_usage_claude` with Anthropic's cache fields
  and `semantic_usage_codex` with reasoning-token fields). Adds a table family that the roadmap's
  complexity exclusions forbid, splits every status and telemetry query by provider, and breaks
  actor-neutrality because CLI, REST, MCP, and the dashboard would no longer read one row. The
  provider-specific shape that matters for cost and comparison is two integers; anything further
  stays in the executor's own logs.
- **Keeping the cache split or effort in `metadata_json`.** Terminal fresh-eyes job metadata is
  compacted to five keys at completion (`semantic_results.py:326-334`), and SQL aggregation across
  actions needs columns, not JSON.
- **Inferring effort when none was requested**, for example recording the Claude CLI default. The
  default depends on the caller's environment and the envelope does not echo it; a guessed value is
  worse provenance than an honest `NULL`.
- **Three separate schema bumps, one per item.** Each forces its own backup of the same live index
  and its own supported-set edit for columns that always ship together; one bump with one ADR is
  the smaller change.
- **A version bump as the only way a column reaches a live index.** Keeps the trap item 1.12 found
  (fixture tests pass while live indexes fail) for every future additive column and turns each of
  them into a backup event; reconciliation on the same-version path is already the pattern for the
  checkpoint policy and the search projections.
