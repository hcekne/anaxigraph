import { expect, test } from "@playwright/test";

test("finding handoff explains when a structural problem appeared and returned", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Agents", exact: true }).click();

  await page.evaluate(async () => {
    const controller = await import("/assets/finding-controller.js");
    controller.renderFindingHandoff({
      workflow_note: "This finding has been selected for agent work.",
      risk: "medium",
      finding: {
        id: 17,
        status: "planned",
        severity: "warning",
        confidence: 1,
        affected_artifacts: ["src/service.py"],
        plain_language: {
          what: "Two files depend on one another in a loop.",
          facts: ["service.py imports adapter.py, which imports service.py."],
          why_it_matters: "A change can travel around the loop.",
          next_step: "Move the shared contract to one clear owner.",
          when_no_change_may_be_needed: [],
          how_to_check: "Scan again and confirm the loop is gone.",
          priority: { guidance: "Check this before nearby cleanup." },
        },
      },
      finding_history: {
        state: "regressed",
        plain_language: {
          conclusion: "This problem disappeared by Remove cycle (22222222) but returned by Restore old import (33333333).",
          limits: "This compares retained code maps, not every Git commit.",
        },
        transitions: [
          { kind: "introduced", frame: { label: "Introduce cycle (11111111)" } },
          { kind: "resolved", frame: { label: "Remove cycle (22222222)" } },
          { kind: "regressed", frame: { label: "Restore old import (33333333)" } },
        ],
      },
      recommended_context: ["src/service.py", "src/adapter.py"],
      relevant_tests: ["tests/test_service.py"],
      protected_paths: [],
      verification: ["Run the focused tests."],
      scope: { active_branch_conflicts: [] },
      agent_prompt: "Fix the dependency loop without changing behavior.",
    });
  });

  const result = page.locator("#agent-result");
  await expect(result).toContainText("History of this problem");
  await expect(result).toContainText("disappeared by Remove cycle");
  await expect(result).toContainText("Appeared by Introduce cycle");
  await expect(result).toContainText("Gone by Remove cycle");
  await expect(result).toContainText("Returned by Restore old import");
  await expect(result).toContainText("not every Git commit");
});
