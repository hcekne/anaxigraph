# Change-loop review: an external redesign proposal checked against the source

**Status:** PROPOSED as Phase 14 on 24 October 2026. Not active until the owner admits it. See the
Phase 14 section of [`feature-development-plan.md`](feature-development-plan.md).

**Source:** an external clean-sheet proposal, *"AnaxiGraph redesign ideas"*, which the owner left in
their floThink Agent Inbox on 24 October 2026. It states that its author never looked at AnaxiGraph.
Every "exists", "partial", or "missing" claim below was checked against the working tree at `dc43885`.

## Verdict

The proposal's thesis is already AnaxiGraph's mission: build around making and checking a change,
with the graph as evidence. Most of its architecture already exists, and should not be rebuilt:

- one service on SQLite and FTS5;
- separate extracted, ambiguous, unresolved, and inferred provenance;
- declared, path, inferred, and current responsibility layers;
- working-tree snapshots with fingerprints;
- two-stage dossier invalidation that includes dependency interfaces;
- lease-guarded publication;
- a bounded `GUIDE` brief;
- before/after reassessment, and introduced/resolved findings;
- Charter corrections as a declared overlay;
- a 128-card pattern catalogue with counter-evidence.

The proposal is useful as an independent checklist, and its strongest point is one the roadmap has
never answered. **AnaxiGraph has no measurement of whether it changes an agent's code.** Every gate
so far proves that an answer is correct, bounded, or fast. None of them proves that an agent using
the answer writes a better patch, or that the next change on top of that patch is easier. This is
why the evaluation item (14.1) comes first, and why its result decides whether the later items are
worth their lines.

The other points it raises that the source confirms are honesty gaps in the change loop:

- a rule can look passed when it never ran;
- an existing violation that grows is invisible;
- an applicable rule can be dropped from the brief by ranking;
- nothing checks a plan before editing;
- "verified" never includes the project's own tests.

## Findings, checked against the source

| Proposal idea | State | Evidence | Disposition |
|---|---|---|---|
| Evaluate configurations A–D, chained follow-up tasks, and whether agents consulted the context | **Missing** | `benchmarks/architecture_tasks.py` grades answers against a reference and compares no AnaxiGraph arms. `benchmarks/README.md:45-63` lists arm comparison only as future work. No chained task exists. | **Adopt, first** (14.1) |
| Every rule result is passed-in-scope, violated, or unresolved; missing analysis is never a pass | **Partial** | `architecture_rules.py:275-276`: `forbid_dependency` silently skips edges whose endpoints it cannot find. Rules emit findings only, with no pass or unresolved state. | **Adopt** (14.2) |
| ArchUnit-style freeze: existing debt stays visible, and only new deterioration fails | **Partial** | `reassessment_evidence.py:388-400` diffs findings into introduced and resolved. "Worsened" exists only for file metrics (`reassessment_advice.py:136-139`), so a boundary violated 3 → 9 times reads as unchanged. | **Adopt**, reusing the reassessment lineage baseline and no baseline file (14.3) |
| Directly applicable obligations must survive ranking | **Partial** | `agent_scope_evidence.py:18-41`: rules count only when they match ranked files, so a rule that applies to the placement target can disappear. | **Adopt** (14.4) |
| `assess_plan` before a substantial edit | **Missing** | No surface accepts plan text. The intents are fixed at `architecture_guidance.py:22-26`. Fresh-eyes grounding already checks "already exists" (`semantic_fresh_eyes_grounding.py:244-258`). | **Adopt inside `GUIDE`**, not as a new tool (14.5) |
| Validation includes compiler, linter, and tests; graph-selected tests never silently replace required ones | **Partial** | `semantic_fresh_eyes_contract.py:310-321` attributes a result only when one is supplied. Reassessment is static only. AnaxiGraph must never run target code (cross-phase gate). | **Adopt as supplied, attributed evidence** (14.6) |
| Behavioural contracts (idempotency, tenancy, atomicity, events, retry), with declared and inferred kept apart | **Partial** | `semantic_contract.py:68-70` stores free-text strings. Nothing separates a contract cited from a schema, test, or document from one the model inferred. | **Adopt the basis, not a typed taxonomy** (14.7) |
| Dead code by reachability from configured entry points | **Partial, and the plan overstates it** | `architecture_dead_code.py:105-116` uses zero fan-in plus suppression gates. Console scripts, `[project.entry-points]`, `__all__`, and `package.json` `bin`/`exports` are not read. `feature-development-plan.md:1977` claims reachability. | **Adopt packaging roots** (14.8) |
| Mark preferred examples versus legacy code being replaced; frequency is a poor basis for precedent | **Missing** | Corrections target Charter sections only (`architecture_charter_corrections.py:12-27`). `local_precedents` (`agent_decision.py:206-222`) cannot tell a preferred example from legacy code. | **Adopt as a correction disposition** (14.9) |
| The agent workflow: prepare at start, reassess on scope change, validate before reporting done, and skip trivial edits | **Partial** | `plugins/anaxigraph/skills/anaxigraph/SKILL.md` asks for `GUIDE` before editing. It never requires reassessment before completion and never says when to skip. | **Adopt** (14.10) |
| An older job must never overwrite a newer result | **Partial** | Agent jobs are validated against the current snapshot (`semantic_leases.py:155-178`). Running non-pattern jobs are not superseded, and non-agent publication has no input-hash check (`semantic_records.py:244-262`). | **Fix** (14.11) |
| A snapshot identifies working-tree contents | **Exists, with one defect** | `git.py:108-159` fingerprints the diff and untracked files. However, `dirty` uses `status --porcelain -uno` (`git.py:83`), so a checkout with only untracked changes is reported clean. | **Fix** (14.11) |

### Not adopted

| Proposal idea | Why not now | Evidence that would reopen it |
|---|---|---|
| Rebuild as a modular monolith with SQLite | It already is one (§10.3, ADR 0003) | — |
| A shared immutable base index with per-worktree overlays | Each checkout gets its own index (`local_runtime.py:41-62`), which is correct but re-indexes. An overlay adds persistent state and a second read path. | 14.1 or dogfooding shows re-indexing parallel worktrees is a measured cost an agent waits on |
| Typed contract fields (`idempotent: bool`, …) | It forces a dossier schema migration and re-mapping for every repository, and strict structured output requires every property (see `AGENTS.md`). Basis plus a prompt checklist gets most of the value. | 14.1 shows agents break a specific obligation kind that free text failed to carry |
| Embedding or vector retrieval beside exact, lexical, and graph search | Complexity exclusion: no second search substrate | Placement fixtures fail on synonym-only goals that FTS5 cannot reach |
| Validating a hypothetical diff without scanning it | A working-tree scan already produces the "after" snapshot | — |
| Deterministic clone detection | Consolidation is model-assessed today. Whether duplicates are missed is exactly what 14.1 measures. | 14.1 patches duplicate an existing capability that `GUIDE` did not name |
| Renaming the MCP surface to `prepare_change`, `inspect`, `assess_plan`, and `validate_change` | The same operations exist as `GUIDE`, `FILE`/`IMPACT`, and `GUIDE intent=reassess`. Renaming is churn for users. | — |
| "Simplest alternative" as a new field on all 128 pattern cards | A large data edit with an unknown effect. A runtime simplest-design sentence exists (`pattern_language.py:219`). | 14.1 records over-abstracted patches that cite a catalogue pattern |
| Proposals as a first-class entity | Fresh-eyes stages already hold proposals apart from as-built facts | — |
| Edge-level rejection of an inferred relationship | Inferred relationships are dossier claims, which Charter refutation already covers. Parser edges are facts. | A correction is needed that no Charter section can express |

## Phase 14 items

Each item names the promise it serves, the smallest change, and a gate that one change can fail.

### 14.1 Measure whether AnaxiGraph changes the patch (Guide, Keep coherent)

Extend the existing `benchmarks/architecture_tasks.py` harness. Do not add a second harness.

- **Three arms on the same pinned revisions, model, effort, and budget.** Arm A is source, search,
  and tests only. Arm B adds the structural tools (`OVERVIEW`, `SEARCH`, `FILE`, `IMPACT`). Arm C
  adds `GUIDE` and reassessment with the semantic map. The proposal's B and C collapse into one arm,
  because semantic annotations and change briefs reach agents only through `GUIDE`.
- **Chained tasks.** A fresh agent implements feature A. A second fresh agent then implements
  feature B, which must build on A, in the result. Score B's success, not only A's.
- **Measures:**
  - functional success and regressions;
  - introduced and worsened findings (from 14.3);
  - duplicated capability and unnecessary abstractions against a written rubric, graded blind;
  - public-surface growth;
  - follow-up task success;
  - wall time and tokens, including indexing, mapping, and refresh cost.
- **Consultation record.** The harness records which tools each agent called, and whether its first
  edited file matched `GUIDE` placement. It reads this from the agent transcript. It is harness-side
  only and adds no product telemetry.
- **Gate:** a recorded run of at least six task chains × three arms × two repeats on AnaxiGraph
  itself and on one external fixture repository, with per-arm results and the raw transcripts
  retained. The report states the measured difference, including "no measurable difference" if
  that is the result. A synthetic rehearsal does not satisfy this gate.

### 14.2 A rule that did not run is not a pass (Keep coherent)

- Every evaluated rule reports one of three states for its scope: `passed`, `violated`, or
  `unresolved`. `unresolved` carries a count and the reason, such as unresolved or ambiguous
  endpoints, unknown paths, or missing analyzer capability.
- `forbid_dependency` counts the edges it cannot place instead of skipping them.
- The rule state reaches `GUIDE`, reassessment, CLI, and dashboard through the existing rule
  identity payload.
- **Gate:** a fixture where a forbidden scope contains an unresolved edge reports `unresolved`. It
  fails on today's code, which reports nothing.

### 14.3 Report a violation that grows (Keep coherent)

- Reassessment classifies each rule's violation set against the lineage baseline as `introduced`,
  `worsened`, `unchanged`, `improved`, or `resolved`. For example, a forbidden-dependency rule
  violated 3 → 9 times reports `worsened` with the six new edges.
- The earlier compatible snapshot is the baseline, so there is no baseline file and no new table.
- **Gate:** a fixture that adds edges to an already violated boundary reports `worsened` and names
  the new edges. An unchanged violation stays `unchanged` and does not enter the attention queue.

### 14.4 Applicable obligations survive the payload budget (Guide)

- Rules scoped to the placement target, the `IMPACT` targets, or their groups are pinned in the
  `GUIDE` payload ahead of ranked material.
- If even the compacted pinned set exceeds the budget, the reply reports the overflow count.
  It never drops one silently.
- **Gate:** a fixture whose governing rule matches only a low-ranked file still returns that rule
  at the 4,000-byte floor.

### 14.5 Check a plan before editing, inside `GUIDE` (Guide)

- `GUIDE` with intent `build` or `improve` accepts optional `plan` text naming the files to edit,
  any new files, and any new symbols.
- The reply adds a `plan_check` section, built from existing grounding:
  - new symbols that already exist (reusing the fresh-eyes "already exists" check);
  - a proposed new file where placement found an existing home;
  - proposed edits that cross a pinned rule from 14.4;
  - planned files outside the bounded impact set.
- No new MCP tool, job kind, or approval gate is added, and the check makes no model call.
- **Gate:** a fixture plan that duplicates an existing capability and creates a sibling file gets
  both findings. A plan that matches placement gets none.

### 14.6 Count the project's own checks, never run them (Keep coherent)

- Reassessment accepts supplied check results, each a command, an exit status, and a revision or
  working-tree fingerprint. Each result is attributed only when the fingerprint matches the target
  snapshot.
- When none are supplied, the behaviour section reports `unchecked`, never `passed`.
- AnaxiGraph still never executes target code.
- **Gate:** a result supplied for a different fingerprint is reported as stale and not attributed.

### 14.7 Say where a contract came from (Understand)

- Each `public_contracts`, `invariants`, and `side_effects` entry gains `basis` (`declared` or
  `inferred`) and an evidence reference. `declared` means the claim cites a schema, test, or
  document path that exists in the snapshot.
- The prompt gains a short checklist: idempotency, tenant or authorization requirement, atomicity,
  emitted events, and retryable versus permanent failure.
- Ship this with the next dossier schema bump, so that a re-map happens once. The wire schema must
  keep every property required and nullable; `_codex_schema` must report zero strict violations.
- **Gate:** a `declared` claim whose cited path does not exist is downgraded to `inferred` by
  deterministic validation.

### 14.8 Dead-code roots from packaging, or correct the claim (Keep coherent)

- Read `[project.scripts]`, `[project.entry-points]`, `__all__`, and `package.json`
  `main`/`bin`/`exports` as roots.
- Suppress candidates reachable from those roots through resolved edges.
- Each candidate reports the root set that was used.
- If this cannot ship within the line budget, correct `feature-development-plan.md:1977` instead.
- **Gate:** a file reached only through a console-script entry is not a candidate. A genuinely
  unreachable file in the same fixture still is.

### 14.9 Preferred example and legacy, as corrections (Guide)

- Add a `preferred_example` / `legacy` disposition to the existing Charter correction document,
  targeting a file or symbol.
- `local_precedents` ranks preferred examples first and never offers a legacy target as a
  precedent.
- **Gate:** with two similar precedents, marking one `legacy` removes it from `GUIDE`, and the
  correction survives a rescan.

### 14.10 Make the skill state the loop (Guide)

The skill keeps its current length or shrinks. It says three things:

- call `GUIDE` before a change that adds a file, a symbol others call, or a dependency;
- scan and reassess before reporting completion;
- skip both for edits confined to one function body that add no dependency.

**Gate:** the existing plugin contract test asserts all three statements.

### 14.11 Two freshness defects

- `dirty` counts untracked files (`git.py:83`).
- Non-agent semantic publication checks that the job's input fingerprint is still current, and
  supersedes the job otherwise.
- **Gate:** one regression test each. Both fail on `dc43885`.

## Phase 14 exit gate

- 14.1's recorded run exists and is reported as measured.
- Items 14.2–14.11 pass their gates, or are explicitly dropped with the 14.1 result as the reason.
- No new MCP tool, job kind, table family, provider path, dashboard journey, or search substrate is
  added.
- Net production growth is at most 600 lines, and the production ratchet is re-recorded at the
  measured value. Lines added by 14.2–14.9 are offset where an existing path is replaced.
