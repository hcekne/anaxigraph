# Can AnaxiGraph exercise expert architectural judgment?

Four-book assessment and bounded improvement plan · 11 September 2026

## Bottom line

**AnaxiGraph has useful foundations for expert architectural assistance, but it has not demonstrated the judgment of a human who has deeply internalized these four books.** It can organize evidence, explain responsibilities, review pattern candidates, compare alternative architectures, and offer cautious change advice. That is meaningful progress. It is not yet evidence of expert-level design decisions across real repositories.

The biggest shortfall is not simply missing patterns. It is the connection between a recommendation, the domain problem it solves, the complexity it removes, the behavior it preserves, and the evidence supporting those claims.

There is also a specific implementation bug: one reassessment projection turns **opportunity into confidence**. That should be corrected before expanding the judgment system.

The lean path is to deepen existing capabilities, not add one subsystem per book.

## Individual reports

Each report contains a chapter/topic map, an assessment against AnaxiGraph, concrete repository evidence, and improvements:

1. [Ousterhout: A Philosophy of Software Design](01-philosophy-of-software-design.md) — 22 chapters; complexity and abstraction quality.
2. [Gang of Four: Design Patterns](02-design-patterns.md) — six chapters and all 23 patterns; collaboration and applicability.
3. [Evans: Domain-Driven Design](03-domain-driven-design.md) — 17 chapters; domain meaning, boundaries, and strategic coherence.
4. [Fowler: Refactoring](04-refactoring.md) — 12 second-edition chapters; controlled, behavior-preserving evolution.

## Scope and evidence

This is a source-grounded review, not a new automated semantic scan and not an implementation. I inspected source, contracts, prompts, policies, benchmark code and saved results, and read the existing AnaxiGraph status. I also used author/publisher materials for the books. The chapter maps are concise orientations, not substitutes for the books or a claim that I reread four complete licensed texts.

The requested editions were used. Ousterhout's second edition is confirmed by his [edition notes](https://web.stanford.edu/~ouster/cgi-bin/book.php). Fowler's map uses the [second-edition ebook contents](https://www.informit.com/store/refactoring-improving-the-design-of-existing-code-9780134757698), not an older contents list exposed by another product listing. Book-specific sources are cited alongside the relevant discussion in each report.

Inspection baseline:

- Repository: `/home/hcekne/repos/anaxigraph`; branch `docs/release-0.5.1-evidence`; HEAD `5f34bd48516e5d8c1bdb79e6e701a87f9f6baae2`.
- At the start, 68 tracked files were modified, including 42 runtime files. Existing untracked work included understandability code, benchmark fixtures, tests, and capability documents. Those changes belong to the existing work, not this review.
- The reviewed checkout contained 274 production Python files, including 76 root-level `semantic*.py` modules and 13 `semantic_fresh_eyes*.py` modules. Counts describe the inspected tree; they are not quality scores.
- The served status inspected during the audit referenced snapshot **1258**, with 266 of 575 indexed modules current, and reported `semantically_ready: false`. Its Charter was stale and originated at snapshot **1129**. These records are context, not a fresh verdict on the present checkout. Indexed modules and production Python files are different populations.
- New understandability assessment and reader-benchmark code was present locally but untracked. This report credits its design without claiming it has shipped or passed its proposed acceptance checks.

Evidence terminology:

- **Implemented mechanism:** source contains a relevant capability; that alone does not establish its reliability.
- **Working-tree addition:** present locally, not treated as released.
- **Observed result:** a specific saved artifact or diagnostic, with a bounded interpretation.
- **Gap/risk:** missing representation, insufficient evidence, or a reasoned failure possibility—not automatically a reproduced user-facing failure.
- **Proposed:** suggested future work, not completed work.

No product code was changed; no new scan, semantic/model job, benchmark run, product test suite, deployment, or release was started. Only these five report files were added. Git status required explicit work-tree selection because the repository's local `core.bare` setting was true during later inspection; this review did not change Git configuration.

## Combined assessment

| Lens | AnaxiGraph's strongest foundation | What remains insufficient | Desired user outcome |
| --- | --- | --- | --- |
| Ousterhout | Keep/merge/split judgment; new task-centered understandability policy | Demonstrated reduction in caller knowledge, indirection, and change effort | A correct change becomes easier without requiring more architectural explanation |
| GoF | Rich cards, separate scoring dimensions, critique, explicit no-action outcomes | Idiom-sensitive recognition, collaboration evidence, calibrated judgment | Patterns explain real design choices without encouraging unnecessary machinery |
| Evans | Charter, capability brief, invariants, taxonomy, attributed corrections | Context-specific meanings and verified ownership of domain rules | Recommendations respect what the product's concepts actually mean |
| Fowler | Compatible-baseline reassessment, sequencing, protected contracts, verification guidance | A precise transformation contract and attributable behavior-check results | Users can distinguish a plausible improvement from a safely verified change |

These books should constrain one another. “Extract a helper” is not good merely because it appears in a refactoring catalog; it must improve the abstraction. A technically elegant shared abstraction is not good if it merges concepts with different domain meanings. A desirable redesign is not yet a safe migration. Useful comments about rationale and constraints should not disappear because some comments can signal hidden complexity. Fowler's inclusion of inverse transformations is particularly useful here. [Fowler on the revised catalog](https://martinfowler.com/articles/refactoring-2nd-changes.html).

## Findings that deserve priority

### F1. Confidence is not preserved through the judgment pipeline

The [pattern evaluation contract](../../../src/anaxigraph/pattern_evaluation_contract.py) correctly separates opportunity from confidence. The persisted reader exposes both. But `pattern_effect_spec` in [reassessment_semantic_advice.py](../../../src/anaxigraph/reassessment_semantic_advice.py) reads `scores.opportunity` and returns:

```python
"confidence": min(0.95, max(0.2, score / 100))
```

A read-only deterministic diagnostic using the actual function supplied `opportunity: 95` and `confidence: 20`; the returned architectural effect had `confidence: 0.95`.

That demonstrates a data-semantics bug in the projection. It does not establish how often users have encountered the resulting overstatement. Correct it first, and inspect adjacent conversions for the same mistake. Missing or zero confidence must not quietly become optimistic confidence through defaults.

[Architecture guidance](../../../src/anaxigraph/architecture_guidance.py) also maps evidence availability to fixed numeric confidence tiers. Those tiers are heuristics, not calibrated probabilities of correctness. Name and present them accordingly.

### F2. Grounded identifiers are not grounded conclusions

[Fresh-eyes grounding](../../../src/anaxigraph/semantic_fresh_eyes_grounding.py) contains an honest caveat: it checks whether cited identifiers exist, not whether the advice is correct. Yet the aggregate status is `confirmed` when those identifiers resolve. It may report `already_satisfied` when the proposed route or symbol name already exists.

The checks are worth keeping. Their interpretation should be narrower: reference resolution, claim support, and behavior verification are different evidence states. A consumer should not need to read a caveat to discover that “confirmed” did not confirm the recommendation's premise.

### F3. Pattern coverage is broad, but not complete or validated

The bundled catalog has **128 cards**, including **18 of the 23 GoF patterns**. Dedicated Builder, Prototype, Singleton, Flyweight, and Iterator entries are absent. The [GoF report](02-design-patterns.md#coverage-of-all-23-patterns) maps every pattern.

More consequentially, some candidate signals favor inheritance counts or branch counts. A language-native function strategy or wrapper can be useful without those structures. Because selection precedes model assessment, omitted candidates may never receive semantic consideration. This is an evidenced recall risk, not a measured false-negative rate.

Completing 23 names would improve vocabulary coverage, not establish that AnaxiGraph recognizes every useful architectural pattern. Domain-specific constraints, runtime behavior, language idioms, and operational requirements remain outside any fixed name list.

### F4. Domain coherence is only partly represented

[Charter claims](../../../src/anaxigraph/architecture_charter_contract.py) and [corrections](../../../src/anaxigraph/architecture_charter_corrections.py) can capture purpose and invariants. But the dossier's `domain_concepts` are strings, while the taxonomy primarily describes responsibilities and membership, with facets for cross-cutting concerns.

That is not yet a context map of definitions and integration contracts. A future domain-aware recommendation should say which meaning applies, who owns the rule, and what evidence establishes the boundary. It should ask for missing domain knowledge rather than invent it from filenames.

### F5. Advice about preserving behavior is not verification

[Architecture reassessment](../../../src/anaxigraph/architecture_reassessment.py) already compares compatible saved states. Do not build it again. The missing layer is an explicit connection from a proposed change to an observable invariant and a check whose actual result belongs to the reviewed revision.

Structural improvement, more current semantics, and model agreement do not establish behavior preservation. AnaxiGraph can remain a read-only observer while consuming clearly attributed verification evidence from the tools that actually perform a change.

### F6. The product's own guardrails can conflict with its advice

At inspection, ten production Python files were between 475 and 500 lines; the dashboard HTML had 500 lines. The [module policy](../../../quality/module-size-policy.json) imposes the ceiling, while [decomposition advice](../../../src/anaxigraph/agent_decomposition.py) correctly allows retaining a cohesive module.

There is tension between these policies. Counts alone do not justify relaxing controls, but controls should not force harmful extractions. The better criterion is a documented boundary and demonstrable maintenance benefit, with a narrowly reviewed exception when necessary.

### F7. Expert-equivalence evidence is currently too thin

The saved [architecture-judgment benchmark](../../../benchmarks/results/architecture-judgment-0.5.0.json) reports **7/7 synthetic cases passed** using GPT-6 Astra at max effort on 8 September. The artifact records a dirty revision. Its cases include retaining cohesive designs, avoiding unjustified infrastructure, and acknowledging missing requirements. This is encouraging evidence for those fixtures.

It is not a human comparison, broad held-out validation, or proof about this current working tree. The uncommitted [reader benchmark](../../../benchmarks/understandability.py) adds a useful task-oriented direction, but supplies all source files in small examples and has no saved result among the inspected result artifacts.

Model competence, AnaxiGraph's evidence selection, and the combined agent workflow need separate evaluation. A stronger model alone cannot recover evidence the planner omitted or correct a confidence field corrupted after inference.

## Is the product cohesive and coherent?

**Its intended workflow is cohesive; its implementation and evidential language are only partly coherent.**

The cohesive core is helping a person or coding agent understand a repository and make an informed architecture decision. Scanning, saved meaning, pattern assessment, Charters, and reassessment can all serve that purpose.

The less coherent parts are the boundaries between those capabilities: similarly named confidence fields mean different things; a verified identifier can resemble a verified claim; responsibility grouping can be mistaken for domain understanding; and a structural comparison can sound stronger than its behavioral evidence.

For users, the product should consistently answer:

1. What do we actually know about the code relevant to this task, and how current is it?
2. What interpretation best explains it, and what remains uncertain?
3. What is the smallest useful change, including the option to leave it alone?
4. What must remain true, and what check would establish that?
5. After a change, what improved, what regressed, and what is still unverified?

Most of the necessary surfaces already exist. Strengthen their shared meanings and task flow. Preserve the current working-tree direction of a lightweight default map with opt-in detailed reviews; do not make every user run a full architectural deliberation to locate one function.

## What fresh-eyes review contributes—and cannot establish

Multiple clean-sheet proposals and blind adjudication help expose alternatives and reduce anchoring to current filenames. Comparison can recognize existing strengths, legitimate reasons to differ, migration cost, and unsupported proposals. This is a useful implementation of design alternatives, not just a request to “find more problems.”

However, proposals can share omissions inherited from their capability brief. Reviewers can make correlated mistakes. Isolation declarations can be self-reported. Identifier grounding is limited. A completed workflow proves that stages completed, not that the design is correct or user benefit was measured.

Improve the existing workflow's evidence and output contract. Do not append four additional reviewers—one per book—to every run.

## Refactoring and improvement plan

These are suggestions for later implementation. The distinction between bug fixes, refactors, capabilities, and validation is intentional. None is marked complete by this report.

| ID | Type | Bounded change | Primary existing locations | Acceptance evidence |
| --- | --- | --- | --- | --- |
| R1 | Bug fix | Preserve judgment confidence separately from opportunity and safety | `reassessment_semantic_advice.py`, `architecture_guidance.py`, existing reassessment tests | High opportunity/low confidence, zero confidence, and missing confidence retain their distinct meanings through user-facing projections |
| R2 | Contract correction | Separate reference resolution, claim support, and observed verification | `semantic_fresh_eyes_grounding.py`, existing review contracts and consumers | An existing name never alone establishes intended behavior; old saved reports remain readable |
| R3 | Refactor | Consolidate only genuinely shared evidence and score conversions | Existing guidance, reassessment, pattern persistence/read projections | Equivalent outputs for unaffected inputs, explicit intentional changes, fewer duplicated semantic conversions |
| R4 | Refactor | Deepen the existing semantic-job persistence boundary | `semantic_index_port.py`, `semantic_results.py`, `semantic_lease_claim.py`, `semantic_job_state.py` | Same claim/completion/retry/expiry behavior and atomicity; a maintenance task requires fewer storage-specific assumptions |
| R5 | Complete/evaluate local work | Finish task-centered understandability, including caller obligations | `understandability.py`, existing dossier/guidance/reassessment integration, reader fixtures | Stable tasks, honest unknowns, clear counterevidence, correct paired task outcomes; no blanket quality score |
| R6 | Capability extension | Add optional context-scoped definitions and invariant ownership | Existing Charter contract/corrections, taxonomy facets, evidence projection | Intentional same-word/different-meaning cases remain separate; unclear domain assumptions are surfaced rather than invented |
| R7 | Coverage improvement | Improve idiom-sensitive candidates and add the five missing GoF vocabulary entries | Existing catalog, candidate selection/feature projection, fixtures | Positive, negative, already-satisfied, and missing-evidence cases per added idiom; bounded candidate/model work |
| R8 | Capability extension | Attach bounded transformation and verification requirements to selected advice | Existing fresh-eyes/reassessment/decomposition contracts | Exact target, preserved behavior, preconditions, small sequence, attributable result status, and rollback where relevant |
| R9 | Policy change | Reconcile size guardrails with cohesive boundaries | Existing quality policies and checkers | Justified exceptions are reviewable; splitting, retaining, and inlining are judged by tasks rather than line count alone |
| R10 | Validation | Expand existing benchmarks to held-out real tasks and expert comparison | Existing architecture-judgment and reader harnesses | Comparable task budgets, blinded grading, correctness-first results, disclosed misses/false positives and uncertainty |

### Recommended execution order

**First: repair trust, without a semantic refresh.** Implement R1 and R2 in separate, focused changes. Define R10's initial regression cases at the same time. These concern deterministic projection and interpretation; they should not invalidate unrelated saved module meaning. If a stored contract evolves, use explicit versioning and compatibility adapters.

**Second: demonstrate one genuine simplification.** Apply R3 only to established duplication, then R4 to one lifecycle operation. Complete the already-started R5 path and use its tasks to assess that change. Do not reorganize all 76 semantic-prefixed modules in one pass. Consider R9 when a real cohesive boundary conflicts with the gate, not as permission to stop reviewing growth.

**Third: deepen selected judgments.** Add R6 and R8 for a narrow user task and domain slice. R7 can be a small catalog/fixture change, but detection improvements should be justified by examples rather than an ever-expanding list of heuristics. Keep deep reviews explicit and scoped.

**Then: earn stronger claims.** Run the broader R10 evaluation only with an agreed scope and model budget. Expand product claims only as the evidence expands.

### Refactoring safety and rollback

For R3, preserve the public shapes and saved-document readers while moving shared conversion logic. Do not force scores with different meanings into one generic abstraction. A small immutable evidence reference or explicit confidence type is useful only if it removes real confusion at multiple consumers.

For R4, characterize the existing lifecycle before moving code. A completion transaction must not be split across calls that can partially commit. Keep provider execution outside database transactions where it already belongs. Retain existing lease-loss and supersession checks. Move one operation, verify it, then continue; avoid concurrent database schema changes. Temporary adapters are acceptable only with a removal plan.

For R6 and R8, add optional fields to existing versioned documents and preserve previous reports. Unknown historical evidence must remain unknown; migration must not manufacture certainty. Keep additions on demand so ordinary mapping does not gain another mandatory analysis pass.

## How to avoid system bloat

Use five constraints on every proposed addition:

1. **Name the user task.** An abstract promise of “richer intelligence” is insufficient.
2. **Name the existing owner.** Prefer extending a current contract or service over adding an overlapping subsystem.
3. **Name what becomes simpler.** Identify removed caller knowledge, duplicate conversion, repeated work, or unnecessary indirection.
4. **Name the evidence and cost.** Record both the improvement check and any added model/runtime work. No full refresh for unrelated projection changes.
5. **Name the stopping point.** Keep no-change outcomes and avoid speculative generality.

Do not add microservices, a new graph database, an ORM, a generic workflow engine, an industry-wide ontology, or mandatory per-book model passes for this plan. Do not paste entire books into prompts. Small review questions, inspectable evidence, and well-chosen counterexamples are more useful.

## What would justify expert-level claims?

Define a bounded target first: expert-quality architecture assistance for declared languages, repository classes, and maintenance tasks. “Better than every human architect on every system” is not an actionable acceptance criterion, and these four books do not exhaust architecture, security, operations, or domain expertise.

Extend the existing harnesses with held-out real repositories and cases that include cohesive large modules, over-factored small modules, Python/JavaScript/TypeScript idioms, misleading names, intentionally different domain meanings, missing requirements, and runtime/transaction constraints invisible to simple dependency counts.

Compare the same coding agent with and without AnaxiGraph under matched information and budgets. Independently have qualified reviewers grade anonymized recommendations and outcomes; retain disagreement rather than manufacturing one authoritative score. Human maintenance trials can then test whether the interface itself helps people.

Measure correctness first, then unnecessary interventions, missed material risks, task completion, compatibility regressions, and effort on comparable correct solutions. Record confidence calibration, repeat trials, and publish limitations. Separate improvements attributable to the model from those attributable to AnaxiGraph's evidence selection and workflow.

That is the route from an ambitious architecture assistant to a credible expert one: **better-supported decisions, demonstrated on real tasks, with less unnecessary machinery**.

## Agent-specific follow-up

The chapter assessments above are useful design lenses, but human readability is not a substitute
for agent effectiveness. The original review underemphasized that distinction. Treat proposed
benefits from smaller functions, deeper abstractions, additional documentation, or richer schemas
as task-dependent hypotheses. An agent's failure to understand an omitted dependency is not, by
itself, evidence that the dependency needs refactoring.

Following discussion, a first local implementation was added on top of the 0.6.1 checkout:

- One concise agent-aware policy is shared by existing detailed module, pattern, and fresh-eyes
  review instructions. It compares retaining code, improving context, and the smallest code change;
  additions need an actual consumer or evidenced failure. No new mandatory response fields.
- The policy has review-specific input identities. Routine five-field mapping and its existing
  input hashes remain unchanged; no blanket semantic refresh is part of this integration.
- Existing evidence shortening preserves supplied mission/constraints, public contracts,
  invariants, protected behavior, and counterevidence. It refuses a packet whose essential context
  cannot fit, rather than silently losing obligations. It cannot restore facts absent from retrieval.
- Three cases extend the existing opt-in architecture-judgment fixtures: five fields versus an
  unsupported 24-section expansion, missing agent context versus a demonstrated code defect, and
  a working callable strategy versus an unnecessary class hierarchy.

This is a policy and evidence-handling integration, not measured improvement in model judgment,
not completion of R1–R10, and not a deployment record. The historical seven-case result is unchanged.
The next evaluation should compare realistic agent tasks with matched models and budgets, including
fresh-session recovery and omitted cross-module constraints. The source-only reader benchmark and
the actual agent-plus-AnaxiGraph workflow answer different questions; retain both comparisons.

Accordingly, R6–R8 are conditional design hypotheses rather than invitations to expand every schema,
and completing a textbook catalog should not outrank a demonstrated user problem. Prefer improving
context selection when the code is sound; require task evidence before adding more machinery.

Local integration validation: 66 focused tests passed; the 37 affected mapping, evidence-selection,
and judgment tests passed again after final cleanup. These use synthetic repositories and test
doubles, not live model judgments. The implementation adds 45 production lines, recorded in the
existing maintainability ledger, without adding runtime modules or changing the five-field schema.
