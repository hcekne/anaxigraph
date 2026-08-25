import { expect, test } from "@playwright/test";

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
}

test("agent workbench shows the readable architecture recommendation", async ({ page }) => {
  const scope = {
    goal: "Change the dashboard feedback workflow",
    risk: "medium",
    risk_reasons: [],
    primary_files: [{ path: "src/anaxigraph/dashboard/finding-controller.js" }],
    related_files: [],
    protected_files: [],
    tests: ["tests/visual/agent-scope.spec.js"],
    known_findings: [],
    architecture_rules: [],
    active_branch_conflicts: [],
    architecture_decision: {
      plain_language: {
        conclusion: "This recommendation uses current module meaning.",
      },
      placement: {
        plain_language: {
          conclusion: "Start this change in finding-controller.js.",
        },
      },
      change_constraints: {
        plain_language: {
          conclusion: "Preserve the existing task-context response.",
        },
      },
      verification: {
        plain_language: {
          conclusion: "A new scan has not been compared yet.",
          what_to_do: ["Run the focused browser contract, then scan again."],
        },
      },
    },
  };
  await openDashboard(page);
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await expect(page.locator("#view-agents")).toContainText(
    "Goal-specific context for coding agents",
  );
  await page.evaluate(async (value) => {
    const controller = await import("/assets/finding-controller.js");
    controller.renderAgentResult(value, "scope");
  }, scope);

  const result = page.locator("#agent-result");
  await expect(result).toContainText("Where to make the change and how to check it");
  await expect(result).toContainText("What this advice uses");
  await expect(result).toContainText("Where to start");
  await expect(result).toContainText("What to preserve");
  await expect(result).toContainText("How to verify it");
  await expect(result).not.toContainText("/100");
  await expect(result).not.toContainText("% confidence");
});
