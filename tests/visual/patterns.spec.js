import { expect, test } from "@playwright/test";

const scores = {
  applicability: 82,
  suitability: 91,
  conformance: 24,
  opportunity: 88,
  confidence: 86,
  benefit: 84,
  urgency: 62,
  execution_safety: 73,
  migration_cost: 37,
};

function patternItem(includeEvidence) {
  const item = {
    target: {
      key: "module:src/anaxigraph/storage.py",
      level: "module",
      label: "storage.py",
      path: "src/anaxigraph/storage.py",
      qualified_name: "",
    },
    pattern: {
      key: "strategy",
      name: "Strategy",
      family: "object_interface",
      kind: "constructive",
      version: 1,
    },
    candidate: { priority: 81, selection_reasons: ["supporting_evidence"] },
    presence: "partial",
    recommendation: "improve_conformance",
    summary: "The provider boundary already resembles Strategy but its selection policy leaks.",
    rationale: "Multiple implementations share a stable behavioral boundary.",
    scores,
    evidence_count: 2,
    counter_evidence_count: 1,
    review: {
      verdict: "approve",
      summary: "Independent critique found the scope and evidence proportionate.",
      confidence: 89,
      issue_counts: {},
      competing_interpretation_count: 0,
    },
    provenance: {
      provider: "agent",
      model: "runtime-test-model",
      created_at: "2026-08-25T12:00:00+00:00",
    },
  };
  if (includeEvidence) {
    item.details = {
      evidence: ["Three providers implement the same execution contract."],
      counter_evidence: ["The current selector has one repository-specific branch."],
      alternatives: ["adapter"],
      prerequisites: ["Preserve provider error semantics."],
      risks: ["An extra abstraction could hide simple policy."],
      review_issues: [],
    };
  }
  return item;
}

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator(".group-family").first()).toBeVisible();
}

test("pattern intelligence explores finalized results in both directions", async ({ page }) => {
  const requests = [];
  await page.route("**/api/patterns**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.searchParams);
    const includeEvidence = url.searchParams.get("include_evidence") === "true";
    await route.fulfill({
      json: {
        contract_version: "pattern-query-v1",
        repository_id: 1,
        snapshot_id: 7,
        filters: {
          target: url.searchParams.get("target") || "",
          pattern: url.searchParams.get("pattern") || "",
          sort_by: url.searchParams.get("sort_by") || "opportunity",
        },
        total: 1,
        returned: 1,
        offset: 0,
        next_offset: null,
        omitted: 0,
        items: [patternItem(includeEvidence)],
      },
    });
  });

  await openDashboard(page);
  await page.getByRole("button", { name: "Patterns", exact: true }).click();

  await expect(page.locator("#view-patterns")).toBeVisible();
  await expect(page.locator(".pattern-result-card")).toContainText("Strategy");
  await expect(page.locator(".pattern-result-card")).toContainText("Independent critique");
  await expect(page.locator(".pattern-score")).toHaveCount(9);
  await expect(page.locator("#pattern-query-summary")).toContainText(
    "current, independently critiqued",
  );

  await page.locator("#pattern-target-filter").fill("src/anaxigraph/storage.py");
  await page.locator("#patterns-query-form").getByRole("button", {
    name: "Query finalized evaluations",
  }).click();
  await expect.poll(() => requests.at(-1).get("target")).toBe("src/anaxigraph/storage.py");

  await page.getByRole("button", { name: "Find this pattern elsewhere" }).click();
  await expect(page.locator("#pattern-key-filter")).toHaveValue("strategy");
  await expect(page.locator("#pattern-target-filter")).toHaveValue("");
  await expect.poll(() => requests.at(-1).get("pattern")).toBe("strategy");

  await page.locator("#pattern-include-evidence").check();
  await page.locator("#patterns-query-form").getByRole("button", {
    name: "Query finalized evaluations",
  }).click();
  await expect(page.locator(".pattern-details")).toContainText("Detailed evidence and critique");
  await expect(page.locator(".pattern-details")).toContainText(
    "Three providers implement the same execution contract",
  );
});
