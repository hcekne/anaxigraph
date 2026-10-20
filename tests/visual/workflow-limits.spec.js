import { test, expect } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

test("workflow shows uncapped calls, finite attempts and shared concurrency", async ({ page }) => {
  const value = configuredProgress();
  Object.assign(value.semantic.semantic_policy, {
    max_parallel_jobs: 32, max_attempts: 3, timeout_seconds: null,
    max_output_tokens: null, max_output_tokens_on_retry: null, daily_budget_usd: null,
  });
  await open(page, value);
  await page.locator("#workflow-limits summary").click();
  const limits = page.locator("#workflow-limits");
  await expect(limits).toContainText("32 parallel workers");
  await expect(limits).toContainText("3 attempts");
  await expect(limits).toContainText("No AnaxiGraph model time limit");
  await expect(limits).toContainText("provider default output capacity");
  await expect(limits).toContainText("no daily spending cap");
  await expect(limits).toContainText("Active leases renew automatically");
});

test("explicit repository limits are shown as actual values", async ({ page }) => {
  const value = configuredProgress();
  Object.assign(value.semantic.semantic_policy, {
    max_parallel_jobs: 8, max_attempts: 5, timeout_seconds: 720,
    max_output_tokens: 12000, max_output_tokens_on_retry: 24000, daily_budget_usd: 25,
  });
  await open(page, value);
  await page.locator("#workflow-limits summary").click();
  await expect(page.locator("#workflow-limits")).toContainText(
    "720s per model call; 12000 output tokens per call; 24000 output tokens on retry; $25 daily spending cap"
  );
});
