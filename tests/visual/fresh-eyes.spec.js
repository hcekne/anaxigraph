import { expect, test } from "@playwright/test";

test("fresh-eyes review shows stage provenance and only final ranked advice", async ({ page }) => {
  await page.route("**/api/fresh-eyes**", async (route) => {
    await route.fulfill({ json: reviewResult() });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();

  await expect(page.locator("#view-fresh-eyes")).toBeVisible();
  await expect(page.locator("#fresh-eyes-title")).toHaveText("Review complete");
  await expect(page.locator(".fresh-stage.complete")).toHaveCount(5);
  await expect(page.locator(".fresh-recommendation")).toContainText(
    "Consolidate duplicate orchestration",
  );
  await expect(page.locator("#fresh-eyes-details")).toContainText("This is not cross-provider");
});

test("a failed fresh-eyes stage can be retried without changing the recipe", async ({ page }) => {
  let retryRequested = false;
  const failed = {
    ...reviewResult(),
    state: "failed",
    ready: false,
    recommendations: [],
    stages: [{ key: "proposal:a", label: "Independent proposal A", state: "failed", reason: "Invalid result" }],
    next_action: "Retry the failed proposal task through the semantic executor.",
  };
  await page.route("**/api/fresh-eyes**", async (route) => {
    if (route.request().method() === "POST") {
      retryRequested = route.request().postDataJSON().retry_failed === true;
      await route.fulfill({ json: { status: "already_started", review: { ...failed, state: "in_progress" } } });
      return;
    }
    await route.fulfill({ json: failed });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();

  const retry = page.getByRole("button", { name: "Retry failed stage", exact: true });
  await expect(retry).toBeEnabled();
  await expect(page.locator("#fresh-eyes-proposal-count")).toBeDisabled();
  await retry.click();
  await expect.poll(() => retryRequested).toBe(true);
});

function reviewResult() {
  return {
    contract_version: "fresh-eyes-review-v1",
    identity: "fresh-eyes-review-v1:1:2:abc",
    state: "current",
    ready: true,
    stages: [
      stage("proposal:a", "Independent proposal A"),
      stage("proposal:b", "Independent proposal B"),
      stage("adjudication", "Blind adjudication"),
      stage("comparison", "As-built comparison"),
      stage("review", "Mission filter and ranked strategy"),
    ],
    proposals: [{}, {}],
    adjudication: { disagreements: [{ topic: "Boundary", adjudication: "Keep it small" }] },
    strategy: {
      summary: "Keep the sound boundary and simplify one duplicate flow.",
      rejected_ideas: [{ idea: "Workflow engine", reason: "The fixed recipe does not need one." }],
    },
    recommendations: [{
      rank: 1,
      title: "Consolidate duplicate orchestration",
      action: "consolidate",
      confidence: 0.81,
      smallest_change: "Route both callers through one durable path.",
      expected_benefit: "Less code and one behavior to verify.",
      reasons_not_to_proceed: ["Keep both paths if retry behavior differs."],
      verification: ["Run semantic lifecycle tests."],
    }],
    diversity: { proposal_count: 2, cross_provider: false, models: ["fixture-model"] },
    caveats: ["This is not cross-provider agreement."],
    next_action: "Use Guide for a selected change.",
  };
}

function stage(key, label) {
  return { key, label, state: "current", reason: "Complete" };
}
