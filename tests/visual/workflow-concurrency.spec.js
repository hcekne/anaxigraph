import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

test("simultaneous steps show live workers and leave other cards runnable", async ({ page }) => {
  const value = configuredProgress();
  const runs = [
    { workflow: "mapping", step: "intrinsic", active_step: "intrinsic", status: "running", phase: "executing" },
    { workflow: "mapping", step: "taxonomy_review", active_step: "context", status: "running", phase: "executing" },
  ];
  value.semantic.worker = { ...runs[1], runs, active_count: 2 };
  value.coverage.live_jobs = [
    { job_kind: "intrinsic", scope_type: "module", running: 1 },
    { job_kind: "context", scope_type: "module", running: 2 },
  ];
  await open(page, value);
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("1 / 4 workers active");
  await expect(page.locator('[data-step="context"]')).toContainText("2 / 4 workers active");
  await expect(page.locator('[data-step="taxonomy_review"]')).toContainText("Waiting for prerequisites");
  await expect(page.locator("#workflow-message")).toHaveText("3 / 4 workers active");
  await expect(page.locator('[data-run-step="intrinsic"]')).toBeDisabled();
  await expect(page.locator('[data-run-step="taxonomy_review"]')).toBeDisabled();
  await expect(page.locator('[data-run-step="groups"]')).toBeEnabled();
  await expect(page.locator("#workflow-run-note")).toContainText("Runs the full Mapping sequence");
});

test("preparing, saving and completion are distinct from active model calls", async ({ page }) => {
  const value = configuredProgress();
  value.semantic.worker = { workflow: "mapping", step: "intrinsic", status: "running", phase: "preparing" };
  await open(page, value);
  await expect(page.locator("#workflow-message")).toHaveText("Preparing pending jobs…");
  value.semantic.worker.phase = "executing";
  await page.locator("#workflow-refresh").click();
  await expect(page.locator("#workflow-message")).toHaveText("Saving worker results…");
  value.semantic.worker.phase = "finishing";
  value.coverage.scopes.module.intrinsic = 12;
  await page.locator("#workflow-refresh").click();
  await expect(page.locator("#workflow-message")).toHaveText("Results saved · finishing…");
  await expect(page.locator('[data-step="intrinsic"] .workflow-spinner')).toHaveCount(0);
  await expect(page.locator('[data-run-step="context"]')).toBeEnabled();
  value.semantic.worker = { status: "complete", message: "Selected work is complete.", processed: 8, runs: [] };
  await page.locator("#workflow-refresh").click();
  await expect(page.locator("#workflow-message")).toContainText("steps remain");
  await expect(page.locator("#workflow-message")).not.toContainText("jobs processed");
  await expect(page.locator("#workflow-message")).not.toContainText("workers active");
});

test("a later card requests its target directly and shows dependencies while waiting", async ({ page }) => {
  const value = configuredProgress();
  let request;
  await page.route("**/api/workflows/run", async route => {
    request = route.request().postDataJSON();
    const run = { workflow: "mapping", step: request.step, active_step: "context", status: "running", phase: "executing" };
    value.semantic.worker = { ...run, runs: [run] };
    value.coverage.live_jobs = [{ job_kind: "context", scope_type: "module", running: 2 }];
    await route.fulfill({ json: { status: "started" } });
  });
  await open(page, value);
  await page.locator('[data-run-step="taxonomy_review"]').click();
  expect(request).toMatchObject({ workflow: "mapping", step: "taxonomy_review", use_step_settings: true });
  await expect(page.locator('[data-step="context"]')).toContainText("2 / 4 workers active");
  await expect(page.locator('[data-step="taxonomy_review"]')).toContainText("Waiting for prerequisites");
});
