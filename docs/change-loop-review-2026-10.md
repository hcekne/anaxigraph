# Change-loop review: an external redesign proposal checked against the source

**Status:** PROPOSED input to the [semantic graph redesign](design/semantic-graph-redesign-2026-10-23.md)
and the [0.9.2 request](design/0.9.2-performance-and-architecture-request.md). It does not open a
separate phase. The roadmap entry is the 24 October section of
[`feature-development-plan.md`](feature-development-plan.md).

**Source:** an external clean-sheet proposal, *"AnaxiGraph redesign ideas"*, which the owner left in
their floThink Agent Inbox on 24 October 2026. It states that its author never looked at AnaxiGraph.
Every state below was checked against `HEAD` at `e7bb76a`, which is 0.9.1 plus the 0.9.2 request.

## Verdict

The proposal's thesis is already AnaxiGraph's direction: build around making and checking a change,
with the graph as evidence. Most of its architecture already exists and should not be rebuilt:

- one service on SQLite and FTS5;
- separate extracted, ambiguous, unresolved, and inferred provenance;
- declared, path, inferred, and current responsibility layers;
- working-tree snapshots with fingerprints;
- per-checkout worktree selection;
- two-stage dossier invalidation that includes dependency interfaces;
- lease-guarded publication;
- a bounded `GUIDE` brief;
- architecture planning with milestones;
- before/after reassessment;
- Charter corrections as a declared overlay;
- the pattern catalogue.

Its dead-code ideas are already covered, more concretely, by the
[0.9.2 dead-code research](research/2026-10-24-dead-code-detection.md).

Its strongest point is one the roadmap admits but does not plan for. The 20 October queue records
that "fewer bugs, faster delivery and a 10×/100× productivity gain have not been demonstrated".
**AnaxiGraph has no measurement of whether an agent using it writes a better patch, or whether the
next change on top of that patch is easier.** Every existing gate proves that an answer is correct,
bounded, or fast. The 0.9.2 request asks for a much smaller implementation and exhaustive pattern
coverage. Without this measurement, nothing tells the redesign which guidance surfaces earn their
lines.

The other confirmed points are honesty gaps in the change loop:

- a rule can look passed when it never ran;
- a growing size or complexity violation is invisible;
- a governing rule can be dropped because its file ranked low;
- nothing critiques an agent's edit plan;
- "verified" never includes the project's own checks.

## Findings at `e7bb76a`

| # | Proposal idea | State | Evidence | Disposition |
|---:|---|---|---|---|
| 1 | Compare agent outcomes with and without AnaxiGraph; chained follow-up tasks; record whether the context was consulted | **Missing** | `benchmarks/architecture_tasks.py` grades answers against a reference with no arms. `semantic_maintenance.py:351-368` compares tool versions with no agent. Nothing chains tasks. | **Adopt, first** |
| 2 | A rule result is passed, violated, or unresolved; missing analysis is never a pass | **Missing** | `architecture_rules.py:276` skips edges whose endpoints are unknown. `_evaluate_rule` returns findings only, and `[]` for an unknown rule type (`:64`). | **Adopt** |
| 3 | Existing debt stays visible; only new deterioration is reported (ArchUnit freeze) | **Partial** | Each forbidden edge is its own finding, so new edges already appear as introduced. A size or complexity finding present in both snapshots is skipped (`reassessment_evidence.py:409`), so a 600 → 900-line file reads as unchanged. | **Adopt `worsened`**, using the lineage baseline with no baseline file |
| 4 | Directly applicable obligations survive ranking | **Missing** | Rules are kept only if they match ranked primary or related files (`agent.py:145,171`; `agent_scope_evidence.py:35-40`). The plan's `architecture_target` does not feed rule selection. | **Adopt** |
| 5 | Assess an edit plan before a substantial change | **Missing** | `GUIDE intent=plan` generates architecture options and milestones (`planning_mcp.py`, `architecture_plan_contract.py`). No surface critiques an agent's proposed files and symbols. | **Adopt inside `GUIDE` build/improve**, with no new tool and no model call |
| 6 | Validation counts compiler, linter, and test results | **Missing** | Reassessment takes no check input (`architecture_reassessment.py:22-30`). Milestone `verification_evidence` is free text that nothing reads (`architecture_plan_read.py:95-152`). | **Adopt as supplied, fingerprint-attributed evidence.** Never run target code. |
| 7 | Contract obligations are kept as declared versus inferred | **Missing** | The new annotation contracts carry `side_effects`, `invariants`, and `evidence` (`knowledge_annotation_contract.py:26-59`), with no basis field. | **Adopt in the new graph contract schema** |
| 8 | Mark preferred examples versus legacy code being replaced | **Missing** | Corrections are `correct` or `refute` only (`architecture_charter_corrections.py:12-27`). `local_precedents` is unlabelled (`agent_decision.py:199-223`). | **Adopt as a correction disposition** |
| 9 | Agents prepare at start, reassess before reporting done, and skip trivial edits | **Partial** | `SKILL.md:46-48,132`: reassessment appears only in the planning section, and there is no skip rule. | **Adopt** (text only) |
| 10 | An older job never overwrites a newer result | **Mostly fixed** | Cross-snapshot superseding covers every kind (`semantic_lease_claim.py:96-116`). Within one snapshot, running non-pattern jobs are not superseded (`semantic_records.py:172-178`), and the non-agent runner does not re-check freshness before commit (`semantic_runner.py:256-270`). | **Fix the remainder** |
| 11 | A snapshot identifies working-tree contents | **One defect** | `git.py:146-150`: `dirty` uses `-uno`, so a checkout whose only changes are untracked files is reported clean. The fingerprint itself is correct. | **Fix** |
| 12 | Dead code by reachability from real entrypoints | **Covered by 0.9.2** | [0.9.2 request § Detect unused code without age gates](design/0.9.2-performance-and-architecture-request.md) | No separate item |

### Not adopted

| Proposal idea | Why not | Evidence that would reopen it |
|---|---|---|
| Rebuild as a modular monolith | It already is one | — |
| A shared base index with per-worktree overlays | Worktrees are recognized per checkout, and the portable record already lets a checkout reuse matching analysis without model calls | Measured agent wait time on re-indexing parallel worktrees |
| Typed contract fields such as `idempotent: bool` | Strict structured output needs every property, and a typed taxonomy grows the schema. A `basis` plus a prompt checklist carries most of the value. | Item 1 shows agents breaking one obligation kind that free text did not carry |
| Embedding or vector retrieval | Complexity exclusion: no second search substrate | Placement fails on synonym-only goals that FTS5 cannot reach |
| Validating a hypothetical diff without scanning it | A working-tree scan already produces the "after" snapshot | — |
| Renaming tools to `prepare_change`, `inspect`, `assess_plan`, and `validate_change` | The same operations exist as `GUIDE`, `FILE`/`ENTITY`/`IMPACT`, and `GUIDE reassess=true` | — |
| Proposals as a first-class entity | Fresh Eyes alternatives and architecture-plan options already hold them apart from observed facts | — |

## Proposed work

These items must fit the 0.9.2 direction of a much smaller implementation. Each item lands on the
code the redesign keeps: the new graph contracts, `GUIDE`, and reassessment. None of it goes into
modules on the retirement ledger. No item adds an MCP tool, job kind, table family, provider path,
dashboard journey, or search substrate.

### A. Measure whether AnaxiGraph changes the patch

Extend `benchmarks/architecture_tasks.py`; do not add a second harness.

- **Arms.** Run three arms on pinned revisions with the same model, effort, and budget:
  - A: source, search, and tests only;
  - B: adds structural tools (`OVERVIEW`, `SEARCH`, `FILE`, `GRAPH`, `ENTITY`, `IMPACT`);
  - C: adds `GUIDE`, planning, and reassessment over the semantic map.
- **Chained tasks.** A fresh agent implements feature A. A second fresh agent then implements a
  feature B that depends on A, in the result. Score B as well as A.
- **Measures:**
  - functional success and regressions;
  - introduced and worsened findings;
  - duplicated capability and unnecessary abstraction, graded blind against a written rubric;
  - public-surface growth;
  - follow-up success;
  - wall time and tokens, including mapping and refresh cost.
- **Consultation record.** The harness reads from the agent transcript which tools were called and
  whether the first edited file matched `GUIDE` placement. This is not product telemetry.
- **Gate:** a recorded run of at least six chains × three arms × two repeats, on AnaxiGraph and on
  one external repository, with transcripts retained. Report the measured difference, including
  "no measurable difference". A synthetic rehearsal does not satisfy this gate.
- **Use in 0.9.2.** The result ranks the retirement ledger. A guidance surface that does not move
  arm C's outcome is a deletion candidate.

### B. A rule that did not run is not a pass

- Each rule reports `passed`, `violated`, or `unresolved` for its scope, with the unresolved count
  and its reason.
- Unknown edge endpoints and unknown rule types count as `unresolved`; they are no longer skipped
  or returned as an empty list.
- **Gate:** a fixture with an unresolved edge inside a forbidden scope reports `unresolved`. It
  fails at `e7bb76a`.

### C. Report a violation that grows

- Reassessment classifies a finding present in both snapshots as `worsened`, `unchanged`, or
  `improved`, using its measured value against the lineage baseline.
- **Gate:** a file already over its size limit that grows reports `worsened`, with both values. An
  unchanged one stays out of the attention queue.

### D. Governing rules survive ranking

- Rules scoped to the placement target, the `IMPACT` targets, the selected plan milestone's owners,
  or their groups are pinned ahead of ranked material.
- If the compacted pinned set exceeds the budget, the reply reports the overflow count.
- **Gate:** a rule matching only a low-ranked placement file is returned at the 4,000-byte floor.

### E. Critique an edit plan inside `GUIDE`

- `GUIDE` build/improve accepts optional `plan` text naming files to edit, new files, and new
  symbols.
- The reply adds `plan_check`, built from existing grounding:
  - symbols that already exist;
  - a new file where placement found a home;
  - edits that cross a pinned rule;
  - files outside the bounded impact set;
  - divergence from the selected architecture target.
- **Gate:** a plan that duplicates a capability and adds a sibling file gets both findings. A plan
  that matches placement gets none.

### F. Count the project's own checks; never run them

- Reassessment accepts supplied check results, each a command, an exit status, and a working-tree
  fingerprint. A result is attributed only when its fingerprint matches the target snapshot.
- When none are supplied, the result reports `unchecked`.
- Marking a milestone `verified` cites such a result rather than free text.
- **Gate:** a result for a different fingerprint is reported stale and not attributed.

### G. Declared or inferred contracts

- Each contract, invariant, and side-effect entry in the new annotation schema carries `basis`
  (`declared` or `inferred`) and an evidence reference.
- The prompt gains a checklist: idempotency, authorization or tenancy, atomicity, emitted events,
  and retryable versus permanent failure.
- Ship this with the canonical contract graph schema so that a re-map happens once. Every wire
  property stays required and nullable; `_codex_schema` reports zero strict violations.
- **Gate:** a `declared` claim citing a path absent from the snapshot is downgraded to `inferred`.

### H. Preferred example and legacy corrections

- Add `preferred_example` and `legacy` dispositions to Charter corrections, targeting a file or
  symbol.
- `local_precedents` ranks preferred examples first and never offers legacy code as a precedent.
- **Gate:** marking one of two similar precedents `legacy` removes it from `GUIDE`, and the
  correction survives a rescan.

### I. The skill states the loop

The skill keeps its current length or shrinks. It says three things:

- call `GUIDE` before a change that adds a file, a shared symbol, or a dependency;
- scan and reassess before reporting completion;
- skip both for edits confined to one function body that add no dependency.

**Gate:** the plugin contract test asserts all three statements.

### J. Two freshness defects

- `dirty` counts untracked files.
- The non-agent runner re-checks the job's input fingerprint before commit, and supersedes the job
  otherwise.
- **Gate:** one regression test each, both failing at `e7bb76a`.

## Suggested placement

| Item | Where it belongs | Why |
|---|---|---|
| J | Now, as 0.9.2 defect repairs | Small, demonstrated, and independent of the redesign |
| A | Before 0.9.2 retirement decisions are final | It is the evidence that ranks the retirement ledger |
| B, C | 0.9.2 "Refocus Changes on pinned-baseline verification" | Both make the baseline comparison honest |
| G | "Implement canonical module/function/interface/contract graph" | One schema bump and one re-map |
| D, E, F, H, I | "Apply graph evidence to … source-aware planning", after A reports | Only if A shows that `GUIDE` changes the patch |
