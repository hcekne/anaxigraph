# AnaxiGraph — Shared Architecture Intelligence

## Working concept

A standalone, reusable system that continuously maps, interprets, monitors, and explains a software
repository for both people and coding agents.

> **AnaxiGraph is the shared architecture intelligence layer for humans and AI agents. It explains
> what a software system does and how its parts work together, while guiding future changes toward
> a cleaner, more coherent design.**

Its product promise is deliberately small:

1. **Understand the system.** Explain responsibilities, architecture, relationships, and history
   from a whole-program view down to files and named code parts.
2. **Guide the agent.** Ground placement, reuse, pattern, impact, and testing decisions in the
   repository that actually exists.
3. **Keep the architecture coherent.** Refresh the shared model after changes and surface new
   sprawl, duplication, misplaced responsibilities, weak boundaries, and possible dead code.

Deterministic analysis, semantic model work, Git history, imported coverage, rules, metrics, the
dashboard, and AnaxiMCP support those three promises. They are implementation capabilities, not
independent products.

---

# 1. Recommendation: build this as its own repository

This should **not be baked directly into MaxOS**.

The better architecture is:

```text
codebase-intelligence/
    analyzer
    graph builder
    database
    architecture evaluator
    history engine
    dashboard
    API / MCP server
    CLI

MaxOS/
    consumes codebase-intelligence

Other app/
    consumes codebase-intelligence

Another repo/
    consumes codebase-intelligence
```

MaxOS should be the first serious use case, not the boundary of the product.

This matters because virtually every sufficiently large application develops the same problems:

- nobody has a complete mental model of the repository
- AI agents repeatedly rediscover the same architecture
- modules become more tightly coupled over time
- duplicated abstractions appear
- dead code accumulates
- architectural rules drift
- tests cover files but not necessarily important interactions
- agents working in parallel can unexpectedly affect the same shared components
- engineers struggle to understand the impact radius of a change
- documentation becomes stale relative to actual code

A reusable intelligence layer can address all of these.

---

# 2. Product positioning

This is not just a code graph.

The concise positioning is:

> **Understand the system. Guide the agent. Keep the architecture coherent.**

One living AnaxiIndex must let a person and an AI agent answer the same questions:

- what your codebase is
- what the software does for its users
- why each part exists
- what depends on what
- how the architecture is evolving
- where complexity is increasing
- where architecture is drifting
- where tests are weak
- which code may be dead
- where refactoring is becoming justified
- what a coding agent should and should not touch

The graph, dashboard, semantic queue, history importer, REST API, CLI, and MCP tools are delivery
mechanisms. The product is the shared understanding and the better architectural decision it
enables. A proposed feature that does not improve one of those decisions does not belong in the
core product.

---

# 3. Do not rebuild the extraction layer unnecessarily

A tool such as Graphify can provide much of the underlying static and semantic graph extraction.

Potential responsibilities of an extractor include:

- parsing source files
- identifying files, classes, functions and symbols
- identifying imports
- identifying function calls
- identifying class relationships
- generating dependency edges
- extracting documentation
- grouping related areas of the codebase
- producing machine-readable graph output

The AnaxiGraph analysis layer should sit **above** this.

Conceptually:

```text
Git repository
      |
      v
Static extractors / Graphify / Tree-sitter
      |
      v
AnaxiIndex (Repository Intelligence Store)
      |
      +----------------------+
      |                      |
      v                      v
Deterministic analysis     LLM analysis
      |                      |
      +----------+-----------+
                 |
                 v
        Architecture evaluator
                 |
       +---------+---------+
       |                   |
       v                   v
   Dashboard           Agent API / MCP
```

Graphify or another parser should be treated as a replaceable adapter rather than a core dependency that leaks throughout the system.

---

# 4. Keep the intelligence system isolated from the target repository

A major design principle should be:

> **The tool analysing complexity must not materially increase the complexity of the system it analyses.**

The analyzer should therefore run externally.

For example:

```text
docker compose run anaxigraph scan /repo
```

or:

```bash
anaxigraph scan .
```

or:

```bash
anaxigraph watch .
```

The target repository should require little or no code modification.

At most, the target repository might contain a small configuration file:

```yaml
# .anaxigraph.yml

project:
  name: MaxOS

architecture:
  policy: docs/architecture/coding-patterns.md

groups:
  frontend:
    paths:
      - frontend/**
  backend:
    paths:
      - backend/**

ignore:
  - node_modules/**
  - dist/**
  - .next/**
```

That is substantially preferable to embedding analysis logic in MaxOS itself.

---

# 5. Repository structure

A possible repository structure:

```text
codebase-intelligence/
│
├── cli/
│   └── commands for scan, watch, history, serve
│
├── analyzer/
│   ├── hashing
│   ├── language adapters
│   ├── static analysis
│   ├── metrics
│   └── graph extraction adapters
│
├── semantic/
│   ├── module summarisation
│   ├── architecture classification
│   ├── input/output inference
│   └── refactoring analysis
│
├── architecture/
│   ├── rules engine
│   ├── drift detection
│   ├── complexity analysis
│   └── recommendation engine
│
├── history/
│   ├── git reader
│   ├── snapshots
│   └── temporal graph analysis
│
├── coverage/
│   ├── pytest adapter
│   ├── jest adapter
│   ├── vitest adapter
│   └── coverage graph
│
├── storage/
│   ├── models
│   ├── migrations
│   └── repositories
│
├── api/
│   ├── REST API
│   └── MCP server
│
├── dashboard/
│   └── interactive graph + reports
│
├── docs/
│   ├── architecture.md
│   ├── data-model.md
│   └── plugin-system.md
│
└── tests/
```

---

# 6. Database model

The database should not simply contain one mutable row for every file.

The important distinction is between:

- repository
- snapshot
- artifact
- artifact version
- symbol
- relationship
- group
- metric
- coverage measurement
- finding
- analysis run

A possible high-level schema:

```text
repositories
snapshots
artifacts
artifact_versions
symbols
relationships
groups
group_memberships
metrics
coverage
findings
analysis_runs
architecture_rules
```

---

## 6.1 Repository

```text
repository_id
name
path
remote_url
default_branch
created_at
```

---

## 6.2 Snapshot

A snapshot represents the repository at a particular commit.

```text
snapshot_id
repository_id
commit_sha
parent_commit_sha
branch
commit_timestamp
analysis_timestamp
```

This makes historical architecture analysis possible.

---

## 6.3 Artifact

An artifact is the persistent identity of something such as a file or module.

```text
artifact_id
repository_id
canonical_path
artifact_type
first_seen_commit
deleted_commit
```

---

## 6.4 Artifact version

An artifact can have many versions across repository history.

```text
artifact_version_id
artifact_id
snapshot_id

path
language
runtime
architectural_group

raw_hash
structural_hash

lines_of_code
comment_lines
complexity

summary
responsibilities
inputs
outputs
side_effects
public_interfaces

first_seen_at
last_changed_at
```

---

## 6.5 Symbols

Files are useful, but eventually the system should understand objects below file level.

Examples:

```text
function
class
React component
API endpoint
database model
event handler
workflow
service
interface
protocol
```

A symbol table could contain:

```text
symbol_id
artifact_version_id
symbol_type
name
qualified_name
start_line
end_line
signature
summary
```

---

# 7. Relationships should be first-class

Relationships are arguably more important than files.

Examples:

```text
A --imports--> B
A --calls--> B
A --implements--> B
A --extends--> B
A --reads_from--> database
A --writes_to--> database
A --publishes--> event
A --subscribes_to--> event
A --calls_api--> service
test_X --covers--> A
```

A relationship might store:

```text
relationship_id
snapshot_id

source_id
target_id

relationship_type

source
confidence
evidence

weight
```

The `source` field is critical.

Possible values:

```text
ast
git
coverage
runtime
configuration
llm
manual
```

This separates observed facts from inferred relationships.

---

# 8. Deterministic facts and LLM inference must remain separate

The system should never blur:

> "The parser detected this dependency."

with:

> "An LLM believes these modules form one conceptual capability."

Those are different classes of knowledge.

For every semantic claim, preserve:

```text
source
model
prompt_version
timestamp
confidence
supporting_evidence
```

This allows findings to be challenged, re-evaluated, and regenerated later.

---

# 9. Hashing strategy

The instinct to avoid re-analysing unchanged code is correct.

However, simply stripping whitespace before hashing is unsafe.

Whitespace can be semantically meaningful, particularly in languages such as Python, and whitespace inside strings obviously cannot be discarded.

Use at least two fingerprints.

---

## 9.1 Raw hash

A byte-level content hash.

Purpose:

> Has the file changed at all?

Git blob hashes may already provide most of this information.

---

## 9.2 Structural hash

Generate a normalised representation from the parsed syntax tree.

Purpose:

> Has executable code structure materially changed?

Examples of things that may leave the structural fingerprint unchanged:

- formatting
- indentation changes that are non-semantic in the language
- certain comments
- stylistic changes

The exact behaviour should be language-aware.

---

## 9.3 Analysis decision tree

```text
raw hash unchanged
    -> do nothing

raw hash changed
structural hash unchanged
    -> metadata/documentation refresh only

structural hash changed
    -> deterministic analysis

meaningful structural change
    -> semantic LLM analysis

major dependency change
    -> architecture analysis
```

The goal should be:

> **No unnecessary LLM calls.**

Most repository monitoring should be deterministic and cheap.

---

# 10. Rust is probably unnecessary initially

A high-performance hashing/scanning service written in Rust may eventually be useful.

It should not be the starting point.

Git, Tree-sitter and ordinary compiled parsing libraries are likely to scan a normal application repository extremely quickly.

Start with the simplest implementation.

Profile it.

Only create a Rust component if scanning performance becomes a demonstrated constraint.

This is important because the project exists partly to fight complexity.

Its own architecture should demonstrate the same discipline.

---

# 11. Hierarchical graph model

The graph should work at multiple levels.

Rather than maintaining separate diagrams, the same underlying graph should be aggregated differently.

---

## Level 0 — Runtime / deployment

Examples:

```text
Browser
Frontend container
Backend API
Worker
Scheduler
Database
Object storage
External services
```

---

## Level 1 — Product capability / domain

For MaxOS, examples might include:

```text
Workbench
Workflow Builder
Agent Runtime
Integrations
Authentication
Knowledge / Files
Administration
Search
Observability
```

---

## Level 2 — Subsystem / package

Examples:

```text
workflow-engine
gmail-connector
calendar-connector
file-service
agent-router
```

---

## Level 3 — File / module

The repository's source files.

---

## Level 4 — Symbol

Examples:

```text
class
function
method
React component
endpoint
event
database model
```

---

# 12. Declared architecture vs inferred architecture

This could become one of the most valuable features.

Store two classifications.

```text
declared_group
inferred_group
```

The declared group represents what the architecture documentation says should exist.

The inferred group is derived from dependency patterns, clustering and semantic similarity.

The difference between the two represents **architecture drift**.

For example:

```text
Declared:
Workbench belongs to Presentation / Application

Observed:
Workbench has direct dependencies on
5 integration implementations
2 persistence adapters
1 authentication implementation
```

The tool can flag:

> The Workbench boundary appears to be absorbing infrastructure responsibilities.

This is more useful than simply saying that two files are connected.

---

# 13. Graph visualisation

The visualisation should keep node positions relatively stable while allowing different analytical overlays.

Node size could represent:

```text
lines of code
complexity
change frequency
fan-in
fan-out
```

Edge width could represent:

```text
number of calls
coupling strength
runtime frequency
change correlation
```

---

# 14. Graph overlays

Rather than encoding every meaning into one permanent colour scheme, provide switchable views.

---

## Architecture view

Colour by:

```text
frontend
backend
domain
application
infrastructure
integration
database
```

---

## Coupling view

Highlight:

```text
fan-in
fan-out
centrality
cycles
highly connected modules
unexpected cross-boundary dependencies
```

---

## Test coverage view

Show:

```text
line coverage
branch coverage
function coverage
integration coverage
relationship coverage
```

---

## Complexity view

Combine:

```text
LOC
cyclomatic complexity
number of dependencies
number of responsibilities
churn
```

---

## Change view

Show:

```text
recently changed modules
change frequency
number of contributors
change hotspots
```

---

## Dead-code view

Fade or mark modules that appear unreachable or unused.

---

## Agent safety view

Show:

```text
current branch ownership
files being changed by another agent
shared dependencies
collision risk
high-risk common modules
```

---

## Architecture-drift view

Compare the actual graph with declared architecture boundaries.

---

# 15. Historical graph: the visual story of the codebase

Every analyzed commit can become a graph snapshot.

The dashboard can provide a timeline:

```text
Commit 100
Commit 500
Commit 1,000
v0.5
v1.0
Today
```

Moving through the timeline would show:

- modules appearing
- modules disappearing
- capabilities splitting
- capabilities merging
- connections becoming denser
- dependency cycles appearing
- abstractions being introduced
- test coverage improving or degrading
- complexity migrating through the architecture

This turns the graph into a **visual biography of the software**.

For a founder or builder, this is effectively:

> **The story of your baby growing up.**

That is emotionally compelling as well as technically useful.

---

# 16. Architectural metrics over time

Useful repository-level metrics could include:

```text
total LOC
artifact count
symbol count
dependency count
average degree
maximum degree
cycle count
average complexity
high-complexity modules
coverage
architectural violations
dead-code candidates
duplication
cross-domain dependencies
```

The important part is not today's value.

The valuable question is:

> Is architectural entropy increasing or decreasing?

The dashboard could therefore contain an **Architecture Health** or **Entropy** trend.

This should not be reduced prematurely to one arbitrary score, but eventually a composite indicator may be useful.

---

# 17. Nightly architecture review

The expensive semantic review should run periodically rather than on every file save.

A nightly process could:

1. identify changed files
2. identify changed symbols
3. expand to neighbouring graph nodes
4. recompute deterministic metrics
5. evaluate applicable architecture rules
6. inspect new patterns and duplication
7. analyse test coverage
8. identify likely dead code
9. inspect architecture drift
10. generate proposed improvements

Examples of findings:

> Three new provider implementations now expose almost identical lifecycle methods. A common protocol or adapter boundary may now be justified.

> Workbench now directly imports five integration implementations. Consider introducing an application-level interface.

> This module has grown from 180 to 510 LOC over six weeks and now contains four distinct responsibilities.

> These files have no detected static references, runtime registrations or test coverage and have not changed for 90 days. They are possible dead-code candidates.

> Test coverage for WorkflowRunner is 91%, but only 43% of its outgoing integration relationships are exercised by tests.

---

# 18. Findings must have lifecycle state

The nightly LLM should not repeatedly produce the same recommendation.

Store findings.

Possible states:

```text
new
acknowledged
accepted
dismissed
planned
resolved
regressed
```

A finding could contain:

```text
finding_id
snapshot_id
finding_type
severity
confidence
summary
explanation
affected_artifacts
evidence
recommended_action
status
first_detected_at
last_detected_at
resolved_at
```

This turns architecture review into a real workflow rather than disposable AI commentary.

---

# 19. Test coverage should exist on both nodes and edges

Traditional coverage concentrates on files and functions.

The graph creates another useful unit:

> **Has the interaction between these two modules been tested?**

Example:

```text
WorkflowRunner
      |
      +--> OpenAIAdapter
      +--> GmailAdapter
      +--> CalendarAdapter
      +--> StorageAdapter
```

WorkflowRunner itself may have excellent unit coverage.

But perhaps only:

```text
WorkflowRunner -> OpenAIAdapter
WorkflowRunner -> StorageAdapter
```

have meaningful integration coverage.

The graph can therefore highlight untested **relationships**, not only untested lines.

That is particularly valuable for agentic applications where many failures happen at system boundaries.

---

# 20. Coding-pattern policy should become canonical

Do not keep architecture principles buried inside:

```text
copilot-instructions.md
CLAUDE.md
AGENTS.md
```

Those files should reference one canonical policy.

For example:

```text
docs/architecture/coding-patterns.md
```

or:

```text
architecture-policy.yml
```

The human-readable Markdown document contains the rationale.

A machine-readable policy contains rules the architecture analyser can evaluate deterministically.

---

# 21. Hybrid functional and object-oriented design

MaxOS is not purely functional and should not pretend to be.

Nor should everything automatically become a class.

The architecture rules should explain when each style is appropriate.

---

## Prefer pure functions when

The code:

- transforms data
- validates input
- applies deterministic business rules
- maps one representation to another
- calculates something
- has no meaningful identity or lifecycle
- can avoid mutable state

---

## Prefer classes when

The concept has:

- identity
- lifecycle
- state
- invariants
- multiple cohesive behaviours
- a meaningful interface that has multiple implementations

---

## Prefer protocols/interfaces for

External boundaries such as:

```text
LLM providers
email providers
calendar providers
storage
databases
search systems
payments
external APIs
```

---

## Prefer adapters for

Concrete integrations:

```text
OpenAIAdapter
AnthropicAdapter
GmailAdapter
GoogleCalendarAdapter
PostgresRepository
```

---

## Prefer composition over inheritance

Inheritance should generally not be the primary reuse mechanism.

---

## Avoid patterns merely because they are patterns

A design pattern should only be introduced when it makes the code easier to understand or change.

The architecture analyser should therefore ask:

> Does this abstraction reduce complexity?

rather than:

> Could a design pattern be applied here?

---

# 22. Possible initial coding standards

The canonical policy could include guidelines such as:

- keep functions short and understandable
- prefer single responsibility
- prefer pure functions where practical
- keep modules cohesive
- avoid very large modules
- use explicit interfaces at system boundaries
- inject external dependencies
- maintain clear domain/application/infrastructure separation
- use typed Python where practical
- avoid hidden global state
- avoid circular dependencies
- avoid direct infrastructure dependencies from presentation code
- keep changes narrow
- avoid surprise refactors
- require tests around changed behaviour
- keep agents inside the smallest useful change surface

Thresholds should be guidelines rather than absolute rules.

For example:

```text
Function > 25 logical lines
    -> inspection signal, not automatic violation

Module > 300 LOC
    -> ask whether multiple responsibilities have emerged

High fan-out
    -> inspect orchestration responsibility

High fan-in
    -> identify stability-critical module
```

---

# 23. The agent-facing layer may be the most important feature

The human dashboard is useful.

But the intelligence layer can fundamentally improve AI-assisted development.

Before an agent changes a feature, request a work envelope.

Example:

```text
Target capability:
Workbench

Primary files:
14

Primary LOC:
3,821

Direct internal dependencies:
9

External dependencies:
4

Likely affected files:
7

Protected boundaries:
auth
agent-runtime
persistence

Relevant tests:
38

Files modified by another active branch:
workflow-shared/types.ts

Collision risk:
LOW

Applicable architecture rules:
6

Recommended context:
11 files
```

An agent does not need to inspect the entire repository.

It receives the smallest useful subgraph.

---

# 24. Agent work envelopes

Possible API:

```http
POST /agent-scope
```

Input:

```json
{
  "goal": "Add saved prompts to the Workbench",
  "branch": "feature/workbench-saved-prompts"
}
```

Output:

```json
{
  "primary_files": [],
  "related_files": [],
  "protected_files": [],
  "tests": [],
  "interfaces": [],
  "architecture_rules": [],
  "known_findings": [],
  "active_branch_conflicts": [],
  "risk": "low"
}
```

This gives AI agents architectural context without forcing them to repeatedly rediscover the repository.

---

# 25. Parallel agent development

This is especially useful when multiple coding agents are working simultaneously.

Example:

```text
Agent A
Feature: Workbench

Agent B
Feature: Workflow Builder

Agent C
Feature: Gmail integration
```

The intelligence layer can identify:

```text
shared dependencies
common interfaces
likely collision points
files changed by multiple branches
shared database migrations
shared type definitions
```

It can then warn:

> Agent A and Agent B are both likely to modify `shared/workflow-types.ts`.

or:

> These work envelopes are nearly disjoint. Parallel implementation risk is low.

This could become a major capability for AI-native software development.

---

# 26. Architecture impact analysis

Before making a proposed change, an agent could ask:

```text
What is the likely impact of changing WorkflowDefinition?
```

The system would traverse the dependency graph and respond with:

```text
Direct dependants: 12
Second-order dependants: 37
Critical paths affected: 3
Tests relevant: 54
Database migrations possibly affected: 1
Active feature branches affected: 2
Risk: HIGH
```

This is substantially more useful than grep alone.

---

# 27. Dead-code detection

Dead-code analysis should combine multiple signals.

Static analysis alone is insufficient.

Signals might include:

```text
no static references
no route registration
no dependency injection registration
no event registration
no runtime observation
no test references
no recent changes
no configuration references
LLM semantic analysis
```

The result should be probabilistic.

For example:

```text
Possible dead code
Confidence: 0.91

Reasons:
- no incoming static relationships
- no dynamic registration detected
- no test references
- unchanged for 147 days
```

The system should recommend deletion, never silently delete.

---

# 28. Complexity reduction should be a core objective

The system should explicitly optimise for:

> **Keeping entropy in check as the application grows.**

Potential signals:

```text
module growth
fan-out growth
fan-in growth
cycle creation
duplicate abstractions
cross-boundary imports
public API growth
number of concepts per module
number of responsibilities
change coupling
test complexity
```

A nightly report might say:

```text
Architecture trend this week

Improved:
- 2 dependency cycles removed
- workflow engine split into clearer components
- integration coverage +8%

Worsened:
- Workbench fan-out increased 9 -> 14
- 3 new infrastructure imports entered UI layer
- 2 modules exceeded complexity threshold

Recommended next action:
Create an application-level connector interface before adding
additional provider integrations.
```

---

# 29. Dashboard design

A dedicated Codebase dashboard could have several primary areas.

---

## Overview

```text
Files
LOC
Languages
Modules
Dependencies
Tests
Coverage
Architecture findings
Dead-code candidates
Recent changes
```

---

## Graph

Interactive hierarchical graph with overlays.

---

## Architecture

Show:

```text
declared architecture
inferred architecture
drift
violations
cycles
coupling
```

---

## History

Timeline and animated graph evolution.

---

## Testing

Coverage by:

```text
capability
module
file
symbol
relationship
```

---

## Findings

Architecture and refactoring recommendations.

---

## Agents

Show:

```text
active branches
active agents
work envelopes
collision risks
shared dependencies
```

---

# 30. Packaging

The tool should be easy to run against any repository.

Possible installation models:

```bash
pip install anaxigraph
```

or:

```bash
uv tool install anaxigraph
```

or:

```bash
docker run \
  -v $(pwd):/repo \
  anaxigraph scan /repo
```

or:

```bash
npx anaxigraph
```

The implementation language should be chosen based on maintainability and ecosystem rather than marketing.

A Python-first backend may be appropriate because:

- strong AST/static-analysis ecosystem
- easy LLM integration
- good Git tooling
- fast development
- easy API implementation
- easy data analysis

The frontend can remain independent.

---

# 31. Suggested operating modes

## One-off scan

```bash
anaxigraph scan .
```

Build a complete current repository map.

---

## Incremental update

```bash
anaxigraph update .
```

Analyse only changed artifacts.

---

## Watch mode

```bash
anaxigraph watch .
```

Update after changes.

---

## Historical analysis

```bash
anaxigraph history .
```

Build snapshots across selected commits.

---

## Architecture review

```bash
anaxigraph review .
```

Run architecture and complexity analysis.

---

## Serve dashboard

```bash
anaxigraph serve
```

Launch the web interface.

---

## Agent context

```bash
anaxigraph scope \
  --goal "Add saved prompts to Workbench"
```

Return an agent work envelope.

---

# 32. Plugin architecture

The project should support adapters rather than hard-coding one stack.

Potential plugin interfaces:

```text
LanguageAnalyzer
GraphExtractor
CoverageProvider
GitProvider
LLMProvider
ArchitectureRuleProvider
RuntimeTelemetryProvider
```

Examples:

```text
TreeSitterAnalyzer
GraphifyExtractor
PytestCoverageProvider
JestCoverageProvider
GitProvider
OpenAIProvider
AnthropicProvider
```

This allows the project to work across many types of application.

---

# 33. MaxOS integration

MaxOS should consume the package through a narrow interface.

For example:

```text
MaxOS
  |
  +--> AnaxiGraph API
            |
            +--> current repository state
            +--> architecture findings
            +--> work envelopes
            +--> graph data
            +--> history
```

The MaxOS Operator Dashboard can link to the Codebase dashboard or embed selected views.

But the intelligence system should remain independently deployable.

This gives MaxOS all of the benefit without making MaxOS responsible for maintaining the analysis engine.

---

# 34. Why standalone is the better boundary

Making this a separate repository provides several advantages.

## Reuse

Every application can use it.

## Isolation

The tool does not contaminate the architecture it is evaluating.

## Open source

The project has a coherent public identity.

## Independent release cycle

AnaxiGraph can evolve without coupling releases to MaxOS.

## Multiple consumers

Potential consumers include:

```text
MaxOS
other applications
CI/CD
GitHub Actions
coding agents
IDE extensions
MCP clients
engineering dashboards
```

## Cleaner architecture

MaxOS remains focused on MaxOS.

The intelligence platform remains focused on understanding software systems.

---

# 35. MVP

The first release should be deliberately narrow.

A good MVP would:

1. scan a repository
2. catalogue every source file
3. calculate hashes
4. calculate LOC
5. extract imports/dependencies
6. generate semantic summaries
7. classify frontend/backend/subsystem
8. persist everything
9. render a graph
10. show file details
11. update only changed files
12. show Git change history
13. generate a basic architecture review

Do not start with:

- runtime tracing
- every programming language
- complex distributed services
- Rust optimisation
- universal IDE integration
- sophisticated AI orchestration
- a vector database
- automatic code mutation

---

# 36. MVP data model

The initial version may only need:

```text
repositories
snapshots
files
file_versions
relationships
groups
findings
analysis_runs
```

This keeps the first implementation tractable.

Symbols, test edges, agent coordination and richer temporal analysis can follow.

---

# 37. Development sequence

## Phase 1 — Repository catalogue

Build:

```text
scan
hash
LOC
language detection
Git metadata
database persistence
```

---

## Phase 2 — Dependency graph

Add:

```text
imports
calls where practical
module relationships
graph output
```

Use Graphify or equivalent where useful.

---

## Phase 3 — Semantic intelligence

Generate:

```text
summary
purpose
responsibilities
inputs
outputs
side effects
architectural group
```

Only run LLM analysis on changed material.

---

## Phase 4 — Dashboard

Build:

```text
repository overview
hierarchical graph
module inspector
search
filters
```

---

## Phase 5 — Architecture policy

Introduce:

```text
canonical coding patterns
machine-readable rules
violations
architecture drift
```

---

## Phase 6 — Testing overlay

Integrate coverage.

---

## Phase 7 — History

Store and render architecture changes over time.

---

## Phase 8 — Agent interface

Add:

```text
MCP
work envelopes
impact analysis
parallel-agent collision analysis
```

---

# 38. Long-term opportunity

The strongest long-term version is not:

> "A prettier dependency graph."

It is:

> **A shared architecture intelligence layer that people can explore and coding agents can act on.**

It lets humans and agents ask:

```text
What does this part of the system do?

Why does it exist?

What is it connected to?

What changed?

Why did it change?

Is complexity increasing?

Where are our weak boundaries?

What code can probably be deleted?

What should we refactor next?

What is safe for this agent to modify?

What other work could this change collide with?

How has the architecture evolved over time?
```

That is broadly useful across software projects.

---

# 39. Core product principles

1. **Standalone first.**
   MaxOS is a consumer, not the container of the product.

2. **Deterministic before probabilistic.**
   Use parsers, Git and tests wherever possible. Use LLMs for interpretation and judgement.

3. **Incremental by default.**
   Never reanalyse unchanged code unnecessarily.

4. **Temporal, not static.**
   Architecture history is a first-class feature.

5. **Graph as a model, not merely a picture.**
   The graph should support analysis, APIs and agents.

6. **Facts and inference remain distinguishable.**

7. **Architecture policy is explicit.**
   The tool should evaluate against declared rules rather than inventing them.

8. **Human approval for refactoring.**

9. **Optimise for simplification.**
   The analyzer itself should remain architecturally boring.

10. **Human- and agent-native.**
    The dashboard and coding-agent interfaces must use the same current architecture model and
    explain the same evidence at the appropriate level of detail.

---

# 40. Concise recommendation

Build this as a separate repository and package.

A working name could be:

```text
codebase-intelligence
architecture-observatory
repo-observatory
codegraph-os
codebase-observer
```

Its architecture should be:

```text
                  +-------------------+
                  |   Any Git Repo    |
                  +---------+---------+
                            |
                            v
                  +-------------------+
                  | Extraction Layer  |
                  | AST / Graphify    |
                  +---------+---------+
                            |
                            v
                  +-------------------+
                  | Intelligence DB   |
                  | temporal history  |
                  +---------+---------+
                            |
            +---------------+---------------+
            |                               |
            v                               v
  +--------------------+          +--------------------+
  | Architecture       |          | Semantic / LLM     |
  | Rules + Metrics    |          | Interpretation     |
  +---------+----------+          +----------+---------+
            |                                |
            +---------------+----------------+
                            |
                    +-------+-------+
                    |               |
                    v               v
              +-----------+   +-------------+
              | Dashboard |   | Agent API   |
              | / Graph   |   | MCP / CLI   |
              +-----------+   +-------------+
```

MaxOS can then simply install or deploy it and say:

```bash
anaxigraph scan /path/to/maxos
```

That gives MaxOS a rich codebase map without coupling the implementation to MaxOS.

If the package proves useful there, it is already architected to analyse every other application you build.
