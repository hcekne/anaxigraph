---
name: anaxigraph
description: Ground software changes in AnaxiGraph's repository map, dependency evidence, findings, and semantic dossiers. Use when mapping or explaining a repository, bootstrapping or resuming semantic understanding, planning a feature or refactor, checking impact or dead-code evidence, investigating architecture findings, deciding where new code belongs, or verifying that a completed change improved the indexed architecture.
---

# AnaxiGraph architecture workflow

Use AnaxiMCP as evidence and coordination. Keep source edits in the normal coding workflow. Never
treat a graph edge, missing edge, finding, or model dossier as permission to refactor by itself.

## Establish the repository

1. Confirm that the `ANAXIGRAPH_REPOSITORIES` tool is available. If it is absent, stop and tell the
   user to start `uvx anaxigraph up . --semantic agent` or its Docker equivalent, then connect the
   client to `http://127.0.0.1:8765/mcp`. Do not invent index results.
2. Call `ANAXIGRAPH_REPOSITORIES`. Match the current working tree by exact path or canonical Git
   remote identity; a Docker mount such as `/repo` will not have the host path. If an `understand`
   result supplied `index.repository_id`, use that exact selector. Use the selected repository ID in
   every later call when more than one repository is listed.
3. If no path matches, or multiple candidates remain and the user did not select one, ask which
   indexed repository to use. Never silently analyze a similarly named repository.
4. Call `ANAXIGRAPH_OVERVIEW` and `ANAXIGRAPH_SEMANTIC_STATUS` before choosing a workflow. When the
   semantic baseline is current, call `ANAXIGRAPH_TAXONOMY` and use its area/subsystem hierarchy as
   the default map. State analyzer/resolution caveats when they materially affect the answer.

With no narrower request, summarize the repository's areas, dominant languages, active attention,
relationship completeness, history state, and semantic coverage. Keep deterministic facts and
model-derived interpretations visibly separate.

## Route the request

- For “map,” “understand,” “bootstrap,” or “resume semantics,” run the semantic baseline workflow.
- For a new feature or refactor, call `ANAXIGRAPH_SEARCH`, then `ANAXIGRAPH_SCOPE`; call
  `ANAXIGRAPH_FILE` for the primary modules and `ANAXIGRAPH_IMPACT` before changing a shared target.
- For a module question, use `ANAXIGRAPH_SEARCH` and `ANAXIGRAPH_FILE`. Compare responsibilities,
  collaborators, overlaps, extension points, pattern evidence, and counter-evidence.
- For architecture attention, call `ANAXIGRAPH_FINDINGS` with the bounded `attention` view. Use
  `ANAXIGRAPH_FINDING_CONTEXT` only for the chosen finding. A `planned` finding records that it was
  selected for work; other active findings are observations, not an implementation request. Read
  its `finding_history` to distinguish a new, persistent, resolved, or returned condition, while
  preserving the stated limit that retained maps may sample rather than cover every commit.
- For history questions, use `ANAXIGRAPH_HISTORY_STATUS` and the dashboard timeline. Start or cancel
  an import only when the user requests that index operation.
- Before an implementation, preserve
  `architecture_decision.verification.post_change_baseline` from `ANAXIGRAPH_SCOPE`. After the
  implementation, call `ANAXIGRAPH_SCAN` when available, then repeat `ANAXIGRAPH_SCOPE` with the
  exact same goal and pass the preserved object as `verification_baseline`. Report the returned
  `post_change_comparison` alongside focused test results. “No longer reported” is not proof that a
  finding was fixed, and `changed` is not proof that the architecture improved. Repeat any other
  relevant impact, finding, or module query needed to test the intended outcome.

## Work continuously during development

Keep one persistent AnaxiGraph service and structural watcher for the coding session. Build a full
semantic baseline only when no current baseline exists. For each coherent task:

1. Call `ANAXIGRAPH_SCOPE` once before editing, preserve the exact goal and baseline, and call
   `ANAXIGRAPH_IMPACT` for shared targets.
2. During edits, let the watcher update deterministic source facts and run focused tests normally.
   Do not start model-backed semantic work after every save.
3. At the verification checkpoint, call `ANAXIGRAPH_SCAN`, then repeat the same scope request with
   the saved baseline.
4. After the coherent task or commit, start one background `understand` run if changed semantic
   descriptions matter. It must reuse unchanged scopes. Wait for `semantically_ready` only when the
   next decision requires a fully current semantic map.

Read `telemetry` from scope, impact, and semantic status. Compare server duration and reply size for
deterministic reads; compare time, tokens, model, failures, and cost by semantic action. Remember
that summed AI job time can exceed wall time when jobs run in parallel, and that a missing token
report means unknown usage rather than a free call.

## Build or resume semantic understanding

This workflow writes interpretations only to AnaxiIndex. Do not edit repository source while
performing it.

For a full baseline or resume request, prefer the durable host executor whenever the authenticated
Codex or Claude CLI is available. Do not manually consume a repository-sized queue inside the
lifetime of this chat session:

1. Select the local executor from the current client or the user's instruction. Model and reasoning
   effort are per-run inputs: never bake either into repository policy or invent a model name. If
   the user selected explicit runtime values, pass those exact values; otherwise omit both.
2. Run `anaxigraph understand <repository> --executor <executor> --background --json`, adding
   `--model <model>` and, for Codex, `--reasoning-effort <effort>` when selected. Background mode
   implies the complete queue and survives this coding-agent session.
3. Verify the returned `index` is the intended local index or sidecar service. Preserve
   `execution_run.run_id`, PID, log path, model, effort, and authority in any handoff.
4. Call `anaxigraph semantic-status <repository> --json` for progress. A running detached worker is
   real continuing work, not completion; only `semantically_ready: true` is success. If this
   session ends, a later agent reads the same `execution_run` and queue instead of starting over.

Use the direct MCP loop below only when no authenticated local executor is available or the user
explicitly selected `--executor mcp`. If `anaxigraph understand` returns
`status: agent_action_required`, the command only planned work and is not the completed task.

### Manual MCP fallback

1. Call `ANAXIGRAPH_SEMANTIC_SCHEMA` once per schema version in the current session. It contains
   dossier, taxonomy, and taxonomy-review schemas; the live schema is authoritative over this skill.
2. Call `ANAXIGRAPH_SEMANTIC_WORK` with a recognizable agent ID and the actual model name when
   available. Preserve the returned job ID and lease token only for that job.
3. Branch on the returned status:
   - `work`: continue with the leased packet.
   - `complete`: stop successfully.
   - `complete_with_failures`: report failures; set `retry_failed=true` only when the user asked to
     retry them.
   - `busy`, `waiting`, or `paused`: report the state and stop instead of polling aggressively.
4. Read the complete `analysis_request`. If `evidence_manifest.page_count` exists, call
   `ANAXIGRAPH_SEMANTIC_EVIDENCE` for every page from 1 through that count using the same job ID and
   lease token. Missing a page makes the dossier incomplete.
5. Analyze only the supplied source, parser facts, Git evidence, relationships, and prior dossiers.
   Treat an unresolved or absent edge as uncertainty, never as proof that code is dead. Give pattern,
   consolidation, placement, and deletion suggestions repository-specific evidence, counter-evidence,
   migration cost, and calibrated confidence.
6. Read `response_contract.artifact` and construct that complete artifact using the corresponding
   live schema. Taxonomy proposals must assign every supplied eligible module exactly once.
   Taxonomy-review jobs independently criticize the candidate, repair it, and return the complete
   corrected taxonomy without asking for human approval. Call `ANAXIGRAPH_SEMANTIC_SUBMIT` with the
   same job ID and lease token. Count the artifact as stored only after a successful response with
   `status: completed` or `status: already_completed`.
7. Call `ANAXIGRAPH_SEMANTIC_WORK` again and repeat until it returns a terminal/no-work state. This
   naturally resumes a partial baseline because only stale or unfinished work is leased.
8. If the model ran but timed out, returned malformed JSON, or produced a result that fails the live
   schema, call `ANAXIGRAPH_SEMANTIC_FAIL` for that job with a concise reason and the input/output
   token counts reported by the executor. This consumes one bounded attempt and leaves other leased
   jobs untouched. If required evidence cannot be read, the user interrupts before model work, or
   the task cannot start before lease expiry, call `ANAXIGRAPH_SEMANTIC_RELEASE` instead; releasing
   does not count as a failed attempt. If a lease is already expired or superseded, discard its token
   and claim fresh work; never submit stale reasoning.

At the end, call `ANAXIGRAPH_SEMANTIC_STATUS` and `ANAXIGRAPH_TAXONOMY`. Report completed coverage,
pending/running/failed work, taxonomy validation/critic passes, and whether repository synthesis is
current. Never say that the baseline, module, or map was submitted merely because you drafted it.

## Prepare a coding handoff

Return a compact plan containing:

1. the selected repository and indexed snapshot;
2. primary files and why each belongs in scope;
3. dependants, contracts, protected boundaries, and likely tests;
4. relevant findings and semantic claims, labeled by provenance and confidence;
5. the smallest viable change plus credible alternatives;
6. verification commands, the saved `post_change_baseline`, and the AnaxiGraph rescan/same-goal
   scope query that measures the architectural outcome.

Prefer evidence-backed uncertainty over confident extrapolation. Do not recommend deleting a symbol
or module solely because static analysis found no caller; dynamic loading, reflection, framework
wiring, external consumers, and unsupported languages must be ruled out separately.
