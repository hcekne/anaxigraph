import { expect, test } from "@playwright/test";
import { installSemanticFixture, semanticFixture } from "./semantic-graph-fixture.js";

function understandingFixture(readiness = "current") {
  const fixture = semanticFixture(), baseDetail = fixture.detail;
  const obligations = ["Reject quantities < 1 before updating stock.", "Reserve all items before confirming an order.", "Release reservations when payment fails.", "Preserve the caller's idempotency key.", "Return the existing order after a duplicate request.", "Record the accepted currency without converting it."];
  fixture.detail = id => {
    const value = baseDetail(id);
    value.node.readiness = readiness;
    value.node.overview = "Validates orders before reserving inventory.";
    value.node.detail = "Coordinates validation, reservations and payment while preserving caller-visible order behavior.";
    value.node.provenance = { method: "saved annotation", evidence: `orders/${"validation_".repeat(18)}.py::validate_order <script>unsafe</script>` };
    value.contracts = [{ id: "contract:orders#retry", label: "Caller-visible order behavior", overview: "Preserves accepted orders across retries.", properties: { obligations, failures: ["Payment failure releases inventory."], unknowns: ["Runtime-only consumers have not been verified."] } }];
    return value;
  };
  return { fixture, obligations };
}

async function showUnderstanding(page, readiness = "current") {
  const { fixture, obligations } = understandingFixture(readiness);
  await installSemanticFixture(page, fixture);
  await page.goto("/#modules");
  await page.locator('.module-row[data-module-id="module:src/orders.py"]').click();
  const panel = page.locator(".module-detail-row");
  await expect(panel.locator(".entity-detail")).toBeVisible();
  return { panel, obligations };
}

for (const width of [1440, 390]) {
  test(`one saved explanation preserves complete contracts in table and graph at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 });
    const { panel, obligations } = await showUnderstanding(page);
    for (const view of [panel, page.locator("#inspector")]) {
      await expect(view.getByRole("heading", { name: "Contracts and obligations" })).toBeVisible();
      await expect(view).toContainText(obligations[0]);
      await expect(view).toContainText(obligations.at(-1));
      await expect(view).toContainText("Runtime-only consumers have not been verified.");
      await expect(view.locator("script")).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
      if (view === panel) await panel.getByRole("button", { name: "Focus in graph" }).click();
    }
  });

  test(`sentence, paragraph and expandable provenance remain readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1100 });
    const { panel } = await showUnderstanding(page);
    await expect(panel.locator(".entity-overview")).toHaveText("Validates orders before reserving inventory.");
    await expect(panel.locator(".entity-detail")).toContainText("Coordinates validation, reservations and payment");
    await expect(panel.locator(".entity-evidence pre")).toBeHidden();
    await panel.locator(".entity-evidence summary").click();
    await expect(panel.locator(".entity-evidence")).toContainText("<script>unsafe</script>");
    await expect(panel.locator("script")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  });
}

test("structural and stale annotations do not imply verified behavior or a clean bill of health", async ({ page }) => {
  const { panel } = await showUnderstanding(page, "structural");
  await expect(panel).toContainText("semantic annotation not yet saved");
  await expect(panel).toContainText("Runtime-only consumers have not been verified");
  await expect(panel).not.toContainText("Appears clear");
  await expect(panel).not.toContainText("All behavior verified");
});
