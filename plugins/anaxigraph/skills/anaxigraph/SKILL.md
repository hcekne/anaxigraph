---
name: anaxigraph
description: Use AnaxiGraph as shared architecture intelligence for people and coding agents. Ground software changes in its repository map, dependency evidence, findings, and semantic dossiers when explaining a system, bootstrapping semantic understanding, planning a feature or refactor, checking impact or dead-code evidence, deciding where new code belongs, or verifying a completed change.
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
4. Call `ANAXIGRAPH_OVERVIEW` and `ANAXIGRAPH_SEMANTIC_STATUS` before choosing a workflow. Use the
   Overview Charter and current responsibility map as the default system explanation. State
   analyzer/resolution caveats when they materially affect the answer.

With no narrower request, summarize the repository's areas, dominant languages, active attention,
relationship completeness, history state, and semantic coverage. Keep deterministic facts and
model-derived interpretations visibly separate.

## Route the request

- For “map,” “understand,” “bootstrap,” or “resume semantics,” run the semantic baseline workflow.
- For a new feature or refactor, call `ANAXIGRAPH_SEARCH`, then `ANAXIGRAPH_GUIDE` with the matching
  `build` or `refactor` intent; call
  `ANAXIGRAPH_FILE` for the primary modules and `ANAXIGRAPH_IMPACT` before changing a shared target.
- For an explicit “fresh eyes,” “clean-sheet architecture,” or independent architecture challenge,
  run the fresh-eyes review workflow. Do not spend those tokens for an ordinary scoped change.
- For a module question, use `ANAXIGRAPH_SEARCH` and `ANAXIGRAPH_FILE`. Compare responsibilities,
  collaborators, overlaps, extension points, pattern evidence, and counter-evidence.
- For architecture attention, call `ANAXIGRAPH_FINDINGS` with the bounded `attention` view. Use
  `ANAXIGRAPH_FINDING_CONTEXT` only for the chosen finding. A `planned` finding records that it was
  selected for work; other active findings are observations, not an implementation request. Read
  its `finding_history` to distinguish a new, persistent, resolved, or returned condition, while
  preserving the stated limit that retained maps may sample rather than cover every commit.
- For history questions, use the Overview history summary and the dashboard Changes journey. Start
  or cancel an import only when the user requests that index operation.
- After an implementation, call `ANAXIGRAPH_SCAN` when available. Repeat guidance or impact when
  responsibilities or dependencies may have moved, and use History and findings for change
  evidence. “No longer reported” is not proof that a finding was fixed, and a changed metric is not
  proof that the architecture improved.

## Work continuously during development

Keep one persistent AnaxiGraph service and structural watcher for the coding session. Build a full
semantic baseline only when no current baseline exists. For each coherent task:

1. Call `ANAXIGRAPH_GUIDE` once before editing and `ANAXIGRAPH_IMPACT` for shared targets.
2. During edits, let the watcher update deterministic source facts and run focused tests normally.
   Do not start model-backed semantic work after every save.
3. At the verification checkpoint, call `ANAXIGRAPH_SCAN`, then repeat only the queries needed to
   confirm changed responsibilities, dependencies, findings, or history.
4. After the coherent task or commit, start one background `understand` run if changed semantic
   descriptions matter. It must reuse unchanged scopes. Wait for `semantically_ready` only when the
   next decision requires a fully current semantic map.

Read `telemetry` from guidance, impact, and semantic status. Compare server duration and reply size for
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
   `--model <model>` and `--reasoning-effort <effort>` when selected; both Codex and Claude accept
   the effort value as given. Background mode implies the complete queue and survives this
   coding-agent session.
3. Verify the returned `index` is the intended local index or sidecar service. Preserve
   `execution_run.run_id`, PID, log path, model, effort, and authority in any handoff.
4. Call `anaxigraph semantic-status <repository> --json` for progress. A running detached worker is
   real continuing work, not completion; only `semantically_ready: true` is success. If this
   session ends, a later agent reads the same `execution_run` and queue instead of starting over.

If no authenticated local executor is available, report that semantic completion needs Codex,
Claude, or another configured executor; do not manually administer a repository-sized lease queue
through the normal MCP tool menu. At the end, call `ANAXIGRAPH_SEMANTIC_STATUS`. Report completed
coverage, pending/running/failed work, responsibility-map readiness, and whether the Living Charter
is current. Never say that the baseline is complete until `semantically_ready: true`.

## Run the fixed fresh-eyes review

This workflow is optional, explicit, and read-only. It challenges legacy anchoring without turning
AnaxiGraph into a general multi-agent workflow engine.

1. Call `ANAXIGRAPH_GUIDE` with `fresh_eyes=true`. If the returned state is `not_started` or `stale`
   and the user requested the review, call it again with `start=true` and `proposal_count=2` unless
   the user chose one or three proposals. If the state is `failed`, keep the existing proposal
   count and call with `start=true, retry_failed=true`. If the state is `current` and the user
   deliberately wants a new architectural judgment, for example from a different model, call
   with `start=true, restart=true`. This is the same operation as
   `anaxigraph fresh-eyes <repository> --restart`: it reruns every stage as a new review
   generation and keeps the earlier documents for audit. Follow `agent_journey.next_action` in
   each reply.
2. Start or resume the durable host executor with
   `anaxigraph understand <repository> --executor <executor> --background --json`, adding
   `--model <model>` and, for Codex, `--reasoning-effort <effort>` when the user selected them
   for a rerun. It completes any missing semantic baseline, then consumes the fixed review jobs
   using the host agent's tokens.
3. Poll `ANAXIGRAPH_GUIDE(fresh_eyes=true)` or `anaxigraph fresh-eyes <repository> --json`. A review
   is complete only when `ready` is true and `state` is `current`; partial proposal or comparison
   stages are evidence, not recommendations.
4. Report provider/model/executor diversity honestly. Different sessions of one provider are not
   cross-provider agreement, and AnaxiGraph can prove only the packet it supplied—not that an
   external model had no unrelated prior context.
5. Present the final ranked recommendations, current strengths, counter-evidence, rejected ideas,
   migration risks, and verification. Use normal Guide/Impact before implementing any selected
   slice. Never edit source merely because the reference design differs from the current system.

## Prepare a coding handoff

Return a compact plan containing:

1. the selected repository and indexed snapshot;
2. primary files and why each belongs in scope;
3. dependants, contracts, protected boundaries, and likely tests;
4. relevant findings and semantic claims, labeled by provenance and confidence;
5. the smallest viable change plus credible alternatives;
6. focused verification commands and the AnaxiGraph refresh/query needed to inspect the result.

Prefer evidence-backed uncertainty over confident extrapolation. Do not recommend deleting a symbol
or module solely because static analysis found no caller; dynamic loading, reflection, framework
wiring, external consumers, and unsupported languages must be ruled out separately.
