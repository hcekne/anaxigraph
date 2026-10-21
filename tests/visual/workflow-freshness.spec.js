import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

function updatedProgress() {
  const value = configuredProgress();
  value.snapshot_id = 43;
  value.coverage.scopes.module = { total: 636, excluded: 0, intrinsic: 624, current: 489, intrinsic_reused: 624, reused: 489 };
  value.coverage.history = {
    commit_sha: "abcdef012345",
    modules: {
      intrinsic: { current: 624, refresh: 10, new: 2 },
      context: { current: 489, refresh: 145, new: 2 },
      affected: [{ path: "src/config.py", intrinsic: "refresh", context: "refresh" }, { path: "tests/new.py", intrinsic: "new", context: "new" }],
    },
    taxonomy: { snapshot_id: 42, commit_sha: "123456abcdef", proposal_model: "gpt-6.1-sol",
      reviews: 1, required_reviews: 2, failed_reviews: 1, review_models: ["gpt-6.1-sol", "claude-opus-5-5"], error: "The earlier review exceeded its output allowance" },
  };
  return value;
}

test("changed source shows retained work, refresh counts and an explicit update action", async ({ page }, testInfo) => {
  const value = updatedProgress();
  let starts = 0;
  await page.route("**/api/workflows/run", route => { starts++; return route.fulfill({ json: { status: "started" } }); });
  await open(page, value);
  await expect(page.locator(".workflow-source-update")).toContainText("Source changed · your work is saved");
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("10 to refresh · 2 first run");
  await expect(page.locator('[data-step="context"]')).toContainText("489 / 636 current files");
  await expect(page.locator('[data-step="taxonomy_proposal"]')).toContainText("1 saved proposal");
  await expect(page.locator('[data-step="taxonomy_review"]')).toContainText("1 / 2 saved passes");
  for (const step of ["intrinsic", "context", "taxonomy_proposal", "taxonomy_review"]) {
    await expect(page.locator(`[data-step="${step}"] .workflow-status`)).toHaveText("Needs update");
  }
  await expect(page.locator("#workflow-run-button")).toHaveText("Update mapping");
  await page.getByRole("button", { name: "See what changed" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator("#workflow-detail")).toContainText("10 saved results need refresh");
  await expect(page.locator("#workflow-detail")).toContainText("src/config.py");
  await page.keyboard.press("Escape");
  await page.locator('[data-step="taxonomy_review"]').click();
  await expect(page.locator("#workflow-detail")).toContainText("1 proposal · 1 / 2 review passes saved · 1 failed");
  await page.getByText("Earlier review failure", { exact: true }).click();
  await expect(page.locator("#workflow-detail")).toContainText("The earlier review exceeded");
  await page.keyboard.press("Escape");
  for (const [width, height] of [[1280, 720], [1440, 900], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.locator("#workflow-focus").click();
    expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(width);
    if (width > 1000) {
      await expect.poll(() => page.locator(".workflow-card").evaluateAll(cards => cards.every(card => {
        const box = card.getBoundingClientRect();
        return box.top >= 60 && box.bottom <= innerHeight;
      }))).toBe(true);
    }
    await page.screenshot({ path: testInfo.outputPath(`source-update-${width}.png`), fullPage: width < 1000 });
  }
  expect(starts).toBe(0);
});

test("a polled source update and page reload keep saved proposal and review visible", async ({ page }) => {
  const value = updatedProgress();
  const before = configuredProgress();
  before.coverage.scopes.module = { total: 634, excluded: 0, intrinsic: 634, current: 634 };
  before.semantic.taxonomy.current = { stored_reviews: 1, validation: {} };
  await open(page, before);
  await expect(page.locator('[data-step="taxonomy_proposal"] .workflow-status')).toHaveText("Complete");
  await page.route("**/api/workflows?*", route => route.fulfill({ json: value }));
  await expect(page.locator('[data-step="taxonomy_proposal"]')).toContainText("1 saved proposal");
  await expect(page.locator('[data-step="taxonomy_review"]')).not.toContainText("Not run");
  await page.reload();
  await expect(page.locator('[data-step="taxonomy_review"]')).toContainText("1 / 2 saved passes");
  await expect(page.locator(".workflow-source-update")).toBeVisible();
});

test("active updates take precedence and a new repository still reports never-run steps", async ({ page }) => {
  const value = updatedProgress();
  value.semantic.worker = { status: "running", workflow: "mapping", step: "context" };
  value.coverage.workers = [{ job_kind: "context", scope_type: "module", running: 4, executor_model: "gpt-6-luna" }];
  await open(page, value);
  await expect(page.locator('[data-step="context"]')).toContainText("4 / 4 workers active");
  await expect(page.locator('[data-step="context"] .workflow-status')).toHaveText("Running");
  const fresh = configuredProgress();
  fresh.coverage.history = { modules: { intrinsic: { current: 0, refresh: 0, new: 12 } }, taxonomy: null };
  await page.route("**/api/workflows?*", route => route.fulfill({ json: fresh }));
  await page.locator("#workflow-refresh").click();
  await expect(page.locator('[data-step="taxonomy_proposal"] .workflow-status')).toHaveText("Not run");
  await expect(page.locator(".workflow-source-update")).toHaveCount(0);
});

test("reusing the proposal keeps old review evidence visible without counting it as a current review", async ({ page }) => {
  const value = updatedProgress();
  value.coverage.scopes.module.intrinsic = value.coverage.scopes.module.current = 636;
  value.coverage.history.modules.intrinsic = value.coverage.history.modules.context = { current: 636, refresh: 0, new: 0 };
  value.semantic.taxonomy.current = { source: "reused_taxonomy_proposal", stored_reviews: 0, validation: {} };
  await open(page, value);
  await expect(page.locator('[data-step="taxonomy_proposal"] .workflow-status')).toHaveText("Complete");
  await expect(page.locator('[data-step="taxonomy_proposal"]')).toContainText("Saved proposal reused");
  await expect(page.locator('[data-step="taxonomy_review"]')).toContainText("1 / 2 saved passes");
  await page.locator('[data-step="taxonomy_review"]').click();
  await expect(page.locator("#workflow-detail")).toContainText("For the current source: 0 / 2 passes ready");
});

test("a scan awaiting reuse checks retains file counts without claiming current coverage", async ({ page }) => {
  const value = updatedProgress();
  value.coverage.scopes = {};
  value.coverage.history.modules = {
    intrinsic: { current: 0, refresh: 0, new: 0 }, context: { current: 0, refresh: 0, new: 0 },
    reuse_pending: true, previous_snapshot_id: 42, saved: { intrinsic: 634, context: 634 },
  };
  await open(page, value);
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("634 saved files");
  await expect(page.locator('[data-step="context"]')).toContainText("New scan · reuse check pending");
  await expect(page.locator('[data-step="context"] .workflow-status')).toHaveText("Needs update");
  await expect(page.locator("#workflow-run-note")).toContainText("first checks which ones are still current");
});
