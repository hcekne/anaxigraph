# AnaxiGraph — Capability Brief

> **AnaxiGraph is the shared architecture intelligence layer for humans and AI agents. It explains what a software system does and how its parts work together, while guiding future changes toward a cleaner, more coherent design.**
>
> **Understand the system. Guide the agent. Keep the architecture coherent.**

AI-assisted development adds code faster than a team can absorb it into a coherent design. AnaxiGraph keeps a durable, inspectable understanding of a repository — what it does, how its parts fit, why they exist — so a person exploring the system and an agent changing it work from the same account of it.

**Maturity labels:** **Shipped** (available today) · **Partial** (real, but short of the stated ambition) · **Intended** (roadmap, not delivered) · **Non-goal** (deliberately not being built).

---

## What it is, and is not

**It is** a read-only observer that keeps a durable memory of a repository, reachable from a browser dashboard, the command line, or a connected coding agent — all three returning the same claims, evidence and stated confidence.

**It is not** a code graph drawn for its own sake, an architecture score, another AI diff reviewer, or an autonomous refactoring tool. It never edits, deletes or executes the code it studies.

Three kinds of statement stay visibly apart everywhere: **facts read from the code**, **AI-written interpretation**, and **recommendation**. Where it cannot see something — wiring that exists only at runtime — it says so rather than treating silence as proof.

---

## 1. Understand the system

| Capability | What you get | Maturity |
|---|---|---|
| Repository briefing | Size, language mix, architecture areas, coverage, what deserves attention, what the repository does and where new work generally belongs | Shipped |
| Responsibility map | Named areas → subsystems → files, each file placed exactly once, with the reason those files belong together, supporting and contradicting evidence, and a confidence rating | Shipped |
| Three groupings, compared | The AI-built map, the grouping your team declared, and the one guessed from paths — each labelled by origin, disagreements shown rather than resolved for you | Shipped |
| What one file is for | Its job in the wider system, its responsibilities, extension points and risks, beside counted facts: named parts, what it uses, what uses it, history, coverage, open findings | Shipped |
| Symbol-level navigation | The functions, classes, endpoints and models a file declares; jump from a goal to the matching named parts without loading whole files | Shipped |
| Search that includes meaning | Ask in ordinary words; get files and symbols ranked across paths, names and written purpose — finding code whose *job* matches even when the word never appears | Shipped |
| Relationship trust | Every dependency says whether it resolved to one file, matched several, could not be resolved, or points outside the repository | Shipped |
| Change history as evidence | Which commits touched a file and when; which files repeatedly change together even with no code link between them | Shipped |
| Answer freshness | Every answer says how current it is and what it left out | Shipped |
| Honest depth per language | Deep reading for Python; lighter for JavaScript/TypeScript; heuristic or catalogued elsewhere — each limit travels with the evidence | **Partial** |

## 2. Guide the agent

| Capability | What you get | Maturity |
|---|---|---|
| Goal-scoped briefing | State a goal in a sentence; get likely files, the route from area to symbol, why each file is in scope, extend-or-create guidance, contracts, protected boundaries, focused tests, existing findings, relevant patterns, a reading order and a written-out risk level | Shipped |
| Impact before you touch it | Direct users of a file or symbol, the next ring outward, a count of everything reachable beyond, focused tests, files needing extra care, possible stored-data effects | Shipped |
| Placement guidance | Whether to extend something that exists or create something new, with the local precedents to follow | Shipped |
| Finding → agent handoff | Turn a finding into a goal, files to read, relevant tests, risk level, verification steps and a ready-to-paste prompt | Shipped |
| Budget-aware by construction | Every answer is size-limited and paged, states its true total and what it omitted, and degrades by dropping optional detail while keeping the conclusion | Shipped |
| Works with any standard agent client | One shared workflow package; connection set up in a single command | Shipped |
| Shared post-change consequence | One plain-language account of what a change did, delivered to dashboard and agent together | **Intended** |

## 3. Keep the architecture coherent

| Capability | What you get | Maturity |
|---|---|---|
| Bounded attention queue | At most ~20 items, most useful first, each already qualified — beside a complete record that is never pruned, with true totals always stated | Shipped |
| A finding as an argument | What was seen, why it may matter, when the code is probably fine as it is, the smallest sensible step, and how a later scan will show whether it worked | Shipped |
| Ranking with reasons written out | Why this item is above that one, in sentences | Shipped |
| Lifecycle you drive | Mark reviewed, planned, accepted or not actionable; see when a problem appeared and whether it came back | Shipped |
| Consolidation advice | Merge, split, keep separate or needs review — with "keep these separate" as a first-class outcome and contrary evidence required | Shipped |
| Boundary erosion and drift | A file whose declared home no longer matches its behaviour, and dependencies crossing boundaries the team declared off-limits | Shipped |
| Large-file decomposition map | Up to five proposed responsibility slices with symbols, target homes, contracts to hold stable, a safe extraction order, focused tests — and the evidence against splitting at all | Shipped |
| Design pattern catalog | 128 entries across eight families, including failure modes, each with intent, liabilities, cautions and relationships to other entries | Shipped |
| Pattern evaluation, both directions | Which patterns suit this code, and where a given pattern applies — with presence, fit, opportunity and counter-evidence, plus why code was skipped | Shipped |
| Independent review of its own judgements | A separate pass checks pattern conclusions, looking specifically for needless machinery | Shipped |
| Conservative unused-code candidates | Only when links resolve cleanly, nothing points at it, history shows it untouched, and no entry point was detected — listing checks passed and checks a human must still do | Shipped |
| Your own architecture rules | The project defines what counts as a problem in one reviewable settings file | Shipped |
| Your own pattern catalog, live | Authoring and validating a house catalog works; making the running evaluation use it does not | **Intended** |

## 4. Running it

| Capability | What you get | Maturity |
|---|---|---|
| One-command start | Start it and connect your agent in a single command, with or without containers | Shipped |
| Understanding that persists | Built once, reused across sessions, refreshed incrementally as code changes | Shipped |
| Durable long builds | Start a repository-scale build and walk away — it reports progress, survives interruption, resumes, and can be cancelled | Shipped |
| History on your terms | Sampled by default and adapting to repository size, or every commit, or a time window — running in the background with progress and resume | Shipped |
| Diagnosis | Tell me why the setup isn't working, in terms I can act on | Shipped |
| Backup and restore | Protect and recover what the understanding cost you to build | Shipped |
| Machine-readable output | Scriptable results from every surface | Shipped |
| Several repositories at once | Multiple repositories supported; serving many from one place is explicitly experimental | **Partial** |

---

## Trust guarantees

- **Never writes to your source.** No edits, deletions or execution of analysed code, ever.
- **The agent spends its own tokens.** Written understanding is produced by your connected coding agent under budget, provenance and egress controls. No hosted-model key is accepted by the packaged service.
- **Provenance on every written claim** — which model, when, from what evidence.
- **No evidence is deleted to quiet a screen.** The queue hides; the record keeps.
- **Confidence is stated, not implied.** Uncertainty is a field, not a tone.
- **It holds itself to the same standards** it recommends, and checks itself.

---

## Limits

- **Language depth is the main one.** Python gets full-strength answers. JavaScript/TypeScript get weaker symbol and relationship evidence, so dependency, placement and unused-code answers are correspondingly weaker. Other formats are recognised, not understood.
- **Runtime wiring is a permanent blind spot** — framework registration, reflection, config-driven loading, generated code. Disclosed, never guessed at.
- **No composed before/after verdict yet.** You can see findings that resolved, appeared or returned, and compare saved states — but not one answer classifying each effect as introduced, worsened, improved, resolved or pre-existing.
- **Requires a Git working tree**, plus either a recent Python toolchain or a container runtime. Linux x86-64 is release-gated; ARM64, macOS and WSL2 are best effort; native Windows is not supported.
- **Evidence base for the written understanding is narrow** — see the counterweight below.

---

## Intended direction

1. **One shared consequence after each refresh** — dashboard and agent receive the same short account of what a change did, its architectural consequence, the recommendation and its confidence.
2. **One continuous journey** from what the program is for down to a single symbol, keeping the selected concept selected across views, so a newcomer can trace a feature to its code unaided.
3. **A deliberately smaller default surface** — about five task-centred journeys for a person, no more than ten obvious actions for an agent, with operator controls off the normal path. The goal is reliability with everyday agents, not richness for frontier ones.
4. **Your own catalog, running** — house conventions evaluated by the live product.

---

## Deliberate non-goals

Parked, not queued. Each reopens only on concrete evidence it materially improves the core loop.

| Non-goal | Why |
|---|---|
| Broad multi-language parser coverage | Understanding one kind of repository deeply and running reliably beats recognising everything shallowly. A scope decision, not a technical barrier |
| Non-code adapters (schemas, infrastructure, documents) | Multiplies surface while diluting the one thing it is trying to be excellent at |
| Third-party plugin ecosystem | Every extension surface is paid for later in confusion and maintenance |
| Rich media — images, PDFs, audio, video | Not on the path from "understand this repository" to "make this change fit" |
| Health score or hotspot leaderboard | A single number gets optimised, then compared between teams, then measures nothing |
| Automatic fixing, refactoring or deletion | A tool that both raises and closes its own findings has no independent check left |
| Learned-similarity search or a second model | One inspectable model whose claims trace to evidence beats two that can quietly disagree |
| A general architecture-policy language | Fixed rule kinds keep findings explainable and the queue small |
| Extra dashboards, website, demo, promotion | Presentation is not allowed to starve the core loop |

**The admission test.** Anything proposed must state which of the three promises it strengthens, which human or agent decision it makes easier, which existing evidence and surface it reuses, what it removes or replaces, the smallest proof it works, and what new machinery it avoids. Anything that cannot answer all of that is optional.

---

## Why it is good at what it does

**It answers the question before the change, not after it.** Most architecture tooling is an audit of a decision already made. The high-leverage moment is earlier — when an agent is deciding *where this goes*, and an isolated prompt guesses from whatever few files are in context and creates a plausible new file next to the one that should have been extended.

**One understanding, two front doors.** Not a human product and an agent product that interpret the repository differently and then disagree with no way to tell which is stale. Both read the same memory and get the same sentences, evidence and confidence, so a handoff is a continuation rather than a translation.

**Every answer argues against itself.** Consolidation treats "keep these separate" as a real outcome. Decomposition returns "keep it together" as a real answer. Pattern results must carry reasons not to change the code. Putting the case against beside the case for is what lets a person or agent decline deliberately — which is what makes the advice worth reading.

**It refuses the moves that would make it look better and be worse.** No score, no auto-fix, no deleting evidence to calm a screen, no language claim from a file extension, no confident dead-code verdict where wiring is invisible. Each refusal costs convenience. Naming them as refusals is what makes them something to rely on.

**It fits inside an agent's budget by construction.** Every read is bounded, states its true total and what it omitted, and defaults to the smallest useful answer. Omission is reported rather than silent — the difference between a briefing and a truncated file read.

**One honest counterweight.** These mechanisms are real and checkable. But the demonstrated quality of the *written understanding* rests on a single repository of roughly 470 files, authored by the tool's own author, with one model configuration. Take the claims about mechanism at face value; treat the claims about your codebase as an evaluation you would be running.

---

*Full detail: [`capabilities.md`](capabilities.md)*
