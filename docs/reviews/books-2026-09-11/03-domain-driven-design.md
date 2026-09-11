# AnaxiGraph through Domain-Driven Design

11 September 2026 · Book: *Domain-Driven Design: Tackling Complexity in the Heart of Software*, Eric Evans, 2003.

## Verdict

This book exposes the largest conceptual gap in AnaxiGraph's architecture intelligence: **a map of responsibilities and dependencies is not yet a model of what the domain means**.

AnaxiGraph already has important foundations: a Living Architecture Charter, behavioral capability briefs, explicit invariants and unknowns, responsibility taxonomy, and append-only human corrections. These should be extended selectively. They do not yet establish context-specific vocabulary, real domain boundaries, or the transactional meaning of an aggregate.

This is a working-tree assessment, not a certification of deployed behavior. [Scope and evidence](00-synthesis-and-refactoring-plan.md#scope-and-evidence).

## Analysis of the recommendation

The strategic-design recommendation is especially relevant. Evans connects software modeling to domain understanding and continuing collaboration with people who know the domain. Code inspection alone cannot recover missing business intentions. His publisher dates the book to August 2003; its copyright date is 2004. [Publisher's description and contents](https://www.informit.com/store/domain-driven-design-tackling-complexity-in-the-heart-9780321125217).

A bounded context is a scope in which a model has a consistent meaning, not automatically a folder, process, or deployable service. Context relationships need deliberate contracts. The author's later reference also distinguishes core-domain work from supporting mechanisms. [Eric Evans, DDD Reference, licensed CC BY 4.0](https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf).

My application to AnaxiGraph: do not mistake structural proximity for conceptual agreement, and do not recommend distributed infrastructure just to express a logical boundary.

## Chapter and topic map

This compact map follows the original book's seventeen chapters and four parts. Labels are shortened; AnaxiGraph assessments are original analysis. [Publisher's contents](https://www.informit.com/store/domain-driven-design-tackling-complexity-in-the-heart-9780321125217).

| Part / chapter | Book's focus, briefly | Assessment of AnaxiGraph |
| --- | --- | --- |
| I · 1. Discovery | Refine models through domain learning. | Partial: semantic inference and declared corrections support revision. A source scan cannot replace discovery with users and domain experts. |
| I · 2. Language | Align communication and domain vocabulary. | Gap: module `domain_concepts` are strings, not context-scoped definitions with conflicting meanings and authoritative corrections. |
| I · 3. Implementation alignment | Keep model and code connected. | Partial: the Charter links claims to entry points and evidence. Free-text evidence does not establish that the code enforces the claimed model. |
| II · 4. Domain isolation | Separate domain decisions from infrastructure. | Partial: modules and ports exist. SQLite connections exposed through semantic ports weaken isolation of lifecycle policy from persistence details. |
| II · 5. Building blocks | Entities, values, services, and modules. | Partial: the catalog recognizes relevant concepts. There is no demonstrated classification of actual identity and ownership semantics across repositories. |
| II · 6. Lifecycles | Aggregates, factories, and repositories govern lifecycles. | Partial: AnaxiGraph's own jobs have explicit transitions and guarded persistence. Identifying an aggregate elsewhere requires invariant and transaction evidence. |
| II · 7. Shipping example | Integrate modeling decisions through scenarios. | Partial: capability briefs include journeys, but routine advice is not consistently validated against complete end-to-end domain scenarios. |
| III · 8. Breakthroughs | Replace inadequate models with deeper ones. | Partial: fresh-eyes work can challenge existing organization. A plausible alternative architecture is not demonstrated domain insight. |
| III · 9. Explicit concepts | Surface hidden rules, constraints, and specifications. | Promising: Charter invariants and reader-task obstacles can expose hidden knowledge. They need links to enforcing code and unresolved questions. |
| III · 10. Flexible modeling | Intention-revealing interfaces and composable constraints. | Partial: interfaces and counterevidence are reviewed, but static shape cannot establish side-effect freedom or meaningful domain composition. |
| III · 11. Analysis patterns | Reuse domain-modeling knowledge selectively. | Limited: broad software patterns exist; deep domain-specific modeling competence is not demonstrated. Avoid a speculative industry ontology catalog. |
| III · 12. Design patterns | Choose collaborations that express domain meaning. | Partial: catalog questions address intent; pattern scoring still needs explicit domain reasons rather than structural resemblance. |
| III · 13. Model evolution | Refactor when understanding improves. | Partial: reassessment and correction history exist. Changes to domain meaning must be distinguished from behavior-preserving movement. |
| IV · 14. Context integrity | Bounded contexts and their integration contracts. | Major gap: taxonomy has ownership and cross-cutting facets, but no explicit context-specific vocabulary and integration-contract model. |
| IV · 15. Distillation | Concentrate on the differentiating domain. | Positive foundation: Charter purpose, capabilities, and non-goals. Advice should show why a change improves architecture decisions rather than merely expands analysis infrastructure. |
| IV · 16. Overall structure | Evolve useful large-scale constraints. | Partial: architecture rules and taxonomies describe structure. They cannot derive organizational obligations or deployment needs from dependencies alone. |
| IV · 17. Strategy | Combine boundaries, priorities, and learning. | Not demonstrated: the components exist, but a coherent, domain-expert-validated decision process across them is not established. |

The later DDD Reference includes additions beyond the original book. This report does not treat those additions as chapters from 2003. [Author's explanation of the reference](https://www.domainlanguage.com/ddd/reference/).

## What AnaxiGraph already does well

### It has a place for purpose, not just structure

The [Charter contract](../../../src/anaxigraph/architecture_charter_contract.py) includes purpose, actors, capabilities, responsibilities, execution flows, public contracts, invariants, extension points, coherence concerns, unknowns, and documentation/code conflicts. Named claims carry evidence, counterevidence, confidence, related claims, and entry points.

The capability brief deliberately describes observable behavior and user journeys. Its validation resists leaking internal file identities into a supposedly independent design brief. This helps fresh-eyes proposals reason from what the product must accomplish rather than merely rearranging current filenames.

### It can preserve human corrections without rewriting history

[Charter corrections](../../../src/anaxigraph/architecture_charter_corrections.py) record author, rationale, disposition, and activation state as immutable appended records. A correction can replace a claim or refute it. The inferred record remains available.

This is a sound foundation for recording domain knowledge that code alone cannot establish. A principal's declaration is evidence about intended meaning; it is not automatically proof that the implementation complies. Those two questions should remain separate.

### Its own workflow already contains genuine domain rules

[Semantic job states](../../../src/anaxigraph/semantic_job_state.py) define permitted transitions. [Completion persistence](../../../src/anaxigraph/semantic_results.py) guards writes against lost leases and coordinates related state changes. These are meaningful rules in AnaxiGraph's own domain, not arbitrary object-model decoration.

The right next step is to make these rules easier to find, explain, and preserve. Introducing new entities and repositories everywhere would add ceremony without necessarily improving their ownership.

## Where it falls short

### 1. Vocabulary is recorded but not modeled precisely

The detailed [semantic dossier](../../../src/anaxigraph/semantic_contract.py) represents `domain_concepts` as a string array. The [taxonomy](../../../src/anaxigraph/semantic_taxonomy_contract.py) models areas, subsystems, file membership, and cross-cutting facets. Both are useful, but neither gives a concept a context-specific definition with explicit interpretation at boundaries.

In AnaxiGraph itself, consider “current”:

- Does the scan correspond to the present checkout?
- Is a module's saved meaning reusable for its present input?
- Is the broader context assessment current?
- Is a review based on that same snapshot and intent?

These are not interchangeable. Likewise, a Snapshot, a semantic document, a Job, a Lease, and a Recommendation have different identities and lifecycles. A good model should make those distinctions easy to discover, not force readers to infer them from several status dictionaries.

**Lean improvement:** add optional, context-scoped concept definitions and critical invariant references to the existing Charter/correction path. Start with AnaxiGraph's own ambiguous terms. Do not merge identical words across contexts automatically, and do not create a second canonical architecture database.

### 2. A dependency edge cannot establish a valid domain boundary

The `bounded-context` catalog card refers to `semantic.term_conflicts`; the DDD card refers to `semantic.domain_complexity`. A source search found those exact feature names in catalog declarations, not in a dedicated feature producer. Candidate selection can still use unknown-semantic evidence as a reason to investigate; absence of a producer does not mean these cards can never be evaluated.

What is missing is direct evidence for the judgment: competing definitions, ownership, translation rules, compatibility obligations, and examples of the same concept crossing a boundary.

**Lean improvement:** enrich a selected context review with a few concrete term conflicts and boundary contracts. Preserve “unknown” when organizational or business evidence is absent. Keep the responsibility taxonomy as a navigation structure; do not relabel it “bounded contexts” without the additional semantics.

### 3. Aggregate recognition needs behavioral evidence

An aggregate is not simply a cluster of heavily connected classes. For a candidate consistency boundary, ask which invariant must hold, which operation changes the relevant state, what happens under concurrency, and where failure or rollback is handled.

AnaxiGraph has places to record invariants and analyzer limitations, but this audit found no basis for claiming general verification of those behaviors. Source and mutation observations can support a hypothesis, not certify atomicity.

**Lean improvement:** attach an invariant owner and boundary-focused verification requirement to selected recommendations. For AnaxiGraph's lifecycle, preserve the existing single completion transaction during any restructuring. Do not distribute it merely to obtain cleaner-looking file boundaries.

### 4. Core purpose must govern new features

My reading of the product's intended core is evidence-grounded help with understanding and improving architecture. Queues, provider integrations, taxonomies, and dashboards support that purpose. Their existence is not the outcome users buy.

Every proposed capability should answer: which architecture decision becomes more reliable, which user uncertainty disappears, and what ongoing machinery can be reused or removed? This is a practical way to resist system bloat while improving domain intelligence.

## Fulfillment of the vision

AnaxiGraph has an unusually useful starting point for domain-aware assistance, but it has not demonstrated the contextual understanding of an expert who has internalized Evans. The largest step forward is not another named DDD pattern: it is a more precise relationship between purpose, language, invariants, evidence, and code.

Prioritize optional context definitions, authoritative corrections, and invariant-owning lifecycle boundaries. Validate them against concrete user scenarios. See actions R2, R3, R4, R6, and R10 in the [combined plan](00-synthesis-and-refactoring-plan.md#refactoring-and-improvement-plan).
