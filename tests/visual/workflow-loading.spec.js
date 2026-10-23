import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

test("loading popup is visible before repository selection and until workflow counts arrive", async ({ page }, testInfo) => {
  let selectRepository, showProgress;
  const repositories = new Promise(resolve => { selectRepository = resolve; });
  const progress = new Promise(resolve => { showProgress = resolve; });
  await page.route("**/api/repositories", async route => { await repositories; await route.continue(); });
  await page.route("**/api/workflows?*", async route => { await progress; await route.fulfill({ json: configuredProgress() }); });
  try {
    await page.goto("/#workflows/mapping");
    const popup = page.locator("#workflow-loading");
    await expect(popup).toBeVisible();
    await expect(popup).toContainText("Loading repository map");
    await expect(popup.locator(".workflow-load-spinner")).toBeVisible();
    await expect(page.locator("#workflow-run-controls")).toBeHidden();
    for (const [width, height] of [[1280, 720], [390, 844]]) {
      await page.setViewportSize({ width, height });
      const box = await popup.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      expect(box.y + box.height).toBeLessThanOrEqual(height);
      await page.screenshot({ path: testInfo.outputPath(`loading-${width}.png`) });
    }
    selectRepository();
    await expect(page.locator("#project-name")).not.toHaveText("Loading…");
    await expect(popup).toBeVisible();
    await expect(page.locator("#workflow-diagram")).toHaveAttribute("aria-busy", "true");
    showProgress();
    await expect(page.locator(".workflow-node")).toHaveCount(8);
    await expect(popup).toBeHidden();
    await expect(page.locator("#workflow-diagram")).toHaveAttribute("aria-busy", "false");
    await expect(page.locator("#workflow-run-controls")).toBeVisible();
  } finally { selectRepository(); showProgress(); await page.unrouteAll({ behavior: "wait" }); }
});

test("manual refresh shows a popup while background polling keeps the map interactive", async ({ page }) => {
  const value = configuredProgress();
  await open(page, value);
  let release, waiting = false;
  let held = new Promise(resolve => { release = resolve; });
  await page.route("**/api/workflows?*", async route => {
    waiting = true;
    await held;
    await route.fulfill({ json: value });
  });
  try {
    await page.locator("#workflow-refresh").click();
    await expect(page.locator("#workflow-loading")).toBeVisible();
    await expect(page.locator('[data-run-step="groups"]')).toBeDisabled();
    release();
    await expect(page.locator("#workflow-loading")).toBeHidden();
    await expect(page.locator('[data-run-step="groups"]')).toBeEnabled();
    waiting = false;
    held = new Promise(resolve => { release = resolve; });
    await expect.poll(() => waiting).toBe(true);
    await expect(page.locator("#workflow-loading")).toBeHidden();
    await page.locator('[data-configure-step="groups"]').click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog").locator('[name="model"]')).toBeEnabled();
  } finally { release(); await page.unrouteAll({ behavior: "wait" }); }
});

test("failed progress stops the spinner and offers a working retry", async ({ page }) => {
  await page.addInitScript(() => {
    window.__testWorkflowRetry = false;
    document.addEventListener("click", event => {
      if (event.target.closest("#workflow-load-retry")) window.__testWorkflowRetry = true;
    }, true);
  });
  await page.route("**/api/workflows?*", async route => route.fulfill(!await page.evaluate(() => window.__testWorkflowRetry)
    ? { status: 503, json: { detail: "Saved progress is temporarily unavailable" } }
    : { json: configuredProgress() }));
  await page.goto("/#workflows/mapping");
  const popup = page.locator("#workflow-loading");
  await expect(popup).toContainText("Couldn’t load workflow progress");
  await expect(popup).toContainText("Saved progress is temporarily unavailable");
  await expect(popup.locator(".workflow-load-spinner")).toBeHidden();
  await expect(page.locator("#workflow-diagram")).toHaveAttribute("aria-busy", "false");
  await popup.getByRole("button", { name: "Retry loading" }).click();
  await expect(popup).toBeHidden();
  await expect(page.locator(".workflow-node")).toHaveCount(8);
});

test("repository discovery failure also stops the loading popup and can be retried", async ({ page }) => {
  let failed = true;
  await page.route("**/api/repositories", route => failed
    ? route.fulfill({ status: 503, json: { detail: "Repositories are temporarily unavailable" } })
    : route.continue());
  await page.goto("/#workflows/mapping");
  const popup = page.locator("#workflow-loading");
  await expect(popup).toContainText("Repositories are temporarily unavailable");
  await expect(popup.locator(".workflow-load-spinner")).toBeHidden();
  failed = false;
  await popup.getByRole("button", { name: "Retry loading" }).click();
  await expect(page.locator(".workflow-node")).toHaveCount(8);
  await expect(popup).toBeHidden();
});
