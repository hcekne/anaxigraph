import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

function plan() {
  const domain = { key: "domain", label: "Application domain", responsibility: "Own behavior", paths: ["src/domain.py"], evidence: ["src/domain.py"] };
  const current = { nodes: [domain], edges: [], unknowns: ["Deployment topology is unknown."] };
  const target = { nodes: [domain, { key: "worker", label: "Existing compute worker", responsibility: "Compute", paths: ["src/worker.py"], evidence: ["src/worker.py"] }], edges: [{ source: "domain", target: "worker", label: "delegates", evidence: [] }], unknowns: [] };
  const milestone = { key: "reuse", title: "Reuse the compute owner", outcome: "Keep compute behind the existing boundary", owners: ["src/worker.py"], affected_contracts: ["compute"], depends_on: [], verification: ["Run compute behavior tests"], rollback: "Revert the adapter change", evidence: ["src/worker.py"] };
  const options = [{ key: "preserve", title: "Preserve current design", summary: "Keep the observed boundary", costs: [], risks: [], target: current, milestones: [] }, { key: "evolve", title: "Evolve existing boundaries", summary: "Reuse the compute owner", costs: ["A focused change"], risks: ["Preserve caller contracts"], target, milestones: [milestone] }];
  return { state: "current", ready: true, snapshot_id: 42, summary: "Reuse existing responsibilities", user_direction: "", direction: "Preserve behavior", selected_option: "evolve", selection_source: "agent", selection_rationale: "Small, reversible changes fit this repository", target: options[1], option_count: 2, milestone_count: 1, progress: {}, provenance: { created_at: "2026-10-21" }, value: { current, options }, diagrams: { current, target, changes: [{ key: "domain", status: "retained" }, { key: "worker", status: "added" }], current_mermaid: "flowchart LR\n n0[Domain]", target_mermaid: "flowchart LR\n n0[Domain] --> n1[Worker]" } };
}

test("full planning accepts blank direction and submits the complete workflow", async ({ page }) => {
  const value = configuredProgress();
  let posted;
  await page.route("**/api/architecture-plan?*", route => route.fulfill({ json: { state: "not_started", ready: false } }));
  await page.route("**/api/workflows/run", route => { posted = route.request().postDataJSON(); return route.fulfill({ json: { status: "started" } }); });
  await open(page, value);
  await page.locator("#workflow-tab-architecture").click();
  await expect(page.locator("#architecture-direction")).toHaveValue("");
  await expect(page.locator("#workflow-run-button")).toHaveText("Run full architecture planning");
  await expect(page.locator("#architecture-planning-panel")).toContainText("Leave this blank");
  await expect(page.locator("#planning-evidence")).not.toContainText("not_started");
  await page.locator("#workflow-run-button").click();
  await expect.poll(() => posted?.workflow).toBe("architecture");
  expect(posted).toMatchObject({ goal: "", use_step_settings: true, step: null });
});

test("letting the agent choose clears a previously saved direction", async ({ page }) => {
  const value = configuredProgress(), saved = plan();
  saved.user_direction = "Scale the compute boundary";
  value.architecture_plan = saved;
  let posted;
  await page.route("**/api/architecture-plan?*", route => route.fulfill({ json: saved }));
  await page.route("**/api/workflows/run", route => {
    posted = route.request().postDataJSON();
    return route.fulfill({ json: { status: "started" } });
  });
  await open(page, value);
  await page.locator("#workflow-tab-architecture").click();
  await expect(page.locator("#architecture-direction")).toHaveValue(saved.user_direction);
  await page.getByRole("button", { name: "Let the agent choose", exact: true }).click();
  await expect(page.locator("#workflow-run-button")).toHaveText("Update architecture plan");
  await page.locator("#workflow-run-button").click();
  await expect.poll(() => posted?.goal).toBe("");
});

test("saved options and current versus target diagrams remain readable on laptop and phone", async ({ page }, testInfo) => {
  const value = configuredProgress(), saved = plan();
  value.architecture_plan = saved;
  value.semantic.architecture_charter = { status: "current" };
  await page.route("**/api/architecture-plan?*", route => {
    expect(new URL(route.request().url()).searchParams.get("details")).toBe("true");
    return route.fulfill({ json: saved });
  });
  await page.route("**/api/architecture-plan", async route => {
    const body = route.request().postDataJSON();
    expect(body.details).toBe(true);
    saved.selected_option = body.option;
    saved.selection_source = "user";
    saved.target = saved.value.options.find(option => option.key === body.option);
    await route.fulfill({ json: saved });
  });
  await open(page, value);
  await page.locator("#workflow-tab-architecture").click();
  await expect(page.locator("#architecture-plan-results")).toContainText("agent selection");
  await expect(page.getByRole("img", { name: "Current architecture" })).toBeVisible();
  await expect(page.locator(".architecture-diagram .plan-node.added")).toHaveCount(1);
  await expect(page.locator("#architecture-plan-results")).toContainText("Run compute behavior tests");
  await expect(page.locator("#workflow-run-button")).toBeDisabled();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath(`architecture-planning-${width}.png`), fullPage: true });
  }
  await page.locator('[data-plan-option="preserve"]').click();
  await expect(page.locator("#architecture-plan-results")).toContainText("user selection");
  await expect(page.locator('[data-plan-option="preserve"]')).toHaveText("Selected target");
});

test("a completed mapping ignores another workflow's old failure", async ({ page }) => {
  const value = configuredProgress();
  value.coverage.scopes = { module: { total: 12, excluded: 0, intrinsic: 12, current: 12 }, group: { total: 1, current: 1 } };
  value.semantic.architecture_charter = { status: "current" };
  value.semantic.taxonomy = { enabled: true, ready: true, required_review_passes: 2, current: { stored_reviews: 2 } };
  value.semantic.jobs = {};
  value.semantic.worker = { workflow: "patterns", snapshot_id: 41, status: "waiting", message: "A prerequisite could not complete", processed: 0 };
  await open(page, value);
  await expect(page.locator("#workflow-run-button")).toHaveText("Mapping is up to date");
  await expect(page.locator("#workflow-run-button")).toBeDisabled();
  await expect(page.locator("#workflow-message")).toContainText("Mapping is up to date");
  await expect(page.locator("#workflow-message")).not.toContainText("prerequisite");
});
