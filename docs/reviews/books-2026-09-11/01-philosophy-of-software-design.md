# AnaxiGraph through Ousterhout's design philosophy

11 September 2026 · Book: *A Philosophy of Software Design*, John Ousterhout, second edition, 2021.

## Verdict

This is the most useful of the four recommendations for deciding whether AnaxiGraph's own growth is making the product better. AnaxiGraph has meaningful mechanisms for resisting unnecessary decomposition, and the current, uncommitted understandability work is particularly well aligned. However, it has not demonstrated that its recommendations reduce the knowledge and effort needed to change a real repository correctly.

The principal risk is substituting a more elaborate explanation of complexity for an actual reduction in complexity. A system can produce excellent descriptions while requiring its users and maintainers to understand too many concepts.

This report distinguishes implemented mechanisms from measured outcomes. It evaluates the inspected working tree, not a promise that all described capabilities are deployed. See the [combined report's provenance and evidence rules](00-synthesis-and-refactoring-plan.md#scope-and-evidence).

## What the recommendation gets right

Use this book as a decision lens, not a demand for long methods or a prohibition on helpers. Ousterhout's emphasis is the relationship between a module's interface and the functionality it hides. His second edition expands general-purpose design and explicitly challenges some Clean Code prescriptions about method length and comments. [Author's edition notes](https://web.stanford.edu/~ouster/cgi-bin/book.php).

For AnaxiGraph, my translation is: **does the proposed boundary remove something callers must know, or merely move it to another file?** That question is more useful than either a file-length target or a pattern count. The author's teaching material connects abstraction, dependencies, information hiding, naming, and alternatives; these should be evaluated together. [Stanford course discussion](https://web.stanford.edu/~ouster/cs190-winter24/lectures/aposd/).

## Chapter and topic map

These are concise topic summaries, with shortened descriptive labels rather than a reproduction of the contents pages. This is an orientation and an original application to AnaxiGraph, not a claim to have reread the full book. The edition-specific additions are documented in the [author's authorized extract](https://web.stanford.edu/~ouster/cgi-bin/aposd2ndEdExtract.pdf); the broader concepts are corroborated by the [author's course material](https://web.stanford.edu/~ouster/cs190-winter24/lectures/aposd/).

| Chapter / topic | Book's focus, briefly | Assessment of AnaxiGraph |
| --- | --- | --- |
| 1. Purpose | Design should make change easier. | Partial: guidance and reassessment support change decisions, but user benefit is not yet measured across realistic tasks. |
| 2. Complexity | Dependencies and obscurity create difficulty. | Partial: graphs expose dependencies; the new task assessment addresses hidden knowledge. Neither graph size nor an AI explanation measures reader difficulty. |
| 3. Strategic work | Invest in design beyond immediate functionality. | Partial: durable architecture records support continuity. Repeated local module extractions still need whole-workflow evaluation. |
| 4. Module depth | Simple interfaces should hide substantial functionality. | Gap: there is no demonstrated, task-based assessment of callers' obligations across an interface. A narrow Python Protocol can still expose storage internals. |
| 5. Hidden knowledge | Contain implementation decisions behind boundaries. | Partial: persistence is separated in places, but semantic application services still depend on SQL and table structure. |
| 6. Useful generality | General operations can simplify current requirements. | Promising: reusable semantic jobs and shared projections avoid separate engines per feature. Generality should not expand into speculative orchestration frameworks. |
| 7. Abstraction levels | Adjacent layers should offer different abstractions. | Gap: some ports are type/re-export boundaries rather than boundaries that remove knowledge. Review actual callers before deleting them. |
| 8. Owning complexity | Put difficult details inside the responsible module. | Partial: lease/state logic already has dedicated owners. Transaction and completion details remain spread across cooperating services. |
| 9. Boundary choices | Combine or separate according to shared knowledge. | Strong mechanism: decomposition can recommend keeping code together; consolidation advice also exists. Hard size gates can conflict with this judgment. |
| 10. Error design | Avoid unnecessary exceptional situations. | Partial: explicit job transitions reduce invalid-state ambiguity. Preserve genuine lease-loss and freshness errors; do not hide uncertainty to simplify output. |
| 11. Alternatives | Compare substantially different designs. | Strong mechanism: fresh-eyes proposals, adjudication, comparison, and review. Agreement is not independent evidence that the winning design works. |
| 12. Comment value | Explanations can carry otherwise missing knowledge. | Promising working-tree policy: retain rationale, domain language, and navigation. The implementation must not treat all documentation as removable duplication. |
| 13. Comment substance | Explain contracts and non-obvious reasoning. | Partial: dossiers and Charters capture this knowledge, but generated prose does not establish that the repository itself exposes it adequately. |
| 14. Names | Names should communicate precise meaning. | Gap: distinctions such as opportunity versus confidence are not preserved consistently through projections. See the confirmed bug in the combined report. |
| 15. Interface-first writing | Explain an interface while designing it. | Partial: schema-first contracts help. AnaxiGraph cannot establish when maintainers wrote comments and should assess their usefulness, not infer their chronology. |
| 16. Evolution | Preserve conceptual design while changing code. | Partial: before/after reassessment exists. Fewer findings after a change do not establish preserved behavior or better comprehension. |
| 17. Consistency | Repeated concepts should behave predictably. | Mixed: shared architecture responses help, but different confidence derivations and evidence labels give similar-looking fields different meanings. |
| 18. Obviousness | Make important behavior easy to discover. | Promising working-tree implementation: stable maintenance tasks and source witnesses. Empirical discoverability remains unproven. |
| 19. Trends | Evaluate practices by their design consequences. | Positive: catalog judgments allow avoidance and no action. Missing: broad evidence that reviewers reject fashionable but unhelpful abstractions. |
| 20. Performance | Measure costs and design important paths carefully. | Partial: usage, timing, and scale artifacts exist. Architectural recommendations still need task-specific latency, memory, and compatibility constraints. |
| 21. Priorities | Separate essential decisions from incidental detail. | Positive direction: behavioral capability briefs and a lightweight default map. Stale mission evidence and overlong review chains remain practical risks. |
| 22. Synthesis | Apply the principles together over time. | Not demonstrated: individual mechanisms exist, but there is no longitudinal evidence that their combined advice makes repositories easier to maintain. |

## What already deserves to be retained

### Task-centered understandability, already being built

The untracked [understandability implementation](../../../src/anaxigraph/understandability.py) is not just a readability score. Its policy asks a competent newcomer to locate behavior, understand contracts, and make a correct change using the repository itself, without generated architecture explanations. Assessments include source witnesses, contrary evidence, migration cost, a proposed small change, and a correctness check. Missing evidence means unknown.

It explicitly says that smaller files, fewer lines, and additional abstractions do not establish improvement. This is a substantial conceptual improvement, not something to propose again under a new name. Its advice also states that reader performance has not been measured.

The new [paired reader benchmark](../../../benchmarks/understandability.py) is a useful start: independent CLI contexts, alternating before/after order, hidden answer checks, and isolated verification of a proposed code change. Its own limitation is important: the small shipping examples supply all source files. This is not yet a study of navigation through a real repository, and CLI freshness is not OS-enforced information isolation. No saved result for this benchmark was found among the inspected benchmark results.

### Restraint about splitting

[Decomposition advice](../../../src/anaxigraph/agent_decomposition.py) treats size as a review trigger, not proof that splitting is correct. Its preliminary decision can retain a cohesive responsibility; a split needs evidence and a useful symbol-to-responsibility mapping. [Decision safety](../../../src/anaxigraph/agent_decision_safety.py) also considers consolidation and reasons to keep modules separate.

These mechanisms are closer to architectural judgment than “large file detected; extract helpers.” Keep them.

## Where the implementation falls short

### 1. Some boundaries do not hide the difficult knowledge

[SemanticIndex](../../../src/anaxigraph/semantic_index_port.py) is called a narrow persistence interface, but exposes SQLite connections, transaction contexts, and a private-named snapshot resolver. [SemanticPersistenceService](../../../src/anaxigraph/semantic_results.py) contains a large document INSERT and coordinates job completion, scope state, claims, and related persistence. [Lease claiming](../../../src/anaxigraph/semantic_lease_claim.py) carries another part of the same lifecycle.

This is not proof that every function belongs in one file. It is evidence that a caller implementing a semantic lifecycle change can still need knowledge of several tables and transaction conventions. The useful design boundary is ownership of an invariant, not ownership of a few SQL helper functions.

**Suggested refactor:** deepen the existing persistence service around a small set of lifecycle operations. Keep atomic completion atomic. Move the required SQL behind that boundary incrementally; reuse the [existing state machine](../../../src/anaxigraph/semantic_job_state.py). Do not add an ORM, generic repository hierarchy, or new workflow engine.

### 2. The guardrails can reward the wrong transformation

The [module policy](../../../quality/module-size-policy.json) sets a hard 500-line ceiling with no current legacy exceptions. The [maintainability policy](../../../quality/maintainability-policy.json) also has function-length and coupling limits, with some baselined exceptions. At inspection, ten production Python files were at least 475 lines, and the dashboard HTML was exactly 500.

These counts indicate pressure, not defective architecture. The concern is the incentive: a developer may satisfy the gate by spreading one responsibility across additional helpers even when the advisory layer recommends keeping it together.

**Suggested change:** retain warnings and growth scrutiny, but permit narrowly documented exceptions for cohesive modules when task evidence supports them. An exception needs an owner, an explanation of the hidden knowledge, representative tasks, and a reconsideration condition. Do not replace a hard number with an unreviewable “AI says this is fine.”

### 3. Module depth needs concrete evidence, not another universal score

For one selected maintenance task, have the existing assessment identify:

- Which decisions the caller must make, and which the module owns.
- Which invariants are enforced once versus remembered at every call site.
- Which implementation facts escape through parameters, exceptions, sequencing, or documentation.
- How many places require coordinated edits for the proposed change, and why.
- The extra concepts introduced by a proposed extraction, compared with keeping or inlining it.

Treat these as inspectable claims and competing hypotheses. Validate the change through a correct maintenance task; do not collapse them into a “depth = lines / methods” metric.

## Fulfillment of the vision

AnaxiGraph is approaching the right questions for this book, especially in the uncommitted task-centered work. It is not yet demonstrably answering them as well as an experienced designer. The missing evidence is not more generated prose: it is repeated, controlled evidence that users make correct changes with less accidental complexity.

The most valuable next work is to finish and evaluate the existing understandability path, fix confidence semantics, deepen one real invariant-owning boundary, and reconcile the guardrails with those goals. See actions R1, R3, R4, R5, and R9 in the [combined plan](00-synthesis-and-refactoring-plan.md#refactoring-and-improvement-plan).
