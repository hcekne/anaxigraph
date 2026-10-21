// Planning composes saved analyses; the agent selects a target when direction is blank.
export function architectureWorkflow(data, step, jobFacts) {
  const plan = data.architecture_plan || {};
  const ready = plan.ready, mapped = data.semantic?.architecture_charter?.status === "current";
  return { id: "architecture", name: "Architecture planning", title: "Choose a direction and plan the transition",
    description: "Build on Mapping, Patterns and Fresh Eyes. The agent can choose the target; your direction is optional.",
    note: "Available reviews become evidence, with gaps retained. Planning proposes a target and reversible milestones; it does not edit source.",
    update: plan.state === "stale" ? { next: "architecture_plan", nextTitle: "Compare architecture options", summary: "Source changed; the selected target and reported progress are retained. Update the plan when a new architectural decision is needed." } : null,
    steps: [
      step("plan_direction", "Set a direction", "Use suggested goals, add your own, or leave it to the agent.", { owner: "You or the agent", done: 1, total: 1, unit: "optional input", detail: plan.direction || plan.default_direction, view: "workflows" }),
      step("plan_evidence", "Gather understanding", "Use the current map and available independent reviews.", { owner: "AnaxiGraph code", done: mapped ? 1 : 0, total: 1, unit: "map", detail: "Mapping is required. Patterns and Fresh Eyes contribute when available; missing reviews remain explicit.", view: "overview" }),
      step("architecture_plan", "Compare architecture options", "An agent weighs alternatives and selects a justified target.", { done: ready ? 1 : 0, total: 1, unit: "plan", jobs: jobFacts(data, "architecture_plan"), detail: "The same saved agent job produces options, selects a target, and writes diagrams and milestones. No human approval is required.", view: "workflows" }),
      step("plan_target", "See current and target", "Compare boundaries and inspect the chosen option.", { owner: "AnaxiGraph code", done: ready ? 1 : 0, total: 1, unit: "target", detail: plan.selection_rationale || "The agent selects a target by default. You may choose another saved option.", view: "workflows" }),
      step("plan_milestones", "Plan small changes", "Follow ordered milestones with contracts and verification.", { owner: "AnaxiGraph code", done: ready ? plan.milestone_count || 0 : 0, total: ready ? plan.milestone_count || 0 : null, zeroComplete: ready, unit: "milestones", detail: "Each milestone names owners, dependencies, behavior checks and a rollback. Completion requires reported evidence.", view: "workflows" }),
      step("plan_develop", "Guide and reassess", "Give the coding agent a shared target and track progress.", { owner: "You or the agent", done: ready ? 1 : 0, total: 1, unit: "handoff", detail: "Guide exposes the saved target. Implement one milestone, run focused tests, refresh and report verification; a proposal remains separate from the observed code.", view: "agents" }),
    ] };
}
