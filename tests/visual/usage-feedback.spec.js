import { expect, test } from "@playwright/test";

test("file inventory loads remaining pages without holding up the current views", async ({ page }) => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  await page.route("**/api/overview?*", async route => {
    const response = await route.fetch();
    const value = await response.json();
    value.files = 251;
    await route.fulfill({ json: value });
  });
  await page.route("**/api/modules?*", async route => {
    const response = await route.fetch();
    const items = await response.json();
    const offset = Number(new URL(route.request().url()).searchParams.get("offset") || 0);
    if (offset) await pending;
    const generated = Array.from({ length: offset ? 1 : 250 }, (_, index) => ({
      ...items[0], artifact_id: offset + index + 1, path: `pkg/file_${offset + index}.py`,
      evaluation: { monitored_by_default: true },
    }));
    await route.fulfill({ json: generated });
  });
  try {
    await page.goto("/");
    await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
    await page.getByRole("button", { name: "Understand", exact: true }).click();
    await page.getByRole("button", { name: "Files", exact: true }).click();
    await expect(page.locator("#module-result-count")).toContainText("250 of 251 indexed files loaded");
    release();
    await expect(page.locator("#module-result-count")).toContainText("251 source or test files");
    await expect(page.locator("#module-result-count")).not.toContainText("more loading");
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("agent directions preserve taste, checkout and the pre-edit baseline", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator("#snapshot-label")).toContainText("indexed");
  await expect(page.locator("#snapshot-label")).toContainText("Checkout");
  await page.getByRole("button", { name: "Understand", exact: true }).click();
  await expect(page.locator("#analysis-freshness")).toContainText("Structural scan:");
  await expect(page.locator("#analysis-freshness")).toContainText("AI mapping:");
  await expect(page.locator("#analysis-freshness")).toContainText("Patterns:");
  await expect(page.locator("#analysis-freshness")).toContainText("Fresh Eyes:");
  await page.getByRole("button", { name: "Guide", exact: true }).click();
  await page.locator("#scope-goal").fill("Save prompts using existing storage. One save action; no new settings screen.");
  await page.locator("#scope-focus").fill("Storage service and prompt launcher boundary");
  await page.getByRole("button", { name: "Copy directions for your coding agent" }).click();
  const prompt = await page.evaluate(() => navigator.clipboard.readText());
  expect(prompt).toContain("One save action; no new settings screen.");
  expect(prompt).toContain("Storage service and prompt launcher boundary");
  expect(prompt).toMatch(/from_snapshot_id=\d+/);
  expect(prompt).toContain("ANAXIGRAPH_IMPACT");
});

test("comparison identifies uncommitted phases and pins the chosen baseline", async ({ page }) => {
  const requested = [];
  await page.route("**/api/reassessment**", async route => {
    const baseline = new URL(route.request().url()).searchParams.get("from_snapshot_id");
    requested.push(baseline);
    const snapshot = id => ({ id, commit_sha: "abc123abc123", branch: "feature", dirty: true, content_fingerprint: `phase-${id}`, checkout_path: "/repo/worktree", analysis_timestamp: "2026-10-20T12:00:00Z" });
    await route.fulfill({ json: { state: "deterministic_only", baseline_selection: baseline ? "requested" : "last_compatible_lineage", baseline_snapshot: snapshot(20), target_snapshot: snapshot(22), architectural_effects: [], semantic_refresh: {} } });
  });
  await page.goto("/");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("button", { name: "Changes", exact: true }).click();
  const panel = page.locator("#architecture-reassessment");
  await expect(panel).toContainText("Map #20");
  await expect(panel).toContainText("Map #22");
  await expect(panel).toContainText("/repo/worktree");
  await expect(panel).toContainText("phase-20");
  await page.locator("#reassessment-baseline").selectOption("20");
  await expect.poll(() => requested.at(-1)).toBe("20");
  await expect(panel).toContainText("This baseline stays pinned across refreshes");
});
