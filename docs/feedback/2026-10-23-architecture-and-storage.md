# Maintainer feedback on architecture reviews and storage

**Date:** 23 October 2026

**Related analysis:** [Graph purpose and architectural judgment](../graph-and-architecture-review-2026-10-23.md)

**Design response:** [Current versus proposed semantic graph, exact storage measurements and agent trade-offs](../design/semantic-graph-redesign-2026-10-23.md)

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
- Draft explicit prompts for alternatives at product, capability and subsystem levels: three
  retained designs, optionally explored from five sketches, compared without collapsing to one.
  Fresh Eyes remains implementation-blind; source-aware criticism belongs outside that workflow.
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

## Confirmed destination and product outcomes

- The semantic graph is the selected destination. Delivery can be phased, but completing a small
  cleanup of the existing knowledge model is not an acceptable endpoint.
- Each module has one concise overview sentence and one short detail paragraph. Agents first read
  the sentences, then expand relevant modules, functions, interfaces and contracts without reading
  raw source to obtain the deeper saved explanation.
- Make function/interface traversal and linked contracts useful for understanding behavior and
  finding safe places to make changes. The same compact understanding should serve people.
- Use graph structure to question complexity, overloaded responsibilities and dependencies across
  boundaries. A hundred incoming connections should prompt contextual investigation and alternatives,
  including retaining a cohesive utility rather than automatically splitting every busy node.
- Help developers build modular software with clear interfaces. A frontend-only change should not
  unexpectedly require unrelated backend changes when its public contracts remain unchanged.
- Assess actual behavior preservation and change propagation, not just fewer graph edges or smaller
  modules. These are explicit acceptance scenarios for the rewrite, not benefits already proven.
- Patterns and source-aware planning use the actual graph. Fresh Eyes keeps its earlier blindness
  requirement and receives only the functional projection; planning connects its proposed designs
  back to the actual graph.

## Clarified requirements from the maintainer

- Fresh Eyes must never inspect raw code or learn the existing architecture. Its input is purpose,
  functionality, observable inputs/outputs and functional dependencies, with implementation details
  removed. Source blindness is the point of the workflow, not a defect to repair.
- Work through functional hierarchies: overall product purpose, capability areas and the functions
  of subsystems/modules, including frontend/backend roles where relevant. At each reviewed level,
  propose several good ways to deliver the same functionality. Preserve three strong alternatives;
  exploring five materially different sketches is also consistent with the request.
- Flowthink's top-level promise is a second brain combining files/folders and connected tools—email,
  Google Drive, Shopify and other MCP servers—with the ability to run agentic workflows. Mapping
  should be able to extract that kind of high-level description.
- Patterns deliberately uses a catalogue. The requirement is explicit consideration of the entire
  catalogue, with contextual ratings, pros, cons and reasons for every entry. Priority can order
  deeper investigation, but must not silently remove patterns from consideration.
- Useful patterns can improve working code. A concrete bug or failure is not a prerequisite.
  Evaluate opportunities for clearer abstractions and better architecture, as well as existing fit.
- A common agent contract with provider-specific implementations is one supplied example among
  dozens of possibilities. The review and benchmark must cover many catalogue families rather than
  anchor on that one abstraction. The missed opportunity is applying a known useful idea without
  being told its name or the desired answer.
- Instructions must spell out the work for each catalogue entry. Do not rely on agents volunteering
  suitable patterns from a general request for a review. Track every catalogue ID and distinguish
  assessed poor fit, unresolved evidence and work that was never assessed.

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

## Full clarification on Fresh Eyes and Patterns

> I have a couple of comments to what you're just writing. Your critique of FreshEyes is exactly, but that's exactly what it's supposed to do. So that's completely by design. It is supposed to receive sample summaries and dependencies without raw model source. That's the whole fucking point, you fucking retarded idiot. Fresh Eyes is supposed to be a completely new way of Of analyzing the system, you're only, you're not supposed to be looking at the actual code and raw source, right? That's the whole point. You're supposed to be looking at summaries and then figuring out what would be a better way to design this without actually knowing how it was designed. Because you don't want to anchor the large language model to that previous design, right? That's the whole point. You're supposed to, fresh eyes is supposed to You're supposed to be looking at what are the functionalities? What is the functionality? What is it actually able to achieve? What is this tool doing? What is the primary purpose? Actually, so what we probably want to do when we redesign Fresh Eyes is we want to look at the tool in different hierarchies. So, so like what is the main, like for instance for flow thinking, I can easily say, what is the main objective of flow thinking? The main objective of flow thinking is to fulfill like to be a second brain for people to use Like where they have all their files and folders connected. And some of their tools are also connected to it. So their email, their Google Drive, Shopify and other MCP servers. And in addition, this is also all connected to a way of running agentic workflows. These two things, that is what the sort of core part of Flowthink is. And a fresh eyes And that's what I would want, like that kind of description is what I would want out from a, from a mapping of the tool, like on a very, very high level, right? That's the highest level of the tool. That is what it's, that is its function, right? That's what it does. And so that's what I would want tools to actually be able to extract on the highest level. Now then a fresh eyes review to But then, then what I want a fresh eyes review to do is like, okay, given that, what's the best way to implement that? Right? Or what are the three, top three best ways to implement something like that? Yes, and I, and I probably, it's probably a bad idea to reduce to fresh eyes suggestion down to one because that limits the amount of sort of, you know, ways we can look Look at this system. So given that, given what we're actually, given what this system is supposed to do, what are like the top three ways we could build something that would actually deliver on that promise? And then I want you, then, then also I want you to go a little bit further down. So given that we have, this is what we've, this is the functionality of the different modules. Like we've got a front end, we've got a back end, we've got all these different things. And they, their output Are there function is this? What would be three alternative, three good ways to deliver or to actually encodeify an architect that functionality? That is what I want Fresh Eyes to do. But because I never want Fresh Eyes to actually look at the code, right? I never want Fresh Eyes to actually look at what is actually being written because the whole point of Fresh Eyes is that it's not
>
> Also, yeah, in regards to patterns, there's supposed to have a catalog, you know, there's supposed to have some selected patterns that they actually select from. That's the whole point. But I agree with your proposed prompt direction is to generate five materially different architectures preserving the required behavior. Yeah, I agree with that. And for patterns you don't need to always identify a concrete problem, right? Like, okay I don't know how to actually solve this problem because I find it so difficult to solve. But the key insight is that I have worked with so many LLMs. And whenever I, for instance, ask them to, oh, what kind of abstractions could you see in this kind of codebase? They're unable to find it. And typically this would be, a typical example would be when I was integrating many different LLM providers into a tool. And I wanted to have, and it turned out it was way easier for the tool to have one abstract agent class that the tool interacted with and then have that agent class itself interact with all the LLM providers. But no matter how many times I asked the LLMs to give me this pattern or like to find a useful pattern, not this specifically, right? But a useful pattern. None of them was able to identify this specific pattern. And this is such a normal pattern in coding, especially object-oriented coding. And it was appalling that, you know, after several attempts of asking for code reviews, they just didn't identify this. And that is the problem, that is the core problem I need to attack with patterns, with my pattern review, right? I need to increase the ability to find this kind of useful patterns that makes the code easier and better architected. Do you understand? And if not, please reply if you don't, because this should be fucking pretty easy now. I've spelled it out

## Full clarification on catalogue coverage

> also understnad this " it should recognize an opportunity for a shared agent contract with provider-specific implementations" is just one of dousins of possilbe patterns that could be useful in an architecture.... RIGHT???? dont anchor toooo much to this one example... thats why I have the pattern catalogue... I want ALLL POSSIBLE FUCKING USEFUL PATTERNS TO BE CONSIDERED AND RATED AND GIVEN PROS AND CONS.. otherwise i dont believe the agents will be able to find and idenfity them
>
> IT needs to be so fuking spelled out ... otherwise just fucking forget about agents finding the right patterns and suggesting them

## Design before further implementation

At this point in the discussion, the maintainer paused implementation and clarified that the requested change is a radical,
lightweight redesign. Produce a concrete design first, compare it with actual current behavior,
measure complete Mapping/Patterns/Fresh Eyes storage, explain the lookup tables, and show how
semantic understanding becomes part of the graph. Compare gains and losses against previous
agent feedback, including reasons the new approach could make their work worse. The request was
to review that design before further implementation or release. The later clarification below
confirms the semantic graph destination and its required product outcomes.

> wait

> I've got a slight update for you, and I just want to make sure that this is actually quite a radical, to understand what I'm asking you. It's quite a radical redesign of how an anaxigraph kind of works right now, right? I'm probably looking for a much more lightweight architecture for an anaxigraph. And before you just go and like fucking implement it, I want you to design it and then come back to me with how it's actually going to look and compare that with the current implementation. Also, when you do that comparison, I also want you to compare the exact size of a full an axiograph map and fresh eyes and everything, all this compared to what it is today. I also want you to compare like, what is this lookup table thing? How would this be changed in the future with your new implementation? Because what I'm really looking for is just like more graphify approach, right? Like, what is it graphify actually does? It graphs your whole code base, right? That's kind of what I want for an anaxigraph to do as well, but I want it to be more, right? I want it to be the semantic understanding as well, and I want that to be written into the graph itself so that it kind of, right? You understand what I'm actually asking you here, right?

> and compare that to what anaxigraph does today.. argue for why this is worse or better than todays version. argue for what are are potentially gaining and what we are loosing. Look at previous feedbback in your documentation .. especially from other agents.. would this new change make the tool better or worse for them???

## Full clarification confirming the graph destination

> For your proposal here and I mean we want to, we don't want to just do an incremental migration towards semantic graph. That's our new, that's where we want to go, right? That's, that's where we want to take the tool. And so that's where we want to migrate. And yeah, I think function interface traversal and late contracts could improve substantially what the agents actually get out of it, right? And, and also yeah, we want to, for each module, like how we describe them. It's like one sentence and then a short paragraph. Very concise, very to the point. And so that when, when, when an agent is running through this, it will first just read the sentences, you know, about each or whatever and get that short kind of understanding quickly. And then it can, if it needs to go deeper, it'll, it can do that. It can go deeper into that without actually reading the modules, right?  and then Of course, and then when we actually do the fresh eyes and when we do the pattern matching, the, the graph is supposed to be a inspiration for finding the better like versions, right? Like the AI, I want the AI to be able to say, hey, look at this graph note here. It's got like 100 incoming whatever connections or something. Like maybe it would be better just to break this up or, you know, reduce the complexity here so that it's easier to work with or whatever, right? You know, from a, from a conceptual standpoint, from, from an understanding standpoint, from a human standpoint, it makes a lot of sense to have separate things doing separate things, right? Like so for instance, if I have a front end, I want to be able to adjust things in the front end without, you know, breaking things otherwhere in the software. That's typically what I'm after, right? So I'm, I want my, the design of my software to be modular and have clear interfaces, not to be overly complex. And I want an AnaxiGraph to help me do this. So as I build this software and use an AnaxiGraph as a helping tool, that is what I want to achieve. And so you need to make sure that when we now re-engineer the code that those objectives are met.
