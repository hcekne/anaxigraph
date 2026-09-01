# ADR 0005: Tree-sitter for JavaScript and TypeScript facts

- Status: Accepted
- Date: 1 September 2026
- Owners: AnaxiGraph maintainers

## Context

AnaxiGraph recognizes JavaScript, JSX, TypeScript, and TSX today, but the built-in adapter uses
regular expressions and token heuristics. That is enough to inventory simple imports and named
functions, but it is not a trustworthy foundation for modern syntax, partial files, decorators,
re-exports, CommonJS, JSX, or TypeScript contracts. Extension recognition is not language support.

Phase 11 requires one parser-backed implementation behind the existing analyzer IR. The parser
must not execute the target repository or require its package manager, compiler configuration, or
Node installation. Parser facts, repository-wide resolution, and semantic interpretation must
remain separate evidence layers.

The candidates were:

1. keep or expand the regular-expression adapter;
2. invoke the TypeScript compiler, Babel, or another Node subprocess;
3. embed a native parser such as SWC through another language runtime; or
4. use Tree-sitter's Python binding with the official JavaScript and TypeScript grammars.

The first option cannot meet the syntax and recovery contract. The second couples a read-only scan
to a target toolchain and makes first-run/container packaging materially heavier. The third adds a
second runtime and adapter surface without a demonstrated advantage for static architectural facts.

## Decision

Use the official Tree-sitter Python binding and official language wheels, pinned exactly:

| Distribution | Pin | Purpose |
|---|---:|---|
| `tree-sitter` | `0.26.0` | Python runtime binding |
| `tree-sitter-javascript` | `0.25.0` | JavaScript and JSX grammar, ABI 15 |
| `tree-sitter-typescript` | `0.23.2` | TypeScript and TSX grammars, ABI 14 |

The pins are direct runtime dependencies, not optional extras. A normal AnaxiGraph installation
therefore has one deterministic analysis path and cannot silently fall back to regex extraction
when a parser wheel is absent. The JavaScript and TypeScript adapters have separate capability
identities even though they share traversal utilities; TypeScript syntax support must not inflate a
JavaScript fact claim.

The parser produces syntax facts only. It does not run `tsc`, read compiler output, execute package
scripts, resolve runtime dispatch, or claim type-checker certainty. Repository resolution consumes
unresolved parser references afterward and retains resolved, ambiguous, unresolved, external, and
dynamic outcomes with provenance.

## Feasibility evidence

The retained `parser-selection-v1` benchmark covers browser JSX, Node CommonJS, monorepo-style ESM,
TypeScript decorators and generics, TSX, and a deliberately incomplete TypeScript file. On the
recorded Linux x86-64 / Python 3.11 runner, all valid cases parsed without errors, the incomplete
case returned a usable `program` tree with an explicit error, and a 955,000-byte TypeScript sample
parsed in a median 134 ms. Small cases had medians between 0.010 and 0.023 ms. These measurements
select the parser; they are not universal machine-speed promises.

AnaxiGraph already refuses files above the configured `max_file_bytes` limit, which defaults to
2,000,000 bytes. Parsing is sequential behind the repository scan write authority, so parsers do
not cross threads. A parse with recovery returns partial structural facts plus diagnostics. An
unrecoverable adapter exception returns `parse_error`; it never produces high-confidence lexical
facts under another implementation identity.

## Packaging and platforms

The binding and official grammars are MIT licensed. Their project metadata and license files are
captured by the release dependency inventory; the release SBOM and container SBOM must also contain
them before Phase 11 closes.

The selected versions publish pre-built wheels for the release-gated Linux x86-64 and macOS
Python 3.11/3.12 paths. Linux ARM64 wheels also exist for the binding and grammars used by the
multi-architecture container. Native Windows remains outside AnaxiGraph's supported platform
matrix. A source build is not treated as a supported substitute on a machine without a compiler.

Release tests install the built AnaxiGraph wheel and source distribution into clean environments,
load all four grammars, and scan representative files. The container gate builds both Linux
architectures and performs the same parser smoke contract.

## Security and update policy

- Exact pins change only through a reviewed dependency update.
- An update must run the parser benchmark, malformed-input fixtures, full scanner/history suite,
  clean wheel/sdist installs, license inventory, and both container architectures.
- A grammar change increments the owning analyzer version and invalidates only facts produced by
  that analyzer. An IR meaning change requires a separate IR-version decision.
- Security advisories in the binding or grammar repositories are reviewed as release blockers.
- Parser input is repository source already bounded by discovery policy. No query strings, target
  build configuration, native plugins, or downloaded grammars are accepted at runtime.

## Consequences

- JavaScript and TypeScript can become genuinely parser-backed without creating another graph or
  persistence model.
- Installation gains three compiled-wheel dependencies and must test their platform availability.
- JSX and TypeScript recovery become structural evidence rather than regex guesswork.
- Type-checker resolution, framework runtime wiring, generated modules, and data flow remain explicit
  blind spots rather than inferred facts.
- The old regex adapter must be deleted after fixture parity; keeping it as a hidden fallback would
  violate this decision.

## Primary references

- [Tree-sitter](https://github.com/tree-sitter/tree-sitter)
- [Python binding](https://github.com/tree-sitter/py-tree-sitter)
- [JavaScript grammar](https://github.com/tree-sitter/tree-sitter-javascript)
- [TypeScript grammar](https://github.com/tree-sitter/tree-sitter-typescript)
