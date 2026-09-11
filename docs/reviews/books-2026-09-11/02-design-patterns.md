# AnaxiGraph through the Gang of Four

11 September 2026 · Book: *Design Patterns: Elements of Reusable Object-Oriented Software*, Gamma, Helm, Johnson, and Vlissides, 1994.

## Verdict

AnaxiGraph has a considerably richer pattern vocabulary than a simple Gang-of-Four checklist, and its assessment contracts already ask many of the right questions. However, its bundled catalog contains dedicated entries for only **18 of the 23 GoF patterns**. More importantly, neither catalog size nor schema completeness demonstrates reliable recognition or sound recommendations.

The priority is better judgment about applicability, existing language idioms, and object collaboration—not adding five patterns and declaring architectural coverage complete.

This is a source audit of the current working tree. It does not claim all detailed-review paths are enabled, current, or deployed. [Scope and evidence](00-synthesis-and-refactoring-plan.md#scope-and-evidence).

## Analysis of the recommendation

This book is valuable as a vocabulary of recurring collaborations, including when a solution is applicable and what it costs. It is not a specification that every program should implement all 23 structures. The publisher describes six chapters followed by reference appendices. [Publisher's contents and description](https://www.informit.com/store/design-patterns-elements-of-reusable-object-oriented-9780321700698).

For AnaxiGraph, the important distinction is between recognizing a useful design and recommending more machinery. A function parameter may already supply interchangeable behavior. A language iterator can already hide traversal. Detecting no bespoke class hierarchy is not evidence that the design is deficient.

## Chapter and topic map

Short topic labels and summaries below follow the [publisher's chapter structure](https://www.informit.com/store/design-patterns-elements-of-reusable-object-oriented-9780321700698). The AnaxiGraph column is this audit's assessment.

| Chapter / topic | Book's focus, briefly | Assessment of AnaxiGraph |
| --- | --- | --- |
| 1. Orientation | Vocabulary, applicability, and design choices. | Strong contract coverage: cards describe intent, trade-offs, alternatives, and invariants. Recognition accuracy is not established by those fields. |
| 2. Editor example | Patterns cooperating within one application. | Partial: relation metadata connects cards; repository and fresh-eyes reviews can discuss systems. There is no demonstrated participant-level verification of a whole collaboration. |
| 3. Creation | Manage construction and variation. | Incomplete dedicated coverage: Abstract Factory and Factory Method are present; Builder, Prototype, and Singleton are absent. |
| 4. Structure | Compose objects and interfaces. | Six of seven dedicated cards exist. Some candidate signals lean on inheritance and risk missing idiomatic composition. |
| 5. Behavior | Organize responsibilities and interactions. | Ten of eleven dedicated cards exist. Iterator is absent; branch-count signals are weak evidence for actual variation boundaries. |
| 6. Synthesis | Reuse design knowledge in context. | Positive: retain, avoid, no-action, and insufficient-evidence outcomes exist. Broader validation of when the tool chooses each is still needed. |

The appendices cover terminology, notation, and supporting classes. Their relevance to AnaxiGraph is consistent terminology and explicit representation—not reproducing the book's class library.

## Coverage of all 23 patterns

The role column is a brief orientation. Coverage comes from reading the repository's catalog files, not from asking a model whether it knows the names. “Present” means a dedicated card, **not proven detection**. The catalog's own intent, questions, and liabilities provide substantially more detail than this table.

| Group | Pattern | Core role | Dedicated AnaxiGraph card |
| --- | --- | --- | --- |
| Creation | Abstract Factory | Compatible object families | Present: object/interface |
| Creation | Builder | Staged construction | **Missing** |
| Creation | Factory Method | Deferred concrete construction | Present: object/interface |
| Creation | Prototype | Copy-based creation | **Missing** |
| Creation | Singleton | Controlled single instance | **Missing** |
| Structure | Adapter | Interface translation | Present: object/interface |
| Structure | Bridge | Independent variation dimensions | Present: object/interface |
| Structure | Composite | Uniform recursive composition | Present: object/interface |
| Structure | Decorator | Composable behavior wrapping | Present: object/interface |
| Structure | Facade | Simpler subsystem access | Present: object/interface |
| Structure | Flyweight | Shared intrinsic state | **Missing** |
| Structure | Proxy | Mediated object access | Present: object/interface |
| Behavior | Chain of Responsibility | Successive potential handlers | Present: composition/workflow |
| Behavior | Command | Represented requests | Present: composition/workflow |
| Behavior | Interpreter | Grammar-driven evaluation | Present: composition/workflow |
| Behavior | Iterator | Encapsulated traversal | **Missing** |
| Behavior | Mediator | Centralized interaction coordination | Present: composition/workflow |
| Behavior | Memento | Encapsulated state capture | Present: data/state |
| Behavior | Observer | Change notifications | Present: composition/workflow |
| Behavior | State | State-dependent behavior | Present: object/interface |
| Behavior | Strategy | Interchangeable algorithms | Present: object/interface |
| Behavior | Template Method | Customizable algorithm skeleton | Present: object/interface |
| Behavior | Visitor | Operations across structures | Present: composition/workflow |

Catalog evidence: [object/interface](../../../src/anaxigraph/catalog/patterns-object-interface.json), [composition/workflow](../../../src/anaxigraph/catalog/patterns-composition-workflow.json), and [data/state](../../../src/anaxigraph/catalog/patterns-data-state.json). A `test-data-builder` elsewhere in the catalog is not general GoF Builder coverage.

The full catalog has **128 cards in eight families**, sixteen per family. It also covers functional construction, module boundaries, integration/concurrency, reliability/testing, and subsystem architecture. These are useful extensions beyond this book. No finite count establishes coverage of every architecture concern a user may encounter.

## What is already good

[PatternCard](../../../src/anaxigraph/pattern_catalog_models.py) includes intent, scope, required analyzer capabilities, supporting and contrary signals, semantic questions, benefits, liabilities, migration cautions, relationships, and verification invariants. This is substantially better than naming patterns from class names.

The [evaluation contract](../../../src/anaxigraph/pattern_evaluation_contract.py) separates applicability, suitability, conformance, opportunity, confidence, benefit, urgency, execution safety, and migration cost. These are different questions. It allows retaining a design and explicitly declining to judge when evidence is insufficient.

The [independent critique request](../../../src/anaxigraph/semantic_pattern_requests.py) asks whether the assessment targeted the right code, overlooked alternatives, ignored contrary evidence, or underestimated cost. The critic can return a corrected judgment, rather than merely approve the original prose.

The [candidate planner](../../../src/anaxigraph/pattern_candidates.py) selects bounded work instead of evaluating every card against every file. That restraint is valuable. In the current working tree, [pattern planning](../../../src/anaxigraph/semantic_pattern_plan.py) is skipped unless detailed reviews are enabled. Do not confuse a lightweight semantic map with an exhaustive pattern audit.

## Important gaps

### 1. Candidate filtering may miss language-native implementations

The object/interface defaults require structural capabilities for calls, constructors, exports, inheritance, signatures, and symbol kinds. Individual cards include these problem signals:

- Composite and Decorator: at least two inheritance observations.
- Strategy: at least three control-flow observations.
- Abstract Factory: multiple construction observations.

[Candidate selection](../../../src/anaxigraph/pattern_candidate_selection.py) can discard a target for no positive evidence or insufficient priority before semantic assessment. Capability gaps affect the evidence/selection process; they are not simply a universal hard exclusion.

The resulting **recall risk** is concrete: a Python callable strategy need not have many branches; a wrapper need not use inheritance; a recursive data structure need not declare a class hierarchy. Conversely, many branches or constructors do not establish these patterns. This audit has not measured the actual false-negative rate.

**Improvement:** add small positive and negative fixtures for each supported idiom, then adjust existing feature projection and card signals where the fixtures justify it. Preserve sparse selection. Do not solve a recall problem by multiplying all model work by 128.

### 2. Names and relationships do not establish collaboration

The schemas can describe participants in prose, but a rigorous explanation needs to identify the actual policy, caller, wrapper, delegate, state owner, or construction boundary—and explain the contract between them. Card-level “related to Strategy” metadata does not establish that concrete modules collaborate correctly.

**Improvement:** attach optional participant/role witnesses to existing evaluations. Require source references for the relevant collaboration and state what cannot be inferred. Reuse the graph's existing symbols and relationships; do not introduce a separate pattern graph database.

### 3. Confidence is corrupted downstream

Although the evaluation contract correctly separates opportunity and confidence, [pattern_effect_spec](../../../src/anaxigraph/reassessment_semantic_advice.py) uses opportunity to populate an architectural effect's confidence. A deterministic diagnostic with opportunity 95 and confidence 20 produces confidence 0.95.

This is an implementation bug, not a philosophical disagreement. Fixing it is more important than adding missing cards. An independently reviewed opportunity may still have low evidential confidence.

### 4. Missing patterns need careful treatment, not forced introduction

Iterator coverage should recognize built-in iteration. Builder coverage should distinguish useful staged construction from unnecessary fluent ceremony. Prototype needs copying/identity semantics, not merely a `copy` call. Flyweight needs sharing and mutation constraints. Singleton deserves especially strong warnings about hidden global state, isolation, and lifecycle.

These five entries can complete the vocabulary without adding five architectural mechanisms to AnaxiGraph itself. They do not need a new service, endpoint, schema family, or model workflow.

## Fulfillment of the vision

AnaxiGraph has a promising pattern-review framework. It has not demonstrated GoF-level expert judgment across real repositories or languages. Its most important unfinished task is explaining **why this collaboration serves this problem, why the current implementation is or is not sufficient, and why changing it is worth the cost**.

I recommend vocabulary completion only alongside idiom-sensitive candidate fixtures, accurate confidence propagation, and examples where the correct answer is to retain simple code. These are actions R1, R2, R7, and R10 in the [combined plan](00-synthesis-and-refactoring-plan.md#refactoring-and-improvement-plan).
