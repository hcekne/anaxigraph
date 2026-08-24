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
  `ANAXIGRAPH_FINDING_CONTEXT` only for the chosen finding. A `planned` finding records human
  approval; other active findings are observations, not an implementation request.
- For history questions, use `ANAXIGRAPH_HISTORY_STATUS` and the dashboard timeline. Start or cancel
  an import only when the user requests that index operation.
- After an implementation, call `ANAXIGRAPH_SCAN` when available, then repeat the relevant scope,
  impact, finding, or module query. Report measured changes; do not claim a finding resolved before
  the rescan confirms it.

## Build or resume semantic understanding

This workflow writes interpretations only to AnaxiIndex. Do not edit repository source while
performing it.

If the user asks you to run `anaxigraph understand` and its JSON result has
`status: agent_action_required`, the command is not the completed task. Follow its `next_action`
with the MCP workflow below and do not return to the user until the queue reaches a terminal state.
If the command used a local Codex/Claude executor, wait for it and verify `complete: true`; a
`partial` result also requires continuation.

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
8. If required evidence cannot be read, the user interrupts, or the task cannot be completed before
   lease expiry, call `ANAXIGRAPH_SEMANTIC_RELEASE` with a concise reason. If a lease is already
   expired or superseded, discard its token and claim fresh work; never submit stale reasoning.

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
6. verification commands and the AnaxiGraph rescan/query that proves the architectural outcome.

Prefer evidence-backed uncertainty over confident extrapolation. Do not recommend deleting a symbol
or module solely because static analysis found no caller; dynamic loading, reflection, framework
wiring, external consumers, and unsupported languages must be ruled out separately.
