# Maintainer feedback on architecture reviews and storage

**Date:** 23 October 2026

**Related analysis:** [Graph purpose and architectural judgment](../graph-and-architecture-review-2026-10-23.md)

AnaxiGraph should primarily provide a compact, navigable understanding of code, interfaces and
change propagation. The maintainer questions whether the current volume of descriptions and
completed review stages produces useful architectural judgment. A seven-hour completed run that
misses known problems is a product failure to investigate, even when storage fits a ceiling.

## Requirements and examples to preserve

- Investigate why Patterns and Fresh Eyes miss obvious opportunities and offer little meaningful
  architectural variety. Do not infer that the existing design is optimal from a completed workflow.
- Study the gap between recalling a principle and applying it in a new situation. Preserve the
  analogy between reciting a car manual or UK driving rules and actually driving or passing a test.
  Investigate model training, combinations of learned skills, and the surrounding agent harness.
- Draft stronger prompts: five different ways to organize the same application, comparison of all
  alternatives, and the strongest concrete criticism of an existing boundary or subsystem.
- Make the code graph the primary product, approximately 90% of the maintainer's intended value.
  Show modules, functions, interfaces and their relationships; explain how behavior flows through
  them. Include module LOC and function counts, a one-sentence overview, a short paragraph for
  important details, and a sentence explaining each function.
- Analyze dense dependency clusters, isolated nodes, possible dead code and unnecessary stored
  data. Surface reasons and useful actions, rather than produce more descriptions for their own sake.
- Support reversible deletion experiments. The maintainer accepts that Git can restore code if a
  later regression reveals a missed consumer; possible uncertainty should inform an experiment.
- Prepare for substantial repository growth. Protect core responsibilities, make components more
  self-contained, and concentrate cross-boundary interaction through clear interfaces—the
  maintainer's "module highways."
- Explain the consequences of a change: affected callers, focused tests, necessary companion
  changes and unexpected propagation. Avoid chains of incidental changes across unrelated modules.
- Preserve the agent-adapter example: changes inside Claude Code or Codex integration should
  preserve the shared agent-facing contract and caller behavior. More robust provider internals
  should not require unrelated application changes.
- Treat robustness, maintainability, useful guidance and discovery as success criteria. Question
  whether extensive writing and per-file analysis are displacing those outcomes.
- Preserve the earlier storage preference: roughly 100 MB of generated state is preferred, with
  200 MB described as an absolute ceiling. A cache being below the latter does not justify its size.

## Run figures supplied with the feedback

These are figures reported by another coding agent, not new measurements of floThink in this audit:

| Reported item | Reported value |
| --- | --- |
| Full analysis duration | Seven hours |
| Portable map | 4.95 MB |
| Default file response | At most 8 KB, with details available separately |
| Rebuildable cache | 122 MB, described as within an unchanged 200 MB ceiling |
| Completion | Mapping, Patterns and Fresh Eyes |
| Restoration | Original results and provenance preserved without additional model calls |
| Verification | 1,472 full-suite tests, followed by 33 focused tests after an export fix |
| Explanation supplied by that agent | Two detailed descriptions per file, copies in lookup tables, and retained function/import facts |

The exact floThink run, its review inputs and its database footprint remain case evidence to
collect. These reported figures must not become invented table-level measurements.

## Full maintainer feedback

The following preserves the original wording, including the examples and reported agent response.

> The problem is.. Both fresh eyes and pattern matching end up with, they always, they never seem to like really come up with something novel. Or something new, or like something, like even when I know that they should catch, like there's an obvious thing that they should catch, they don't seem to find it. I think this just goes to the problem we have with large language models is that they are great at recall, but they suck dick at like getting, using that effectively sometimes. Like, you know, large language models could be great at reciting the instructions manual for a car or the, what the driver's, you know, laws and regulations in the UK are. But they might fail miserably at driving a car and at a driving license test because they don't always know how to apply it naturally and they don't seem to be able to do that in a good way. There seems to be this disconnect between recall and application. And that's what I'm seeing again and again and again and again in this programming space as well. And I don't understand, like I don't, bridging that gap seems to be kind of difficult right now. This is actually a research problem as well. So I, as a side note, I need to, I want to have a research agenda on this because I think this is so interesting. Humans are so good at this, right? Or, you know, we can take stuff, learn it and apply it in a much better way. Or we, the way we, you know, apply combined knowledge and know-how is kind of unique. And I think that's something we need to be, we need to train the large language models to be much, much better at, or their harnesses or whatever, the techniques that we put around there needs to be better. Now, I think the failures of the pattern matching and the fresh eyes is, it needs to be phrased differently. It's just like, it needs to be a much more antagonistic towards the current way of doing it. So current, like if you're looking at the current way of writing a code base, you need to say, come up with five different ways of writing that exact same codebase. Now compare them all against each other. Or like, you know, or if you were a super critic, if this was, like, what was the most super critical thing you could write about this part of the code, right? And take more that approach. I'm not exactly sure how to phrase this and I need you to come up with ways, suggestions for me to rewrite the prompts that are in Fresh Eyes and in pattern matching to be much better because I don't believe in a codebase as large as floThink That we that we still like that it doesn't find any good patterns or that it, and that it doesn't you know, see any other ways of doing this that it still thinks whatever the architecture is right now is the best way of doing it. I find that completely, like, crazy. There must be other ways of like making this program in a decent way. In another way. And the fact that that isn't even surfaced in this like seven-hour analysis, I find to be completely absurd. That's number one.
>
> Issue number 2. what the fuck are all these fucking files for??? why does it take over 100mb??
>
> This is what it gives me after a full 7 hours:
>
> The tool generated two detailed descriptions per file, copied descriptions into lookup tables, and retained function/import facts for tracing code links.
>
> I’ve tightened the export and default responses locally:
>
> - Complete portable map: 4.95 MB.
> - Default file replies: ≤8 KB, with full details on request.
> - Rebuildable cache: 122 MB, within the unchanged 200 MB ceiling.
>
> Mapping, Patterns, and Fresh Eyes are complete. All original results and provenance survived restoration without additional model calls. The full suite passed 1,472 tests, followed by 33 focused tests after the export fix.
>
> So basically, my issue is that, you know, what I want the first map to do is basically to first understand how modules are connected together. And that's kind of like graphifying, right? Can you just start with like a line drawing? And then you connect modules to each other through that based on their functionality and based on how they interface and based on how they are connected, right? That graph, that's kind of a graph that tells you kind of how the program works to some degree. And so that's one of the things, artifacts, I obviously want to create. Now, the way I kind of see this, and that in itself is a good map for understanding and analysis of the codebase. I think once you kind of, if you were to draw out a map like that about how all the different modules interact, how different functions interact with each other, and how you can kind of traverse that, right? Like so then, and then how many, how many lines of code maybe is in each module or how many, and how many different functions it has, right? And then give a short brief description. I'm talking like maybe a sentence for each module as a short, overbrief description. And then maybe a short paragraph after that which goes in a little bit more detail about a specific function, about specific things that that actual module does. And if you similarly document each of the functions within the modules so that they also have a brief description, a sentence each kind of about that specific. And then the interfaces. I think that map in itself there would be you know, that should be 90% of what kind of an Anaxigraph is, right? And then there needs to be some analysis, So some analysis that basically is able to traverse this, look for modules perhaps that are too densely connected. Look for node, like, like nodes, Yeah, some notes will be yeah, too densely connected. Some nodes will be connected to nothing maybe. And why are they even there, right? Like there's probably even dead code here. Like I know that the manager or like the maintainer of the code or the build, he uses, he uses a set of analyses that go through his codebase every night to find dead code. And I mean, I would bet there's loads of dead code in here that's basically not being used to store stuff that's just can be just removed. And we also don't need to acknowledge that this whole codebase is a GitHub repo, right? Like so even if we make changes, we can always revert. If we figure out, okay, actually we should remove this because it's dead code, you know, if that leads to some bug down the road, well, fine, then maybe we need to just sort that out. But for now it's okay, right? Like the thing is, as we are expanding and building out the codebase here, because the codebase will grow a lot. This is just a start, right? Like we're going to have way more. I mean, we maybe we could protect the core codebase in some way, but and then the core of the, maybe we find some way to like ring fence parts of the solution so that they are more sort of standalone and, and, and or maybe just interact with other parts of the application along some kind of module highways, if you know what I mean. Like so that we make it easier and less complex, right? Like the thing is the more different modules are connected to other different modules, the more we have increased complexity, right? Because then if you change something, that can have profound impact across large parts of the codebase. And that's kind of what you don't want. You know, you want something that's easy to maintain, that's clear to understand what's connected to it. And if you change something, then it's also clear to understand like you know, what else you need to test for, what you need to check. And what other changes you need to make and not have like follow-on, follow-on changes, follow-on effects, follow-on effects from something that you did, right? That's, that's like the last thing you want to have. For instance, let's say you have an adapter that connects both Claude code agents and Codex agents into the tool. And so it's an interface that lets you interface abstractly with agents. Now if you make some change to that interface, you would expect that the agents interface would continue to work exactly as it did even if you made changes to how it was actually interfacing with Claude Code and Codex. You would, the user of that contract kind of would expect, you know, maybe similar behavior even if you did upgrades to the abstract agent class and made it more robust and stuff towards the providers that it was actually abstracting away. Right? That's the kind of behavior you would want from good code. And you wouldn't think that anything else in the app would change if you made changes there. So that's kind of robustness criteria that I want to build against. And that's the things, these are the things that I want kind of an anaxigraph to really check for and test. And maybe what we've done with the anaxigraph so far is just overwriting. Maybe we're just doing too much writing. Maybe it's not actually serving its useful purpose. And I think these are all questions that I want to analyze right now.

## Request to retain the feedback

> also write all this i have written here down so we dont forget it
