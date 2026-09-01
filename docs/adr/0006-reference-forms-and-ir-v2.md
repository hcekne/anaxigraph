# ADR 0006: Explicit reference forms in analyzer IR v2

- Status: Accepted
- Date: 1 September 2026
- Owners: AnaxiGraph maintainers

## Context

The original `anaxigraph-ir-v1` dependency record preserved a reference kind such as `imports` or
`extends`, but did not say how source code expressed the reference. That omission was tolerable for
Python and the former shallow JavaScript analyzer. It is not sufficient for parser-backed
JavaScript and TypeScript: a static import, CommonJS `require`, literal dynamic import, computed
dynamic import, and type-only import have materially different runtime and deletion implications.

Encoding those distinctions only in analyzer-specific metadata would make graph resolution,
semantic prompts, pattern evidence, and dead-code safeguards disagree. Adding the distinction to
the shared dependency record changes the IR contract and therefore requires an explicit version
decision rather than silently redefining v1.

## Decision

Advance the shared analyzer contract to `anaxigraph-ir-v2`. Add the required `reference_form` field
to every dependency with this closed vocabulary:

| Form | Meaning |
|---|---|
| `static` | A normal static language reference |
| `commonjs` | A literal CommonJS `require` reference |
| `dynamic_literal` | A dynamic import whose target is nevertheless a source literal |
| `dynamic_expression` | A computed import or require with no single target written in source |
| `type_only` | A syntax-level TypeScript reference erased from emitted runtime code |

The relationship resolver stores reference forms and resolution provenance separately from the
relationship kind. A computed expression receives the explicit `dynamic` resolution outcome and
is never guessed. Type-only relationships may still resolve to an indexed declaration, but their
form remains available to humans, agents, and later analysis.

Analyzer versions still identify implementation changes within IR v2. JavaScript and TypeScript
have separate analyzer identities. Scanner analysis version 5 invalidates prior extracted facts;
the semantic input identity includes analyzer version and capability fingerprint so a parser or
capability change cannot silently reuse an incompatible dossier.

## Compatibility

Historical v1 facts remain readable. The compatibility decoder supplies `static` only when an old
dependency lacks the additive field, and old snapshots retain their recorded v1 schema identity.
Current analyzers emit only v2. A current scan therefore re-analyzes old facts before treating them
as v2; reading an old snapshot never upgrades its evidence label in place.

## Consequences

- All consumers can distinguish runtime, type-only, and computed references through one contract.
- Dead-code and impact advice can remain conservative in the presence of computed imports.
- Semantic agents receive the same form and resolution provenance shown by the graph.
- Adding another reference form requires a reviewed IR-contract change and conformance fixtures.
