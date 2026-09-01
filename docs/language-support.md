# Language support and evidence depth

AnaxiGraph reports what each analyzer can actually establish. Recognizing an extension means a file
can be inventoried; it does not mean symbols, types, calls, or dependency targets are understood.
Every stored file fact carries the analyzer name, version, capability fingerprint, and parse status
that produced it.

## Phase 11 capability contract

| Evidence | Python | JavaScript / JSX | TypeScript / TSX | Other recognized formats |
|---|---|---|---|---|
| Syntax implementation | Python AST | Tree-sitter JavaScript | Tree-sitter TypeScript / TSX | Bounded text heuristics |
| Module identity | Deep | Deep | Deep | Deep path identity only |
| Imports and re-exports | Deep syntax | Structural syntax | Structural syntax, including type-only forms | Unavailable |
| CommonJS references | Not applicable | Structural syntax | Structural syntax where accepted | Unavailable |
| Functions, methods, classes | Deep | Structural | Structural | Unavailable |
| Interfaces, aliases, enums, namespaces | Not applicable | Unavailable | Structural syntax | Unavailable |
| Signatures and source spans | Deep | Structural | Structural | Unavailable |
| Calls | Selected imported roots | Selected imported roots | Selected imported roots | Unavailable |
| Decorators and annotations | Structural | Unavailable unless valid JavaScript syntax | Structural syntax | Unavailable |
| Complexity and control flow | AST structural | Syntax structural | Syntax structural | Heuristic |
| Repository target resolution | Separate resolver with explicit provenance | Same | Same | Only explicit configuration references |
| Compiler/type-checker certainty | Not claimed | Not applicable | Not claimed | Not claimed |
| Runtime dispatch and dynamic wiring | Not claimed | Not claimed | Not claimed | Not claimed |
| Data flow and dead-code proof | Not claimed | Not claimed | Not claimed | Not claimed |

The JavaScript/TypeScript rows are the binding implementation contract in current source builds.
Published `0.3.0` predates this adapter and still reports its JavaScript-family facts as lexical; a
future version bump will carry the parser-backed implementation through the immutable release path.
The dashboard and agent APIs always use the capability record stored with a snapshot, so an old
lexical map does not become “structural” merely because a newer AnaxiGraph executable reads it.

## Precision rules

- A literal `import()` or `require()` target is a syntax fact. A computed target is recorded as
  dynamic and unresolved; AnaxiGraph does not guess the resulting module.
- A TypeScript annotation, interface, generic, or decorator is a syntax fact. It is not proof that
  `tsc` accepts the project or that a type resolves to a particular declaration.
- A selected call edge means source syntax invoked a name rooted in an imported binding. It is not a
  complete call graph and does not model runtime dispatch.
- Parse recovery may preserve unaffected declarations and references. Diagnostics remain attached,
  confidence is reduced where recovery intersects evidence, and missing evidence is never treated
  as proof of absence.
- An internal-looking path may resolve uniquely, ambiguously, or not at all. Bare package imports
  remain external unless repository configuration or workspace evidence identifies an internal
  target.

## Updating support claims

A capability changes only with executable conformance fixtures, an analyzer-version change, cache
invalidation, and an update to this matrix. Adding another suffix to language detection is not a
capability change. New parser families remain demand-led after JavaScript and TypeScript; language
count is not a product metric.
