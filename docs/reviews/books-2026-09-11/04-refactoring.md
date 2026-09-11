# AnaxiGraph through Fowler's Refactoring

11 September 2026 · Book: *Refactoring: Improving the Design of Existing Code*, Martin Fowler, with contributions including Kent Beck, second edition, 2018.

## Verdict

AnaxiGraph is considerably better equipped to **suggest a structural improvement** than to establish that carrying it out **preserved observable behavior**.

It already has before/after architecture reassessment, decomposition advice, compatibility considerations, counterevidence, and verification suggestions. Those should be credited. The missing step is a precise connection between a proposed transformation, the behavior it must preserve, and the verification actually observed.

This is an analysis of the inspected working tree, not an implementation or a new test run. [Scope and evidence](00-synthesis-and-refactoring-plan.md#scope-and-evidence).

## Analysis of the recommendation

This is the strongest recommendation for turning architectural insight into controlled change. The second edition broadens the treatment beyond object-centric examples, and its catalog includes inverse transformations: extraction is not inherently better than inlining. [Fowler's account of the second-edition changes](https://martinfowler.com/articles/refactoring-2nd-changes.html).

For this audit, “refactoring” means structural change intended to preserve observable behavior. Fixing the opportunity/confidence bug is therefore a bug fix, not merely a refactor. Adding context-aware domain definitions is a capability change. Moving existing persistence behind a better boundary can be a refactor if the lifecycle behavior remains the same.

These distinctions matter for AnaxiGraph: it should not make “behavior-preserving” sound like a property conferred by the wording of a recommendation.

## Chapter and topic map

The table follows the **second edition's twelve chapters**, using concise topic labels. The edition-correct publisher listing was checked; a different print-product listing exposed an older contents structure and was not used for this map. [Second-edition contents, ISBN 9780134757698](https://www.informit.com/store/refactoring-improving-the-design-of-existing-code-9780134757698).

| Chapter / topic | Book's focus, briefly | Assessment of AnaxiGraph |
| --- | --- | --- |
| 1. Worked example | Restructure incrementally around preserved behavior. | Partial: decomposition provides steps and preserved contracts. It does not show that each proposed intermediate state was checked. |
| 2. Principles | Separate restructuring from feature changes. | Gap: advice can say “behavior-preserving” without a structured distinction between an intended semantic change and a mechanical move. |
| 3. Design smells | Investigate symptoms without mechanical prescriptions. | Positive: structural findings can be moderated by semantic evidence and no-change advice. Size gates still risk turning a symptom into a compulsory split. |
| 4. Tests | Protect behavior, including boundary cases. | Partial: likely tests and verification guidance exist. A suggested test is not a test result, and a passing structural scan is not a behavioral oracle. |
| 5. Catalog use | Connect motivation, mechanics, and examples. | Partial: pattern cards cover desired designs. They are not a substitute for a bounded transformation recipe and its preconditions. |
| 6. Initial transformations | Extract, inline, rename, regroup, and stage. | Partial: split/consolidate advice exists. First-class inverse choices and small ordered transformations need more consistent representation. |
| 7. Encapsulation | Hide representations and unnecessary delegation. | Concrete opportunity: semantic persistence still leaks connections and SQL conventions across the application boundary. |
| 8. Moving behavior | Relocate responsibilities and simplify coordination. | Partial: dependency/caller evidence helps identify destinations. It cannot alone prove equivalent side effects or safe initialization order. |
| 9. Data organization | Clarify data meaning and ownership. | Concrete issue: opportunity becomes confidence in one projection. Fix semantics first; then reduce dictionary-level opportunities to confuse them. |
| 10. Conditions | Clarify branching and exceptional cases. | Positive example: the existing job transition table. Do not replace a clear table with a class hierarchy simply to instantiate a named pattern. |
| 11. Interfaces | Improve APIs while controlling obligations. | Partial: Charter contracts and fresh-eyes compatibility fields help. Verification must include actual consumers, error behavior, and versioned payloads where relevant. |
| 12. Inheritance | Restructure hierarchies or replace them. | Partial vocabulary coverage: related GoF cards exist. AnaxiGraph's own prominent problems concern lifecycle ownership and projections, not a demonstrated need for more inheritance. |

The [author's online catalog](https://refactoring.com/catalog/) is the appropriate reference for individual transformations. AnaxiGraph should associate selected recommendations with a few relevant recipes, not reproduce the entire catalog inside every prompt.

## Existing capabilities that should not be reinvented

### Before/after architecture comparison already exists

[Architecture reassessment](../../../src/anaxigraph/architecture_reassessment.py) selects a compatible saved baseline and combines module, relationship, finding, pattern, and change-coupling evidence into a shared response. It is read-only and does not create a new workflow state machine.

It would be incorrect to list “build before/after reassessment” as an entirely missing capability. The actual gap is what its observed differences establish. Fewer dependency edges or warnings may be useful evidence, but neither proves preserved behavior or improved usability.

In the uncommitted work, [reader-task reassessment](../../../src/anaxigraph/reassessment_semantic_advice.py) requires stable keys and matching task wording before comparing assessments. That is a sensible safeguard against declaring improvement by changing the question.

### Advice already includes caution and sequencing

[Decomposition](../../../src/anaxigraph/agent_decomposition.py) offers responsibility slices, extraction order, caller/dependency context, protected contracts, and tests. [Decision safety](../../../src/anaxigraph/agent_decision_safety.py) supplies verification guidance. The [fresh-eyes review contract](../../../src/anaxigraph/semantic_fresh_eyes_contract.py) includes protected behavior, affected contracts, migration risk, counterevidence, verification, and reversibility.

These are useful ingredients. Much remains free text, however, so downstream consumers cannot reliably distinguish a requirement to verify something from evidence that it was verified.

## What should improve

### 1. Use a bounded change contract

Extend an existing recommendation with an optional structured step containing:

- Whether observable behavior is intended to change.
- The exact owner/symbol and proposed transformation.
- Preconditions and the specific invariants to preserve.
- A small sequence of intermediate changes, including a stop condition.
- Focused verification requirements, tied to those invariants.
- Verification evidence with revision, command/check identity, source, and status: not run, passed, failed, or inconclusive.
- A rollback or compatibility strategy where needed.

This does not require AnaxiGraph to edit or execute untrusted repository code. A coding agent or CI system can perform the checks and supply attributable results; AnaxiGraph should say whether it observed execution, merely received a report, or has no result at all. Preserve this distinction through CLI, API, MCP, and dashboard projections.

### 2. Stop treating identifier resolution as claim verification

[Fresh-eyes grounding](../../../src/anaxigraph/semantic_fresh_eyes_grounding.py) explicitly warns that it checks identifiers, not correctness. That is good. But its status becomes `confirmed` when all cited identifiers resolve. It can also return `already_satisfied` when a proposed named route or symbol already exists.

An existing symbol does not establish that it has the required behavior. The underlying checks are useful; the status vocabulary is too easy to overinterpret.

Separate reference resolution, support for the claim, and behavioral verification. Keep legacy saved reports readable through an adapter. Do not rerun every model job simply to improve how existing evidence is described.

### 3. Make inverse and no-change options first-class

For a proposed extraction, compare keeping the code together and inlining a shallow intermediate layer. For an API wrapper, ask whether it hides a real compatibility decision or simply forwards parameters. For a repeated conditional, compare a clear table/function with polymorphism.

This should operate through existing recommendation and pattern machinery. A separate “refactoring intelligence service” would itself need a strong justification.

### 4. Require correctness before claiming reduced effort

The new [reader benchmark](../../../benchmarks/understandability.py) includes an isolated behavioral check for its shipping-code change task. That is a useful seed. Expand it to real, held-out maintenance tasks, including failures and compatibility edges; do not declare an architecture superior because an agent produced an incorrect answer faster.

Likewise, existing test files are evidence of intended checks, not evidence that a particular reviewed revision passed them. A report must preserve the revision and execution status of any result it uses.

## A concrete sequence for AnaxiGraph itself

These are proposed changes, not completed work:

1. **Characterize the confidence projection.** Add focused examples showing that opportunity, judgment confidence, and execution safety are independent. Include zero and missing confidence. The audit's diagnostic already demonstrates the current mismatch.
2. **Fix that behavior in a small change.** Read the intended confidence field rather than opportunity; represent missing evidence explicitly. Keep this separate from structural movement.
3. **Encapsulate the shared evidence values.** Use small immutable records or well-defined conversion functions only where fields genuinely share meaning. Preserve external JSON compatibility; avoid a universal mega-object for every judgment.
4. **Characterize lifecycle behavior.** Record focused expectations for claim, completion, retry, lease expiry, supersession, and rollback. Use existing relevant tests as the starting point, not a new test framework.
5. **Move lifecycle persistence behind one real boundary.** Transfer one operation at a time into the existing owning service while keeping each transaction intact. Do not simultaneously rename database tables or redesign the workflow.
6. **Compare maintenance tasks before and after.** Can a newcomer locate completion rules and change one correctly with fewer hidden assumptions? If not, the file movement has not established design improvement.

## Fulfillment of the vision

AnaxiGraph has much of the advisory scaffolding, but the verified-transformation story remains incomplete. An expert-like tool must be able to say both “this is a plausible improvement” and “we do not yet have evidence that this change preserves the required behavior.”

Keep architecture observation and code execution distinct. Make their evidence exchange precise. See actions R1–R4, R8, and R10 in the [combined plan](00-synthesis-and-refactoring-plan.md#refactoring-and-improvement-plan).
