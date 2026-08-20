# ADR 0001: Internal layers and the analyzer IR

- Status: Accepted
- Date: 20 August 2026
- Owners: AnaxiGraph maintainers

## Context

AnaxiGraph asks other repositories to preserve architectural boundaries, but its own early package
grew around a scanner, a SQLite facade, transport entry points, and language-specific result
shapes. Without an explicit dependency rule, parser details can leak into persistence and transport
code. Without a versioned analyzer contract, the tree-sitter and storage work planned for later
phases could create a second, incompatible representation beside the existing `FileAnalysis`,
`Symbol`, and `Dependency` records.

We also need to distinguish three separate claims:

1. an analyzer extracted a reference from source;
2. the repository resolver uniquely, ambiguously, or unsuccessfully resolved that reference; and
3. a deterministic rule or semantic dossier interpreted the architectural consequence.

Collapsing those claims would make the graph look more certain than its evidence permits.

## Decision 1: enforce inward package dependencies

The package uses these layers. An arrow means “may depend on.”

```text
dashboard client
      ↓
CLI · REST · MCP · background transports
      ↓
application services and use cases
      ↓                    ↓
analysis adapters     index persistence
      ↓                    ↓
     foundation models, contracts, configuration, and identities
```

| Layer | Current responsibilities | May import |
|---|---|---|
| Foundation | provider-neutral records, configuration, IR identity, relationship provenance, glossary and small registries | Foundation |
| Analysis | language adapters, Git/coverage adapters, semantic-provider adapters, deterministic architecture evaluation | Foundation, analysis |
| Persistence | AnaxiIndex storage and read models | Foundation, persistence |
| Application | scan/history orchestration, agent scope, semantic planning/queue use cases, onboarding | Foundation, analysis, persistence, application |
| Transport | CLI, REST, MCP and process entry points | Every inward layer and transport peers |
| Dashboard | packaged static client | Foundation and dashboard peers |

`quality/architecture-policy.json` classifies every current Python module and checks every internal
import. A new unclassified module, cross-layer import, package cycle, or stale exception fails the
quality gate. There is one ratcheted legacy violation:

```text
anaxigraph.architecture → anaxigraph.storage
```

Architecture evaluation currently persists finding lifecycle state directly. Phase 3b will move
that state transition behind an application/index boundary; the exception permits the existing
edge but no additional sibling-layer dependency.

Transport code may compose use cases but may not own SQL, parser logic, or semantic state
transitions. Foundation records may not import FastAPI, MCP, SQLite, or dashboard code. Persistence
and analysis are siblings: neither becomes a shortcut into the other.

## Decision 2: evolve the existing records into `anaxigraph-ir-v1`

The IR is not a new graph or parallel object model. It is version 1 of the records analyzers already
return:

| Contract part | Required facts |
|---|---|
| `ModuleIdentity` | normalized path, language, canonical module name, package name, and resolution aliases |
| `Symbol` | kind, name, qualified name, signature, line/column span, visibility, complexity, and logical size |
| `Dependency` | reference kind, unresolved target text, imported names, source span, evidence, and confidence |
| `FileAnalysis` | structural hash, size/complexity facts, interfaces, symbols, references, exports, parse status, analyzer identity/version, IR version, and resolver context |
| `ResolverContext` | importer/module/package identity, extracted aliases, configured path aliases, and candidate roots |

Reference kinds in v1 are `imports`, `exports`, `calls`, `extends`, and `references`. Parse status is
explicitly `parsed`, `lexical`, `fallback`, or `parse_error`; recognizing a file extension is not a
claim that a full parser handled it. Python AST extraction is the reference implementation.
JavaScript/TypeScript currently declares lexical extraction, and the other recognized text
languages declare fallback extraction unless parsing failed.

Every analyzer has its own version independent of the IR version. A parser bug fix can invalidate
that analyzer's facts without silently redefining the shared contract. The scanner's analysis
version was advanced to 4 when v1 became binding.

`validate_analysis` is language-neutral. It checks identity, version, hashes, parse/error
consistency, spans, visibility, reference vocabulary, evidence, and confidence. The scanner runs
it before accepting newly extracted facts. Conformance fixtures certify all built-in analyzers;
the Python fixture additionally characterizes aliases, exports, calls, and visibility.

## Decision 3: persist facts and resolution outcomes separately

The current schema stores the extra v1 fields in the version row's structured IR metadata so this
contract can land without an unrelated database migration. The compatibility codec round-trips
tuples, symbols, references, analyzer versions, parse status, exports, and resolver inputs when an
unchanged analysis is reused. Phase 1b may normalize these fields, but must preserve v1 semantics
and migration tests.

Resolution combines each file's context with the complete snapshot inventory and configured
aliases. Relationship rows then record one of `resolved_internal`, `ambiguous_internal`,
`unresolved_internal`, or `external`, including candidate paths where relevant. A low-confidence or
unresolved edge remains evidence; it is never silently discarded. Dynamic runtime wiring remains
outside what this static contract can prove.

Semantic dossiers and pattern recommendations are not IR facts. They stay in versioned semantic
tables with provider/model/prompt/confidence/evidence provenance and can be invalidated without
rewriting deterministic extraction.

## Consequences

- New language adapters have one executable conformance target before they can enter AnaxiIndex.
- Later tree-sitter adapters can improve depth without teaching storage or transports a parser's
  node types.
- Contract changes require a new IR version, compatibility policy, fixtures, and analysis-version
  decision; silently changing a field's meaning is prohibited.
- The metadata codec is intentionally transitional. Normalized storage remains Phase 1b work.
- Layer pressure is visible immediately. A legitimate boundary change requires an ADR/policy
  change, not a hidden import or permanent inline suppression.
