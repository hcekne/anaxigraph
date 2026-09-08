# Architecture intelligence — 0.5.0 feature and release list

Admitted by the repository owner on 8 September 2026 as Phase 13. This strengthens
Understand, Guide, and Keep coherent through existing product surfaces. It does not
reopen the completed consolidation programme or introduce a new command family.

## Features and acceptance

- [x] **Reliable large review execution.** Keep small Codex requests inline; page
  oversized requests losslessly through private temporary evidence files. Test the
  character boundary, Unicode, every review stage, errors, timeouts, and cleanup.
  Representative packets below remain the primary defence against wasted context.
- [x] **Safe failure-mode judgments.** Distinguish desirable patterns from failure
  modes in score meanings, constraints, validation, guidance, and rendering. A
  present failure mode must never imply “retain” or “improve conformance.” Preserve
  constructive-pattern safeguards and make legacy unsafe advice visibly unusable.
- [x] **Honest incremental freshness.** Explain what remains reusable, what changed,
  and what is refreshing. Keep an available prior repository summary accessible
  with explicit snapshot/freshness provenance; never label it current. Prove
  repository isolation and read-only status parity across existing transports.
- [x] **Representative, bounded review evidence.** Replace alphabetic prefixes with
  deterministic coverage of responsibilities, production modules, changed code,
  contracts, and boundary relationships. Bound the serialized packet, retain
  provenance and explicit selection/omission counts, and test documentation-heavy
  and oversized repositories. Never leak as-built evidence into blind stages.
- [x] **Grounded parent-scope pattern judgments.** Supply bounded child responsibility
  and contract witnesses and internal/cross-boundary relationships at subsystem,
  area, and repository scope. Test known missed patterns and sparse candidate
  selection without increasing the catalogue or pretending static edges prove
  runtime behavior.
- [x] **Goal-directed coherence review.** Carry the user's review goal into saved
  stage inputs and fingerprints. Respect implementation blindness, retain goals
  across resume, and invalidate only affected review work when a goal changes.
  Judge responsibility ownership, contracts, user flows, and the cost of added
  machinery through the existing review sequence and output fields.
- [x] **Architectural judgment evidence.** Add small positive, negative, and
  uncertain fixtures for justified patterns, harmful structures, and no-change
  cases. Separate deterministic protocol checks from a recorded model-backed
  experiment (GPT-6 Astra, max effort). Report known-case misses, unsupported advice,
  scope coverage, and measured/unknown cost; do not promise all possible patterns.

## Scope and verification discipline

Reuse the current index, queue, stage contracts, pattern cards, and CLI/REST/MCP/UI
surfaces. No new runtime dependency, generic review orchestrator, aggregate
architecture score, catalogue-size target, or automatic source refactoring.
Source-size and architecture gates remain binding; any justified net growth needs
an exact measured acceptance record, not an arbitrary allowance.

Run focused tests for each slice, then the full quality, changed-coverage, packaging,
browser, benchmark, and container gates. Refresh changed semantics once at the
coherent checkpoint, reusing unchanged scopes. Save review and token provenance;
a running worker or partial architecture comparison is not completion.

## Release and deployment ledger

- [x] Resolve repository identity, preserve unrelated drafts, and inspect existing
  release/deployment instructions and protection gates.
- [x] Implement and run focused verification for the feature checklist above.
- [x] Set the single Python version, lockfile, and bundled plugin versions to 0.5.0;
  record release notes and compatibility changes.
- [x] Open [PR #5](https://github.com/hcekne/anaxigraph/pull/5) and pass all seven
  protected checks for implementation commit `93d1fdd`.
- [ ] Obtain the required approving review and merge the accepted commit through
  protected main without bypassing its gates.
- [ ] Verify 0.5.0 is unused; create the immutable annotated `v0.5.0` tag from the
  accepted main commit and publish through the existing trusted release workflow.
- [ ] Verify public PyPI install, wheel/sdist, plugin ZIP, checksums, SBOM,
  attestations, and matching multi-architecture container digest.
- [ ] Confirm production target, back up the retained index, deploy the verified
  artifact while preserving both registered repositories, and verify health,
  schema/read compatibility, MCP/dashboard behavior, and rollback availability.

The target release is **0.5.0**, not complete until every release gate above is
verified. Next release-schedule checkpoint: **15 September 2026**; review outstanding
regressions and dependencies, decide whether a patch is warranted, and record that
decision here. This is a checkpoint, not a commitment to publish an unready build.

## Acceptance record

Implementation and isolated staging verification are complete; unchecked release
gates above remain open. The Phase 13 source ratchet is **63,524 lines**, up
**778 lines (1.24%)** from 62,746. This is the exact measured cost of the admitted
features, including the
previously prepared lossless Codex fallback. One shared evidence-selection module
serves existing review and pattern paths. No runtime dependency, schema table,
command family, normal MCP tool, review stage, function-limit exception, or module
size exception was added. The 500-line module and 50-line/15-complexity function
ceilings remain unchanged. This phase does not reopen unrelated consolidation to
offset necessary feature code.

Verified locally and in CI on 8 September:

- `scripts/check_architecture.py`: zero errors.
- `scripts/check_module_size.py`: zero errors.
- `scripts/check_self_analysis.py`: six governed findings, zero regressions;
  final local report `/tmp/anaxigraph-050-self-analysis-final.json`, also verified
  by the protected CI quality gate.
- Pinned Playwright container: **40 browser contracts passed**, including updating
  a review goal without restarting blind stages.
- Focused pattern, semantic freshness, goal durability, transport, generation,
  source-guard, representative-packet, and retained-history regression tests pass.
- The retained GPT-6 Astra/max judgment experiment passed **7/7 cases** across five
  scope levels, with zero known-positive misses and zero unsupported change
  recommendations. It reported **251,691 input / 85,977 output tokens**; monetary
  cost was not supplied. The [raw report](../benchmarks/results/architecture-judgment-0.5.0.json)
  retains answers, independent reviews, fixture fingerprint, and dirty-worktree
  provenance (the implementation was not yet committed when the run started).
  These seven fixtures are bounded evidence, not exhaustive pattern recall.
  An initial setup attempt was interrupted because fixture labels hinted at
  expected outcomes. Those labels were anonymized before the retained run; usage
  from the interrupted attempt is unavailable, not zero.
- Container hardening and MCP sidecar smoke passed. Three first-user runs reached
  a working dashboard in a median **1.467 s** and a first dossier in **1.632 s**.
- The clean-checkout 0.5.0 wheel and sdist passed archive verification and were
  byte-identical across two builds. Linux/macOS packaging checks passed on Python
  3.11 and 3.12. No artifacts from the dirty workspace are eligible for publication.
- [Implementation CI](https://github.com/hcekne/anaxigraph/actions/runs/34221557641)
  passed every protected check at `93d1fdd`: **952 tests** on both Python 3.11 and
  3.12, **93.35% total coverage**, and **99.08% changed-code coverage** (324/327
  executable lines), above the unchanged 80% / 85% gates. Four Linux/macOS package
  jobs, browser contracts, all source policies, Compose validation, hardened
  sidecar, bounded performance smoke, and first-user checks passed. The final CI
  first-user medians were **1.040 s** to dashboard and **1.172 s** to first dossier.
  Coverage and performance reports are retained in its `quality-evidence` artifact.
  This records the tested implementation; the documentation-only acceptance commit
  must also clear protected checks before merge.
- Read-only replay against the retained snapshot 1129 caught and corrected the
  reviewed-taxonomy envelope: the packet now represents **all 21 responsibilities**
  through **80/550 modules** (56 production, 12 test, 12 documentation) and 120
  boundary/dependency links. All six areas, 21 subsystems, full paths, and owner
  identities survive compaction; omitted evidence is counted. It retains 300-character
  excerpts within the 600,000-byte current-system budget. Unmapped files are reported
  separately, not counted as a fictitious responsibility. These corrections add
  exactly 20 source lines to the initial Phase 13 acceptance; no limits were relaxed.
- Upgrade rehearsal found unindexed per-set edge and reference lookups: 53,743 sets
  repeatedly scanned 474,899 edges and 539,752 coverage rows. Four narrow SQLite
  lookup indexes now precede compaction and are restored on same-version opens.
  The integrity gate also correctly refused duplicate cleanup that relied on
  disabled cascade actions; that attempt rolled back. Duplicate edges are now
  explicitly removed after their references are preserved, and affected checkpoint
  fingerprints are rebuilt through the existing checkpoint mechanism. These
  deployment-blocking corrections add **14 source lines** beyond the evidence
  corrections above, without a new table or data model or any relaxed safeguard.
- Corrected upgrade rehearsal: the **1.6 GB / 1,131-snapshot** retained copy migrated
  from schema 10 to 11 in **39.294 s**, with zero integrity or foreign-key violations.
  Both repository identities and current snapshots (1131 and 1128) were preserved.
  Repository 1 retains the prior Charter from 1129, explicitly stale; semantic reuse
  has not yet been prepared for 1131. The pristine backup and old container image
  remain available for rollback. **34 migration, recovery, temporal, index-doctor,
  and checkpoint tests pass**, including a duplicate-set/coverage/checkpoint fixture.
- Full index health additionally exposed an existing forked-lineage cache bug:
  checkpoint cadence followed global sequence numbers rather than actual ancestry.
  `bounded-delta-v4` adds the depth condition to the existing cache policy (one net
  source line). Refreshing disposable checkpoints took **2.079 s**; all 1,131 frames
  now pass the full health check with a maximum **15 traversed deltas**, versus 82
  before upgrade, and zero blockers. Forked-history and migration regressions pass.
  This rebuilds derived index caches, not AI descriptions or immutable source facts.
- Post-upgrade counts preserve **144,274 file facts, 7,682 semantic documents,
  6,105 semantic claims, and 539,752 coverage records**. Full file/symbol/relationship
  digests match before and after for six sampled historical/current frames,
  including both repositories. The full lineage, checkpoint-hash, foreign-key,
  integrity, and semantic-reference checks pass across the retained index.
- The clean `93d1fdd` release-candidate container passed isolated staging against
  that retained index: version 0.5.0, healthy REST and MCP, working dashboard,
  both repositories preserved, correctly stale prior Charter, and all index-health
  checks passing. Read-only root, dropped capabilities, no-new-privileges,
  read-only repository mounts, and a loopback-only port were verified. The staging
  container was stopped and removed after validation; the backup, test index, and
  rollback image remain. This was not a production deployment or public artifact.
- The final structural checkpoint is snapshot **1132**: 14 changed files analyzed,
  547 unchanged files reused, and no model jobs enqueued. No full semantic reread
  was requested. The preflight backup captures 1131; take a fresh validated backup
  immediately before an authorized production cutover.
- Production and changed-semantic verification remain open. The live service uses
  the older executor protocol, so the one incremental GPT-6 Astra/medium refresh
  must follow its upgrade; no incompatible worker or forced full reread was started.

The required PR review is still absent, and the owner is the only repository
collaborator; no maintainer bypass has been authorized. Production-target
confirmation is also outstanding. No release tag, PyPI publication, or production
replacement has occurred. Record accepted-main and public artifact identities,
deployment verification, and incremental semantic progress here before marking
this phase complete.
