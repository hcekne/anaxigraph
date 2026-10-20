# Direct the agent, keep the architecture coherent

Give your coding agent the outcome, examples, boundaries and design preferences. Ask it to use
AnaxiGraph to locate existing ownership, inspect the source and propose a small change. Review
the result and refine your directions. The dashboard's **Guide** form can copy these directions
with the exact checkout and pre-edit snapshot into an agent prompt.

For example:

> Add saved prompts to the Workbench. Reuse the existing storage service and preserve prompt
> execution. I want one save action and no additional settings screen. Use AnaxiGraph to find
> the owner, callers and relevant tests. Explain the proposed boundary before implementing.
> Run behavior checks, refresh the map and reassess against the pre-edit snapshot. Show me
> the result so I can refine the interaction.

Ideas and taste may constrain what agents achieve, but that is a product hypothesis. Neither
10×/100× gains nor fewer bugs follow from having an architecture map. Measure delivery outcomes
and inspect code before claiming those benefits.

## The development loop

1. Ask `ANAXIGRAPH_GUIDE` with `intent=build` or `improve`, your goal and an optional `focus`.
   Its starting point should be implementation code unless you explicitly ask for documentation
   or tests. Keep the returned `snapshot_id` as your comparison baseline.
2. Read the suggested source. Use `ANAXIGRAPH_FILE` for detailed evidence and
   `ANAXIGRAPH_IMPACT` for dependencies, dependants and relevant tests. Static links can miss
   runtime wiring; verify important ownership claims in source.
3. Implement the smallest change that respects the goal, boundaries and existing extension
   points. Run the repository's relevant behavior checks.
4. Call `ANAXIGRAPH_SCAN` with `refresh_semantics=true`. Complete any affected AI work.
5. Call `ANAXIGRAPH_GUIDE` with `intent=reassess` and `from_snapshot_id` set to the baseline.
   Keep that ID for subsequent phases. A later phase should compare with the same baseline
   until you deliberately choose a new one.

The CLI exposes the same code evidence:

```bash
anaxigraph guide . --goal 'Change Calculator behavior; preserve the existing domain boundary' --json
anaxigraph impact . --target pkg/core.py --json
anaxigraph reassess . --from-snapshot 12 --json
```

Use the actual pre-edit ID in place of `12`. Guidance includes that ID in its suggested
post-change MCP call. In **Changes**, select **Compare from** to pin a saved map. The dashboard
shows both snapshot IDs, commits, branch, checkout path and scan times; uncommitted phases also
have content fingerprints, so equal Git commits do not make two phases indistinguishable.

## A concrete coherence check

The executable example in `tests/test_usage_feedback.py` uses a small Calculator repository:

| Evidence or action | What the example establishes |
| --- | --- |
| Code facts | `pkg/core.py` owns `Calculator`; `pkg/consumer.py` uses it and `tests/test_core.py` exercises it. |
| Selection | Repeated Calculator wording in a documentation file does not turn that file into the implementation starting point. |
| Proposed action | Extend the existing owner and preserve the arithmetic boundary; inspect the implementation before accepting that recommendation. |
| Two edit phases | Both change the existing calculation behavior and receive separate saved snapshots, including uncommitted content. |
| Reassessment | Pinning the first snapshot compares the final phase with that exact baseline. A historical target reads its own AI status. |
| Supporting artifacts | Adding benchmark timing JSON is a measurement change and does not, by itself, justify caller inspection or an architectural regression. |

This demonstrates ownership, dependency and baseline continuity. It does not demonstrate that
the selected arithmetic policy is desirable. That needs your examples, judgment and tests.

The worktree repair follows the same boundary: Git supplies linked-checkout identity, the
repository registry admits that checkout, and the existing scanner saves its facts. It reuses
the existing scan route and index model. It does not introduce another scanning subsystem.

## Read freshness and counts precisely

- **Structural scan** compares the saved map with the checkout's current commit and working
  files. Checkout path, branch, indexed commit and current commit appear in the header.
- **AI mapping**, **Patterns** and **Fresh Eyes** each report their own state for the named
  snapshot. A current structural scan does not mean those analyses have run. Reused documents
  can remain valid for a newer snapshot; their source identity stays available in details.
- File totals include reference artifacts. AI coverage excludes ineligible files. Pattern
  coverage counts candidate–target pairs, including poor fits, rather than unique files or
  only recommended patterns. Findings totals include diagnostics; the attention queue applies
  its displayed severity and priority filters.
- File pages load in the background, with loaded/total shown while incomplete. Search results
  identify the 250-match cap. Reassessment reports total, returned and omitted effects.

## Keep interactions short

Guidance and impact use an 8 KB default response budget, respecting a smaller configured
budget. Request `details=true` in MCP/REST or `--details` in the CLI to expand their evidence.
MCP guidance also summarizes repository understanding, Fresh Eyes and reassessment by default;
request `details=true` for complete review documents. Text content gives a short conclusion
beside structured data, without another copy of the full JSON.

Workflow polling reads current progress without loading the retained Fresh Eyes proposals,
generation history or input manifests. `/api/workflows?details=true` exposes those details.
The dashboard requests compact file pages and loads full descriptions when a file is opened.
History and reassessment load independently of current views.

Mapping step 5 runs independent batches concurrently inside each configured review pass.
OpenAI and Claude passes stay ordered. Each batch is saved immediately; resume reuses successful
batches and retries failures. The UI shows completed/total batches, active workers, elapsed time
and a final reconciliation phase. **Try 2 jobs** provides a bounded sample before a large run.
Configure worker counts within the repository's shared capacity; adding workers cannot remove
an ordered pass's dependency on its predecessor.

Local latency measurements are reproducible with `python -m benchmarks.usage_latency`.
The retained [usage benchmark](../benchmarks/results/usage-feedback-2026-10-20.json) records a
synthetic 1,000-file repository and excludes model calls. Cold scans, unchanged scans, HTTP reads
and payloads are measured separately. Live provider latency, real-code recommendation quality
and delivery speed remain separate evaluation questions.
