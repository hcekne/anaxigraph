import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

test("step 5 shows saved batches, active workers, time and final reconciliation", async ({ page }) => {
  const value = configuredProgress();
  value.semantic.taxonomy.current = { stored_reviews: 1, validation: {} };
  value.settings.steps.taxonomy_review.forEach(worker => { worker.workers = 2; });
  value.semantic.worker = { status: "running", workflow: "mapping", step: "taxonomy_review", active_step: "taxonomy_review", phase: "executing" };
  value.coverage.taxonomy_review = { passes: [
    { pass: 1, completed_batches: 3, total_batches: 3, active_workers: 0, elapsed_seconds: 30, reconciliation: "complete", final: false },
    { pass: 2, completed_batches: 1, total_batches: 3, active_workers: 2, elapsed_seconds: 17, reconciliation: "not_started", final: true },
  ] };
  value.coverage.live_jobs = [{ job_kind: "taxonomy_review", scope_type: "taxonomy", running: 2 }];
  await open(page, value);
  const card = page.locator('[data-step="taxonomy_review"]');
  await expect(card).toContainText("1 / 3 batches saved");
  await expect(card).toContainText("2 workers active · 17s elapsed");
  await expect(card).toContainText("Final reconciliation · Not run");
  await card.click();
  const details = page.locator("#workflow-detail");
  await expect(details).toContainText("Pass 1 · 3 / 3 batches saved");
  await expect(details).toContainText("Pass reconciliation · Complete");
  await expect(details).toContainText("Pass 2 · 1 / 3 batches saved");
  await page.keyboard.press("Escape");
  value.coverage.taxonomy_review.passes[1] = { pass: 2, completed_batches: 3, total_batches: 3, active_workers: 1, elapsed_seconds: 22, reconciliation: "running", final: true };
  value.coverage.live_jobs[0].running = 1;
  await page.locator("#workflow-refresh").click();
  await expect(card).toContainText("3 / 3 batches saved");
  await expect(card).toContainText("Final reconciliation · Running");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("ordered review settings allow parallel workers within each pass", async ({ page }) => {
  await open(page, configuredProgress());
  await page.locator('[data-configure-step="taxonomy_review"]').click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Independent batches run in parallel within each pass and save immediately");
  await expect(dialog).toContainText("Reconciliation combines their findings before the next model starts");
  const workers = dialog.locator('[name="workers"]');
  await expect(workers).toHaveCount(2);
  await expect(workers.first()).not.toHaveAttribute("readonly");
  await expect(workers.first()).toHaveAttribute("max", "4");
  await workers.first().fill("4");
  await workers.last().fill("4");
  await expect(dialog.getByRole("button", { name: "Save settings", exact: true })).toBeEnabled();
});
