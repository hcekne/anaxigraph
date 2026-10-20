import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

test("all eight mapping cards fit in a focused laptop viewport", async ({ page }, testInfo) => {
  const value = configuredProgress();
  value.execution.max_parallel_jobs = 32;
  value.settings.steps.intrinsic = [
    { provider: "codex", model: "gpt-6-luna", workers: 16, reasoning_effort: "medium" },
    { provider: "claude", model: "claude-haiku-5-5", workers: 16, reasoning_effort: "medium" },
  ];
  value.coverage.scopes.module.total = 628;
  value.semantic.worker = { status: "running", workflow: "mapping", step: "intrinsic", settings: value.settings.steps };
  value.coverage.workers = [{ job_kind: "intrinsic", scope_type: "module", executor_model: "gpt-6-luna", running: 16 }];
  await open(page, value);
  await expect(page.locator(".workflow-legend, .workflow-owner, .workflow-node .workflow-next-run, .workflow-node .workflow-models")).toHaveCount(0);
  await expect(page.locator(".workflow-node-top").nth(0)).toHaveText("1 Scan the source");
  await expect(page.locator(".workflow-node-top").nth(1)).toHaveText("2 Describe each file");
  for (const [width, height] of [[1280, 720], [1366, 768], [1440, 900]]) {
    await page.setViewportSize({ width, height });
    await page.locator("#workflow-focus").click();
    await expect.poll(() => page.locator(".workflow-card").evaluateAll(cards => cards.every(card => {
      const box = card.getBoundingClientRect();
      return box.top >= 60 && box.bottom <= innerHeight && box.left >= 0 && box.right <= innerWidth;
    }))).toBe(true);
    const heightOfMap = (await page.locator("#workflow-diagram").boundingBox()).height;
    expect(heightOfMap).toBeLessThan(height - 72);
    await page.screenshot({ path: testInfo.outputPath(`focused-map-${width}.png`) });
  }
});

test("configure another step while running, save it and preserve the active run choices", async ({ page }) => {
  const value = configuredProgress();
  value.semantic.worker = { status: "running", workflow: "mapping", step: "intrinsic", settings: structuredClone(value.settings.steps) };
  value.coverage.workers = [{ job_kind: "intrinsic", scope_type: "module", executor_model: "gpt-6-luna", running: 4 }];
  let saved, starts = 0;
  await page.route("**/api/workflows/settings", async route => {
    saved = route.request().postDataJSON();
    value.settings.steps[saved.step] = saved.workers;
    value.settings.customized = [saved.step];
    await route.fulfill({ json: { repository_id: 1, settings: value.settings } });
  });
  await page.route("**/api/workflows/run", route => { starts += 1; return route.fulfill({ json: { status: "started" } }); });
  await open(page, value);
  await page.locator("#workflow-focus").click();
  await page.locator('[data-configure-step="context"]').click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAccessibleName("3. Add context");
  const scroll = await page.evaluate(() => scrollY);
  await dialog.getByRole("button", { name: "Add model", exact: true }).click();
  await expect(dialog.locator(".workflow-worker-row")).toHaveCount(2);
  expect(await dialog.getByRole("button", { name: "Save & run step →", exact: true }).isDisabled()).toBe(false);
  await dialog.getByRole("button", { name: "Remove model 2", exact: true }).click();
  expect(await dialog.getByRole("button", { name: "Save & run step →", exact: true }).isDisabled()).toBe(false);
  const model = dialog.locator('[name="model"]');
  await expect(model).toBeEnabled();
  await model.selectOption("gpt-6.1-sol");
  await dialog.locator('[name="workers"]').fill("2");
  await expect(dialog.getByRole("button", { name: "Save settings", exact: true })).toBeEnabled();
  await expect(dialog.getByRole("button", { name: "Save & run step →", exact: true })).toBeEnabled();
  await expect(dialog.getByRole("button", { name: "Try 2 jobs", exact: true })).toBeEnabled();
  await model.focus();
  await page.waitForResponse(response => response.url().includes("/api/workflows?"));
  await expect(model).toBeFocused();
  await expect(model).toHaveValue("gpt-6.1-sol");
  await dialog.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(saved).toMatchObject({ step: "context", workers: [{ model: "gpt-6.1-sol", workers: 2 }] });
  expect(starts).toBe(0);
  expect(Math.abs(await page.evaluate(() => scrollY) - scroll)).toBeLessThan(2);
  await expect(page.locator('[data-configure-step="context"]')).toBeFocused();
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("4 / 4 workers active");
  await page.locator('[data-configure-step="context"]').click();
  await expect(model).toHaveValue("gpt-6.1-sol");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});

test("completed coverage stays complete while the run is finishing", async ({ page }) => {
  const value = configuredProgress();
  value.semantic.worker = { status: "running", workflow: "mapping", step: "intrinsic", active_step: "intrinsic" };
  value.coverage.scopes.module.intrinsic = value.coverage.scopes.module.total;
  value.semantic.jobs = { running_live: 0 };
  await open(page, value);
  const node = page.locator('[data-step="intrinsic"]');
  await expect(node).toContainText("12 / 12 files");
  await expect(node.locator(".workflow-status")).toHaveText("Complete");
  await expect(node.locator(".workflow-spinner")).toHaveCount(0);
  await expect(node).not.toContainText("Preparing jobs");
  await expect(page.locator("#workflow-message")).toContainText("Results saved · finishing");
  await expect(page.locator('[data-run-step="context"]')).toBeEnabled();
  value.semantic.worker.status = "complete";
  await page.locator("#workflow-refresh").click();
  await expect(page.locator('[data-run-step="context"]')).toBeEnabled();
});

test("popup keeps drafts, traps focus and fits a phone without scrolling the page", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, configuredProgress());
  await page.locator('[data-configure-step="context"]').click();
  const dialog = page.getByRole("dialog");
  const scroll = await page.evaluate(() => scrollY);
  await dialog.locator('[name="workers"]').fill("3");
  for (let i = 0; i < 18; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
  }
  const box = await dialog.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  expect(box.y + box.height).toBeLessThanOrEqual(844);
  await page.screenshot({ path: testInfo.outputPath("phone-settings-modal.png") });
  await page.keyboard.press("Escape");
  expect(Math.abs(await page.evaluate(() => scrollY) - scroll)).toBeLessThan(2);
  await page.locator('[data-configure-step="context"]').click();
  await expect(dialog.locator('[name="workers"]')).toHaveValue("3");
  await dialog.getByRole("tab", { name: "Progress & models" }).click();
  await expect(dialog.locator("#workflow-detail")).toContainText("Next run");
  await page.keyboard.press("ArrowRight");
  await expect(dialog.getByRole("tab", { name: "Configure", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(dialog.locator('[name="workers"]')).toHaveValue("3");
});
