import { expect, test } from "@playwright/test";

const task = {
  key: "validate-order",
  task: "Find the order validation rule <script>unsafe</script>",
  status: "obstructed",
  obstacle: "The generic helper name hides which order rule it owns.",
  smallest_change: "Name the helper after the order rule.",
  expected_benefit: "A reader can find validation from its domain name.",
  verification: "Check invalid orders before inventory reservation.",
  evidence: ["orders.py::validate_order", `tests/${"order_".repeat(45)}.py`],
  counter_evidence: ["Preserve existing caller compatibility."],
};

async function showDossier(page, value, status = "current") {
  await page.route("**/api/file?**", async (route) => {
    const response = await route.fetch();
    const detail = await response.json();
    detail.semantic_state = { status };
    detail.semantic_dossiers = {
      context: { value },
    };
    await route.fulfill({ response, json: detail });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await page.locator(".module-row").first().click();
  return page.locator(".module-detail-row");
}

async function showAssessment(page, status = "current", tasks = [task]) {
  const panel = await showDossier(page, {
    summary: "Processes orders.",
    understandability: { contract_version: "code-understandability-v1", tasks },
  }, status);
  await expect(panel.getByRole("heading", { name: "Understanding this code without AnaxiGraph" })).toBeVisible();
  return panel;
}

for (const width of [1440, 390]) {
  test(`concise mappings show contracts and evidence in file and graph views at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 });
    const value = {
      summary: "Validates orders before reserving inventory. " + "Preserves caller-visible order behavior. ".repeat(20),
      responsibilities: ["Check order quantities."],
      public_contracts: [
        "Reject quantities < 1 before updating stock.",
        "Reserve all items before confirming an order.",
        "Release reservations when payment fails.",
        "Preserve the caller's idempotency key.",
        "Return the existing order after a duplicate request.",
        "Record the accepted currency without converting it.",
      ],
      evidence: [`orders/${"validation_".repeat(18)}.py::validate_order <script>unsafe</script>`],
      confidence: 0.9,
    };
    const panel = await showDossier(page, value);
    for (const view of [panel, page.locator("#inspector")]) {
      await expect(view.getByRole("heading", { name: "Key behavior callers rely on" })).toBeVisible();
      await expect(view).toContainText(value.public_contracts[0]);
      await expect(view).toContainText(value.public_contracts.at(-1));
      await expect(view).toContainText(value.summary);
      await expect(view).toContainText(value.evidence[0]);
      await expect(view.getByRole("heading", { name: "Patterns that may fit" })).toHaveCount(0);
      await expect(view.getByRole("heading", { name: "Understanding this code without AnaxiGraph" })).toHaveCount(0);
      await expect(view.locator("script")).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
      if (view === panel) await panel.getByRole("button", { name: "Open in graph" }).click();
    }
  });

  test(`file task evidence stays readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 });
    const panel = await showAssessment(page);
    await expect(panel).toContainText("Reader performance has not been measured");
    await expect(panel).toContainText(task.task);
    await expect(panel).toContainText(task.verification);
    await expect(panel).toContainText(task.counter_evidence[0]);
    await expect(panel.locator("script")).toHaveCount(0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
  });
}

test("stale and unassessed tasks cannot appear clear", async ({ page }) => {
  const stale = await showAssessment(page, "pending_context");
  await expect(stale).toContainText("needs a current review");
  await expect(stale).not.toContainText(task.smallest_change);
  await page.unrouteAll({ behavior: "wait" });
  const empty = await showAssessment(page, "current", []);
  await expect(empty).toContainText("No maintenance tasks have been assessed yet");
  await expect(empty).not.toContainText("Appears clear");
});
