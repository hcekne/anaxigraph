import { expect, test } from "@playwright/test";

test("file inventory pages on demand and reports the global matching count", async ({ page }) => {
  const requested = [];
  await page.route("**/api/graph/entities?*", async route => {
    const query = new URL(route.request().url()).searchParams, offset = Number(query.get("offset") || 0);
    requested.push(offset);
    return route.fulfill({ json: { context: { repository_id: 1, snapshot_id: 1, revision: "inventory-fixture" },
      nodes: Array.from({ length: offset ? 1 : 100 }, (_, index) => ({ id: `module:pkg/file_${offset + index}.py`, kind: "module", label: `file_${offset + index}`, path: `pkg/file_${offset + index}.py`, overview: "One saved sentence.", metrics: { lines_of_code: 5 } })),
      edges: [], total_nodes: 251, returned_nodes: offset ? 1 : 100, next_offset: offset ? null : 100,
    } });
  });
  await page.goto("/#modules");
  await expect(page.locator("#module-result-count")).toContainText("100 shown · 251 matching modules");
  expect(requested).toEqual([0]);
  await page.locator("#module-next").click();
  await expect(page.locator("#module-result-count")).toContainText("1 shown · 251 matching modules");
  expect(requested).toEqual([0, 100]);
  await expect(page.locator(".module-row")).toHaveCount(1);
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
