import { expect, test } from "@playwright/test";

import { freshReview } from "./semantic-review-fixture.js";

test("Fresh Eyes keeps three alternatives per scope and loads selected designs without actual graph access", async ({ page }) => {
  const scopes = [], actualGraphRequests = [];
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/graph")) actualGraphRequests.push(request.url()); });
  await page.route("**/api/fresh-eyes?*", route => {
    const params = new URL(route.request().url()).searchParams;
    scopes.push(Object.fromEntries(params));
    return route.fulfill({ json: freshReview(params.get("scope_id") || "product", params.get("details") === "true") });
  });
  await page.goto("/#fresh-eyes");
  await expect(page.locator("[data-fresh-alternative]")).toHaveCount(3);
  await expect(page.locator("#fresh-eyes-summary")).toContainText("9 / 9 alternatives saved");
  await expect(page.locator("#fresh-eyes-isolation")).toContainText("Unverified");
  await page.locator("#fresh-eyes-scope").selectOption("capture");
  await expect.poll(() => scopes.at(-1)?.scope_id).toBe("capture");
  expect(scopes.at(-1).details).toBe("true");
  await expect(page.locator('[data-fresh-alternative="capture:a"]')).toContainText("capture boundary a");
  await expect(page.locator("[data-fresh-alternative]")).toHaveCount(3);
  await expect(page.locator("#fresh-eyes-comparison")).toContainText("Check parent constraints");
  expect(actualGraphRequests).toHaveLength(0);
  await expect(page.locator("#fresh-eyes-start")).toHaveCount(0);
});

test("Pattern results expose complete catalogue coverage independently from the current page", async ({ page }) => {
  const requested = [];
  await page.route("**/api/patterns/catalogue?*", route => {
    const params = new URL(route.request().url()).searchParams, offset = Number(params.get("offset") || 0);
    requested.push(Object.fromEntries(params));
    return route.fulfill({ json: { catalogue: { fingerprint: "catalogue-revision", expected: 133, considered: 97, rated: 97, reviewed: 97, unresolved: 2, missing: 36, complete: false }, total: 133, returned: 1, next_offset: offset + 25,
      items: [{ pattern: { key: offset ? "composition" : "adapter", name: offset ? "Composition" : "Adapter", family: "structural", intent: "Keep change behind a stable interface" }, state: offset ? "missing" : "unresolved", summary: offset ? "Not assessed" : "Evidence is incomplete", recommendation: "insufficient_evidence", scores: offset ? {} : { suitability: null }, pros: ["May isolate change"], cons: ["Adds indirection"], placements: [] }] } });
  });
  await page.goto("/#patterns");
  await expect(page.locator("#pattern-catalogue-counts")).toContainText("Expected 133");
  await expect(page.locator("#pattern-catalogue-counts")).toContainText("Missing 36");
  await expect(page.locator("#pattern-results")).toContainText("May isolate change");
  await expect(page.locator("#pattern-results")).toContainText("Adds indirection");
  await expect(page.locator("#pattern-results")).toContainText("Unknown");
  await page.locator("#pattern-next").click();
  await expect.poll(() => requested.at(-1)?.offset).toBe("25");
  await expect(page.locator('[data-catalogue-pattern="composition"]')).toContainText("Missing");
  await expect(page.locator("#pattern-catalogue-counts")).toContainText("Missing 36");
});

test("Workflows remains usable while the separate overview is still loading", async ({ page }) => {
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route("**/api/overview?*", async route => { await held; await route.continue(); });
  try {
    await page.goto("/#workflows/mapping");
    await expect(page.locator(".workflow-node")).toHaveCount(8);
    await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.locator("#workflow-run-controls")).toBeVisible();
  } finally { release(); await page.unrouteAll({ behavior: "wait" }); }
});

test("Fresh Eyes reports converged designs and unexplored directions without claiming novelty", async ({ page }) => {
  const value = freshReview();
  value.scope_reviews[0].comparison.diversity = { status: "converged", differences: [], limitations: ["These alternatives repeat the same ownership model."], unexplored_directions: ["Explore event-driven control instead of direct calls."], novelty: "unverified" };
  value.scope_reviews[0].comparison.assessments = [{ alternative_id: "product:a", decomposition: "Same responsibility split", control_flow: "Direct calls", data_ownership: "One state owner", failure_isolation: "One shared failure domain" }];
  value.scope_reviews[0].alternatives[0].design.state_ownership = "Private state owned by the proposed boundary";
  await page.route("**/api/fresh-eyes?*", route => route.fulfill({ json: value }));
  await page.goto("/#fresh-eyes");
  const comparison = page.locator("#fresh-eyes-comparison");
  await expect(comparison).toContainText("Design diversity: Converged");
  await expect(comparison).toContainText("Novelty is unverified");
  await expect(comparison).toContainText("repeat the same ownership model");
  await expect(comparison).toContainText("event-driven control");
  await expect(comparison).toContainText("One shared failure domain");
  await expect(page.locator("[data-fresh-alternative]")).toHaveCount(3);
});
