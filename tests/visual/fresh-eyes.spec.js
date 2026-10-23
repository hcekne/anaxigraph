import { expect, test } from "@playwright/test";
import { freshReview } from "./semantic-review-fixture.js";
import { configuredProgress } from "./workflow-fixture.js";

async function openFresh(page, value = freshReview()) {
  await page.route("**/api/fresh-eyes?*", route => route.fulfill({ json: value }));
  await page.goto("/#fresh-eyes");
  await expect(page.locator("#fresh-eyes-summary")).toContainText("alternatives saved");
}

test("Fresh Eyes preserves independent alternatives, their provenance and functional trade-offs", async ({ page }) => {
  const value = freshReview();
  value.scope_reviews[0].alternatives.forEach((item, index) => { item.provenance = { executor_model: index === 1 ? "claude-opus-5-5" : "gpt-6.1-sol" }; });
  await openFresh(page, value);
  await expect(page.locator("#fresh-eyes-alternatives > [data-fresh-alternative]")).toHaveCount(3);
  await expect(page.locator("#fresh-eyes-alternatives")).toContainText("claude-opus-5-5");
  await expect(page.locator("#fresh-eyes-alternatives")).toContainText("gpt-6.1-sol");
  await expect(page.locator("#fresh-eyes-comparison")).toContainText("Several useful designs remain");
  await expect(page.locator("#fresh-eyes-start")).toHaveCount(0);
});

test("failed Fresh Eyes work resumes through the shared workflow controls", async ({ page }) => {
  const value = freshReview(); value.state = "failed"; value.ready = false; value.counts.retained_alternatives = 8;
  const progress = configuredProgress(); progress.fresh_eyes = value;
  let posted;
  await page.route("**/api/workflows?*", route => route.fulfill({ json: progress }));
  await page.route("**/api/workflows/run", route => { posted = route.request().postDataJSON(); return route.fulfill({ json: { status: "started" } }); });
  await openFresh(page, value);
  await page.locator("#fresh-eyes-open-workflow").click();
  await expect(page.locator("#workflow-tab-fresh-eyes")).toHaveAttribute("aria-selected", "true");
  await page.locator("#workflow-run-button").click();
  await expect.poll(() => posted?.workflow).toBe("fresh-eyes");
  expect(posted.use_step_settings).toBe(true);
  expect(posted.restart).toBe(false);
});

test("different executor models remain visible without presenting them as verified agreement", async ({ page }) => {
  const value = freshReview();
  value.scope_reviews[0].alternatives[0].provenance = { executor_model: "gpt-6.1-sol" };
  value.scope_reviews[0].alternatives[1].provenance = { executor_model: "claude-opus-5-5" };
  await openFresh(page, value);
  await expect(page.locator("#fresh-eyes-isolation")).toContainText("Unverified");
  await expect(page.locator("#fresh-eyes-alternatives")).toContainText("gpt-6.1-sol");
  await expect(page.locator("#fresh-eyes-alternatives")).toContainText("claude-opus-5-5");
  await expect(page.locator("#fresh-eyes-alternatives")).not.toContainText("providers agree");
});

test("mapping provenance identifies a dirty checkout without claiming Fresh Eyes read source", async ({ page }) => {
  const value = freshReview(); value.snapshot = { dirty: true, working_tree_fingerprint: "f".repeat(64) };
  await openFresh(page, value);
  await expect(page.locator(".fresh-eyes-warning")).toContainText("dirty checkout");
  await expect(page.locator(".fresh-eyes-warning")).toContainText("working-tree fingerprint ffffffffffff");
  await expect(page.locator(".fresh-eyes-warning")).toContainText("functional brief revision");
  value.snapshot.dirty = false;
  await page.locator("#fresh-eyes-refresh").click();
  await expect(page.locator(".fresh-eyes-warning")).toHaveCount(0);
});

test("optional target steering belongs in Planning and does not erase Fresh Eyes alternatives", async ({ page }) => {
  await page.route("**/api/workflows?*", route => route.fulfill({ json: configuredProgress() }));
  await openFresh(page);
  await page.locator("#fresh-eyes-open-planning").click();
  await expect(page.locator("#architecture-direction")).toBeVisible();
  await expect(page.locator("#architecture-direction")).toHaveValue("");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();
  await expect(page.locator("#fresh-eyes-alternatives > [data-fresh-alternative]")).toHaveCount(3);
});

test("partially completed scopes retain their saved alternatives", async ({ page }) => {
  const value = freshReview(); value.ready = false; value.state = "in_progress";
  value.counts.retained_alternatives = 8;
  value.scope_reviews[0].alternatives.pop();
  await openFresh(page, value);
  await expect(page.locator("#fresh-eyes-alternatives > [data-fresh-alternative]")).toHaveCount(2);
  await expect(page.locator("#fresh-eyes-alternatives")).toContainText("Not saved yet");
  await expect(page.locator("#fresh-eyes-summary")).toContainText("8 / 9 alternatives saved");
});

test("recorded generations are readable without independent execution controls", async ({ page }) => {
  const value = freshReview(); value.generations = [{ generation: 1 }, { generation: 2 }]; value.review_generation = 2;
  const queries = [];
  await page.route("**/api/fresh-eyes?*", route => { queries.push(new URL(route.request().url()).searchParams.get("generation")); return route.fulfill({ json: value }); });
  await page.goto("/#fresh-eyes");
  await expect(page.locator("#fresh-eyes-summary")).toContainText("alternatives saved");
  await page.locator("#fresh-eyes-generation").selectOption("1");
  await expect.poll(() => queries.includes("1")).toBe(true);
  await expect(page.locator("#fresh-eyes-start")).toHaveCount(0);
});

test("two functional generations retain their three alternatives side by side", async ({ page }) => {
  const value = freshReview(); value.generations = [{ generation: 1 }, { generation: 2 }]; value.review_generation = 2;
  await page.route("**/api/fresh-eyes?*", route => {
    const old = new URL(route.request().url()).searchParams.get("generation") === "1";
    return route.fulfill({ json: { ...value, functional_brief: { ...value.functional_brief, revision: old ? "old-brief" : "new-brief" } } });
  });
  await page.goto("/#fresh-eyes");
  await expect(page.locator("#fresh-eyes-summary")).toContainText("alternatives saved");
  await page.locator("#fresh-eyes-compare").selectOption("1");
  await expect(page.locator("#fresh-eyes-compare-panel")).toContainText("old-brief");
  await expect(page.locator("#fresh-eyes-compare-panel [data-fresh-alternative]")).toHaveCount(3);
  await expect(page.locator("#fresh-eyes-alternatives > [data-fresh-alternative]")).toHaveCount(3);
});

test("same-generation comparison explains why it cannot establish agreement", async ({ page }) => {
  const value = freshReview(); value.generations = [{ generation: 1 }, { generation: 2 }]; value.review_generation = 2;
  await openFresh(page, value);
  await page.locator("#fresh-eyes-compare").selectOption("2");
  await expect(page.locator("#fresh-eyes-compare-panel")).toContainText("Comparing a generation with itself does not establish agreement");
});

test("three alternative diagrams and long descriptions fit desktop and phone", async ({ page }, testInfo) => {
  const value = freshReview();
  value.scope_reviews[0].alternatives[0].pros = ["A long description of one option with important obligations and trade-offs that should wrap without losing meaning."];
  await openFresh(page, value);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await expect(page.locator("#fresh-eyes-alternatives > [data-fresh-alternative]")).toHaveCount(3);
    await page.screenshot({ path: testInfo.outputPath(`functional-alternatives-${width}.png`), fullPage: true });
  }
});
