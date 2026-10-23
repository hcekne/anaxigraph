import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

test("simultaneous steps show live workers and leave other cards runnable", async ({ page }) => {
  const value = configuredProgress();
  value.settings.steps.groups[0].workers = 4;
  const runs = [
    { workflow: "mapping", step: "annotation", active_step: "annotation", status: "running", phase: "executing" },
    { workflow: "mapping", step: "taxonomy_review", active_step: "groups", status: "running", phase: "executing" },
  ];
  value.semantic.worker = { ...runs[1], runs, active_count: 2 };
  value.coverage.live_jobs = [
    { job_kind: "annotation", scope_type: "module", running: 1 },
    { job_kind: "synthesis", scope_type: "group", running: 2 },
  ];
  await open(page, value);
  await expect(page.locator('[data-step="annotation"]')).toContainText("1 / 4 workers active");
  await expect(page.locator('[data-step="groups"]')).toContainText("2 / 4 workers active");
  await expect(page.locator('[data-step="taxonomy_review"]')).toContainText("Waiting for prerequisites");
  await expect(page.locator("#workflow-message")).toHaveText("3 / 4 workers active");
  await expect(page.locator('[data-run-step="annotation"]')).toBeDisabled();
  await expect(page.locator('[data-run-step="taxonomy_review"]')).toBeDisabled();
  await expect(page.locator('[data-run-step="charter"]')).toBeEnabled();
  await expect(page.locator("#workflow-run-note")).toContainText("Runs the full Mapping sequence");
});

test("preparing, saving and completion are distinct from active model calls", async ({ page }) => {
  const value = configuredProgress();
  value.settings.steps.groups[0].workers = 4;
  value.semantic.worker = { workflow: "mapping", step: "annotation", status: "running", phase: "preparing" };
  await open(page, value);
  await expect(page.locator("#workflow-message")).toHaveText("Preparing pending jobs…");
  value.semantic.worker.phase = "executing";
  await page.locator("#workflow-refresh").click();
  await expect(page.locator("#workflow-message")).toHaveText("Saving worker results…");
  value.semantic.worker.phase = "finishing";
  value.coverage.scopes.module.current = 12;
  await page.locator("#workflow-refresh").click();
  await expect(page.locator("#workflow-message")).toHaveText("Results saved · finishing…");
  await expect(page.locator('[data-step="annotation"] .workflow-spinner')).toHaveCount(0);
  await expect(page.locator('[data-run-step="charter"]')).toBeEnabled();
  value.semantic.worker = { status: "complete", message: "Selected work is complete.", processed: 8, runs: [] };
  await page.locator("#workflow-refresh").click();
  await expect(page.locator("#workflow-message")).toContainText("steps remain");
  await expect(page.locator("#workflow-message")).not.toContainText("jobs processed");
  await expect(page.locator("#workflow-message")).not.toContainText("workers active");
});

test("a later card requests its target directly and shows dependencies while waiting", async ({ page }) => {
  const value = configuredProgress();
  value.settings.steps.groups[0].workers = 4;
  let request;
  await page.route("**/api/workflows/run", async route => {
    request = route.request().postDataJSON();
    const run = { workflow: "mapping", step: request.step, active_step: "groups", status: "running", phase: "executing" };
    value.semantic.worker = { ...run, runs: [run] };
    value.coverage.live_jobs = [{ job_kind: "synthesis", scope_type: "group", running: 2 }];
    await route.fulfill({ json: { status: "started" } });
  });
  await open(page, value);
  await page.locator('[data-run-step="taxonomy_review"]').click();
  expect(request).toMatchObject({ workflow: "mapping", step: "taxonomy_review", use_step_settings: true });
  await expect(page.locator('[data-step="groups"]')).toContainText("2 / 4 workers active");
  await expect(page.locator('[data-step="taxonomy_review"]')).toContainText("Waiting for prerequisites");
});
