import { expect, test } from "@playwright/test";
import { configuredProgress, open } from "./workflow-fixture.js";

test("desktop workflows keep navigation left, the whole diagram central and run controls right", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, configuredProgress());
  for (const [flow, title, count] of [["mapping", "Mapping", 8], ["patterns", "Pattern analysis", 6], ["fresh-eyes", "Fresh eyes", 7]]) {
    await page.locator(`#workflow-tab-${flow}`).click();
    await expect(page.locator("#workflow-run-title")).toHaveText(title);
    await expect(page.locator(".workflow-node")).toHaveCount(count);
    const left = await page.locator(".workflow-sidebar").boundingBox();
    const map = await page.locator("#workflow-diagram").boundingBox();
    const right = await page.locator("#workflow-run-controls").boundingBox();
    expect(left.x + left.width).toBeLessThan(map.x);
    expect(map.x + map.width).toBeLessThan(right.x);
    expect(Math.abs(right.y - map.y)).toBeLessThan(2);
    expect(Math.abs(left.y - map.y)).toBeLessThan(2);
    expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(1440);
    const boxes = await page.locator(".workflow-card").evaluateAll(cards => cards.map(card => card.getBoundingClientRect().toJSON()));
    expect(boxes.every(box => box.top >= 0 && box.bottom <= 900)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`workspace-${flow}.png`) });
  }
});

test("sidebar supports vertical keyboard navigation and keeps focus during progress updates", async ({ page }) => {
  await open(page, configuredProgress());
  const tabs = page.getByRole("tablist", { name: "Repository workflows" });
  await expect(tabs).toHaveAttribute("aria-orientation", "vertical");
  await page.locator("#workflow-tab-mapping").focus();
  for (const [key, flow] of [["ArrowDown", "patterns"], ["End", "architecture"], ["ArrowUp", "fresh-eyes"], ["Home", "mapping"], ["ArrowUp", "architecture"]]) {
    await page.keyboard.press(key);
    const selected = page.locator(`#workflow-tab-${flow}`);
    await expect(selected).toBeFocused();
    await expect(selected).toHaveAttribute("aria-selected", "true");
    await expect(tabs.locator('[tabindex="0"]')).toHaveCount(1);
    await expect(page.locator("#workflow-panel")).toHaveAttribute("aria-labelledby", `workflow-tab-${flow}`);
  }
  await page.waitForResponse(response => response.url().includes("/api/workflows?"));
  await expect(page.locator("#workflow-tab-architecture")).toBeFocused();
});

test("narrow layouts keep the map readable and all workflow controls reachable", async ({ page }, testInfo) => {
  await open(page, configuredProgress());
  for (const width of [1024, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const map = await page.locator("#workflow-diagram").boundingBox();
    const controls = await page.locator("#workflow-run-controls").boundingBox();
    expect(controls.y).toBeGreaterThanOrEqual(map.y + map.height);
    expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(width);
    await page.locator('[data-configure-step="groups"]').click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.locator("#workflow-run-button").scrollIntoViewIfNeeded();
    await expect(page.locator("#workflow-run-button")).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`workspace-narrow-${width}.png`), fullPage: true });
  }
});
