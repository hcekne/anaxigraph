import { expect, test } from "@playwright/test";

test("Changes shows the shared calibrated architecture reassessment", async ({ page }) => {
  await page.route("**/api/reassessment**", async (route) => {
    await route.fulfill({ json: reassessmentResult() });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Changes", exact: true }).click();

  const panel = page.locator("#architecture-reassessment");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("What changed—and should the architecture change with it?");
  const changed = panel.locator(".reassessment-comparison span").nth(2);
  await expect(changed.locator("strong")).toHaveText("1");
  await expect(changed.locator("small")).toHaveText("Changed files");
  await expect(panel).toContainText("Only affected AI descriptions");
  await expect(panel.locator(".reassessment-effect")).toHaveCount(2);
  await expect(panel).toContainText("Why it may matter");
  await expect(panel).toContainText("Counter-evidence");
  await expect(panel).toContainText("Reasons to leave it alone");
  await expect(panel).toContainText("Smallest safe next step");
  await expect(panel).toContainText("Advice, not an automatic edit");
});

function reassessmentResult() {
  return {
    contract_version: "architecture-reassessment-v1",
    identity: "architecture-reassessment-v1:fixture",
    state: "semantic_refresh_pending",
    baseline_snapshot: { id: 20, commit_sha: "1111111111111111" },
    target_snapshot: { id: 21, commit_sha: "2222222222222222" },
    evidence_work: { changed_modules: 1, affected_context_modules: 3 },
    semantic_refresh: {
      enabled: true,
      semantically_ready: false,
      changed_modules: ["src/service.py"],
      affected_modules: ["src/api.py", "tests/test_service.py"],
      affected_groups: ["application/services"],
      full_repository_rerun_required: false,
    },
    architectural_effects: [
      effect("complexity", "worsened", "Measured complexity rose from 5 to 9."),
      effect("pattern_fit", "opportunity", "A reviewed adapter pattern may fit here."),
    ],
    safety: { automatic_code_changes: false },
    plain_language: {
      conclusion: "One changed file increased complexity while its bounded meaning refresh continues.",
    },
  };
}

function effect(category, classification, observation) {
  return {
    category,
    classification,
    subject: "src/service.py",
    observed_change: observation,
    architectural_consequence: "The service may be harder to change safely.",
    recommendation: "Test one cohesive extraction before adding another abstraction.",
    confidence: { score: 0.8, label: "high", basis: "fixture" },
    counter_evidence: ["The decision paths may form one coherent protocol."],
    reasons_to_leave_alone: ["Do not split cohesive policy solely to lower a score."],
    smallest_safe_follow_up: "Review the changed decision paths and focused tests.",
    verification: "Run focused tests and refresh the map.",
  };
}
