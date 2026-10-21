import { expect } from "@playwright/test";

export function progress(repositoryId = 1) {
  return {
    repository_id: repositoryId, snapshot_id: 42, scan: { active: false },
    execution: { mounted: true, configured_provider: "agent", local_executors: ["codex", "claude"], max_parallel_jobs: 4 },
    coverage: {
      scopes: { module: { total: 12, excluded: 0, intrinsic: 4, current: 2, intrinsic_reused: 2, reused: 1 } },
      live_jobs: [{ job_kind: "intrinsic", scope_type: "module", running: 0, interrupted: 0 }],
      document_models: [], scan: { analyzed_count: 10, reused_count: 2, error_count: 0 },
    },
    semantic: {
      enabled: true, provider: "agent", jobs: { pending: 8, running_live: 0 }, worker: { status: "idle" },
      map_status: { state: "current" }, budget: { paused: false },
      taxonomy: { enabled: true, required_review_passes: 2, ready: false },
      patterns: { enabled: false, planned: false, selected: 0, finalized: 0 },
      semantic_policy: { stage_models: { repository: { model: "gpt-6.1-sol", reasoning_effort: "high" } } },
      telemetry: { semantic: { current_snapshot: { actions: [{
        job_kind: "intrinsic", scope_type: "module", completed: 15, pending: 8, input_tokens: 12000,
        output_tokens: 400, token_counts_missing: 1, models: ["gpt-6-luna"],
      }] } } },
    },
    fresh_eyes: { state: "not_started", ready: false, stages: [], recommendations: [] },
  };
}

export function configuredProgress() {
  const value = progress();
  const worker = (model, workers = 1) => ({ provider: model.startsWith("claude") ? "claude" : "codex", model, workers, reasoning_effort: "medium" });
  const sol = worker("gpt-6.1-sol"), opus = worker("claude-opus-5-5");
  const steps = {
    intrinsic: [worker("gpt-6-luna", 4)], context: [worker("gpt-6-luna", 4)],
    taxonomy_proposal: [sol], taxonomy_review: [sol, opus], groups: [sol], charter: [sol],
    pattern_assessment: [sol], pattern_review: [opus], proposals: [sol, opus],
    adjudication: [sol], comparison: [opus], mission_filter: [sol],
    architecture_plan: [sol],
  };
  value.settings = { steps, suggested: structuredClone(steps), customized: [],
    modes: Object.fromEntries(Object.keys(steps).map(key => [key, ["intrinsic", "context", "groups", "pattern_assessment", "pattern_review"].includes(key) ? "parallel" : key === "taxonomy_review" ? "sequence" : key === "proposals" ? "proposals" : "single"])),
    models: { codex: ["gpt-6-luna", "gpt-6.1-sol"], claude: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] } };
  return value;
}

export async function open(page, value = progress()) {
  await page.route("**/api/workflows?*", route => route.fulfill({ json: value }));
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(page.locator(".workflow-node")).toHaveCount(8);
}
