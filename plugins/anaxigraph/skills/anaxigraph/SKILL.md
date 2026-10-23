---
name: anaxigraph
description: Use AnaxiGraph's saved semantic graph to understand a repository, locate behavior and caller contracts, plan changes, inspect impact and tests, build or resume mapping, evaluate the pattern catalogue, or run an implementation-blind Fresh Eyes architecture review.
---

# AnaxiGraph architecture workflow

Use AnaxiMCP for repository understanding and coordination. Keep source edits in the normal coding
workflow. A graph edge, missing edge, finding, or AI interpretation alone does not justify a refactor.

## Select the exact checkout

Call `ANAXIGRAPH_REPOSITORIES` and match the working tree by exact path. A container path such as
`/repo` can differ from the host path; then match canonical Git remote plus checkout commit and dirty
fingerprint. A shared remote alone cannot distinguish worktrees. Prefer `index.repository_id` from an
existing `understand` receipt. If multiple candidates remain, ask which indexed repository to use.
Use `repository="<id>"` in subsequent MCP calls; `repository_id` is the REST parameter.

If AnaxiMCP is absent, use the authorized installation to start
`uvx --from anaxigraph anaxigraph up . --semantic agent` or the existing container service and connect
to `http://127.0.0.1:8765/mcp`. Do not invent map results. Check the indexed checkout, commit, dirty
fingerprint, structural freshness and annotation freshness separately.

## Read progressively

- Start with `ANAXIGRAPH_OVERVIEW` for purpose, capabilities, responsibility areas and readiness.
- Use `ANAXIGRAPH_GRAPH` to search behavior or page modules, functions, interfaces and contracts.
  Read the one-sentence overviews first. Pass the returned entity ID to `ANAXIGRAPH_ENTITY` for
  its saved paragraph, function summaries, full obligations, typed connections, tests and provenance.
  Expand a graph entity to traverse callers or dependencies. Preserve its repository and revision.
- `ANAXIGRAPH_SEARCH` and `ANAXIGRAPH_FILE` give compact compatibility views by default.
  Request `details=true` when you need complete saved facts. Neither a structural-only record nor
  an unresolved relationship is a verified behavioral claim.
- `ANAXIGRAPH_GUIDE` with `build`, `refactor` or `improve` combines placement and relevant evidence;
  use `ANAXIGRAPH_IMPACT` before changing shared behavior. Follow the linked contracts and tests.
- Use `ANAXIGRAPH_FINDINGS` for the `attention` view and `ANAXIGRAPH_FINDING_CONTEXT` for a selected
  finding. `planned` records chosen work. Read `finding_history` to distinguish new, persistent,
  resolved and returned signals; retained history can sample commits.
- The dashboard Changes journey exposes saved comparisons and optional Git history replay. Start
  or cancel history imports when requested. A missing finding does not establish a successful fix.

For a coding handoff, include the checkout/revision, primary owners, caller obligations, affected
code, relevant tests, uncertainty and the smallest justified change. Let the user's goals and taste
steer the plan. Do not anchor every design discussion to one favorite pattern.

## Keep development responsive

Reuse the coding host's persistent AnaxiGraph service, local rebuildable index and structural watcher.
Register each clone/worktree as a separate checkout; share portable understanding between hosts. Call Guide once before a coherent task, use focused tests while
editing, then call `ANAXIGRAPH_SCAN` at the verification checkpoint. Repeat only the queries needed
to check changed responsibilities or contracts. Avoid model-backed mapping after every save.

After a coherent task or commit, run one incremental Mapping workflow if updated annotations matter.
Unchanged compatible analyses must be reused. Wait for `semantically_ready: true` when the next
decision needs a complete current map; structural navigation remains available independently.

## Build or resume Mapping

Do not edit repository source while performing Mapping. New mapping writes one compact annotation
per module: an overview sentence, a short detail paragraph, one sentence per supplied function,
named caller contracts linked to those functions, and useful capabilities. It does not write two
intrinsic/context essays or duplicate Pattern/Planning recommendations. Group summaries stay concise.

Prefer the durable authenticated host executor for a full baseline:

1. Select the authorized executor and worker model independently of this chat's model. Respect exact
   user choices and installed model names; pass model and optional effort as runtime arguments.
2. Launch once: `anaxigraph understand <repository> --executor <executor> --model <model>
   --parallel-jobs <slots> --background --json`. The runner supports 30+ concurrent model jobs within
   the repository's shared `semantic.max_parallel_jobs`; multiple executors share that capacity.
3. Preserve the returned index authority, `execution_run.run_id`, model, executor and log path.
   `already_running` reuses that run. Do not create supervisor scripts or competing restart loops.
4. Use compact `ANAXIGRAPH_SEMANTIC_STATUS` or `anaxigraph semantic-status <repository> --compact
   --json` on request or after `poll_after_seconds` (normally 300). Honor an explicit request to
   wait for completion; otherwise return the durable handle. Resume using the same command/index.

The runner owns leases, retries, bounded batches and saved progress. A preparation HTTP 409 is not
permission to relaunch. If no authenticated executor exists, report that missing dependency.
`details=true` on semantic status exposes timing, tokens, executor/model, failures and provenance.
Unknown token usage is not zero cost; summed parallel job time can exceed elapsed wall time.

For an explicitly selected manual task, fetch only the schema named by
`response_contract.schema_arguments`. Annotation packets advertise `artifact="graph_annotation"`.
Fetch every listed evidence page, preserve all functions, and submit the exact advertised contract;
the submission argument retains the compatibility name `dossier`. Release an unfinished lease before
handing it off. Never substitute a five-field group summary for an eight-field module annotation.

## Evaluate Patterns

Use the Pattern workflow for systematic architectural opportunities. It considers every card in the
versioned catalogue across the repository, rates suitability separately from existing presence, and
records contextual pros, cons, implementation placements, costs, confidence and contrary evidence.
Read global considered/rated/reviewed/unresolved counts separately from a displayed page. Missing or
insufficient evidence is unresolved, not a zero score or a clean architectural endorsement. A useful
pattern can be an opportunity without an existing bug; compare concrete benefits with its added
complexity. Preserve poor-fit ratings as well as recommendations so coverage is auditable.

## Run implementation-blind Fresh Eyes

Fresh Eyes redesigns required functionality without seeing raw source, current file/module names,
actual topology, Pattern verdicts or implementation-specific steering. Every hierarchy, proposal,
comparison and final review pass is tool-free and receives only allowed functional evidence.
Source-specific constraints belong in Planning. Never add source/evidence tools to overcome a context
limit; reduce functional scope or increase the configured inline context budget instead.

1. Read `ANAXIGRAPH_GUIDE(fresh_eyes=true)` or `intent="redesign"`. If explicitly requested and not
   started/stale, call with `start=true`, retaining three alternatives per scope by default; five
   is optional. Retry failed batches without discarding successful results. `restart=true` creates
   a new generation and preserves the originals.
2. Run the durable host executor. The workflow prepares a functional product/capability/subsystem
   hierarchy, generates independent alternatives from parents to children, compares all retained
   alternatives blindly, and performs a final functional review. It does not collapse to one design.
3. For full non-product designs, request `ANAXIGRAPH_GUIDE(intent="redesign",
   scope_id="<returned-scope-id>", details=true)`. Read each scope's alternatives, pros/cons,
   assumptions, disagreements, parent compatibility and
   isolation provenance. Different models or sessions do not prove independent agreement; an
   unattested external worker remains unverified. Completion requires `ready=true, state="current"`.
4. Compare saved generations by their complete original records. This is a side-by-side historical
   view, not a newly inferred agreement score. Legacy v1 documents are read-only archives.

## Plan an architecture target

Call `ANAXIGRAPH_GUIDE(intent="plan")`; direction can be blank. `start=true` prepares work for the
background executor. Planning brings observed graph evidence, Pattern assessments and retained
Fresh Eyes alternatives together. Compare preserving sound boundaries with evolutionary and other
justified options; let the agent select a default when the user does not steer.

Read the current and proposed diagrams, contracts, migration risks and next milestone. Use
`target_option` to select a saved option. After actual tests, report `milestone`,
`milestone_status="verified"` and `verification_evidence`. A saved target can outlive its source
snapshot; keep stale evidence, proposed design, observed code and reported verification distinct.
Use `ANAXIGRAPH_GUIDE(reassess=true)` to compare compatible before/after maps after implementation.

## Share portable understanding

Explicit dashboard/headless workflows save the current portable record in `anaxigraph/` when
writable. After Git pull, import compatible fingerprinted analyses before buying new model work.
Queues, leases, credentials and rebuildable indexes stay local; Git carries concise current
understanding, selected analyses and provenance. `anaxigraph refresh . --workflows
mapping,patterns,fresh-eyes,architecture --json` supports scheduled runs and saves partial results.
Report mapped locally, record exported, Git committed and pushed separately. The caller owns Git
publication. Do not export the complete historical SQL cache or excluded runtime data.

Do not recommend deleting code solely because a static graph has no callers. Check dynamic loading,
framework wiring, external consumers and analyzer limitations before turning that signal into work.
