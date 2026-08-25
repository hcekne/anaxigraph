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
      task_path: {
        area: {
          key: "product",
          name: "Product behavior",
          responsibility: "Own behavior people use directly.",
          why_grouped: "These files deliver user-facing behavior.",
        },
        subsystem: {
          key: "dashboard",
          name: "Browser dashboard",
          responsibility: "Show repository guidance in the browser.",
          why_grouped: "These files build the same browser workflow.",
        },
        module: {
          path: "src/anaxigraph/dashboard/finding-controller.js",
          responsibility: "Show focused coding-agent advice.",
          contracts_to_preserve: ["The scope result remains readable."],
          extension_points: ["renderAgentResult"],
          callers_to_check: ["src/anaxigraph/dashboard/app.js"],
          dependencies_to_check: ["src/anaxigraph/dashboard/findings-view.js"],
          focused_tests: ["tests/visual/agent-scope.spec.js"],
        },
        symbols: [{
          name: "renderAgentResult",
          signature: "renderAgentResult(value, kind)",
        }],
        nearby_files: [{
          path: "tests/visual/agent-scope.spec.js",
          reason: "checks this route",
        }],
        plain_language: {
          conclusion: "Follow the dashboard route to renderAgentResult.",
        },
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
      decomposition: {
        items: [{
          path: "src/anaxigraph/dashboard/finding-controller.js",
          status: "candidate",
          plain_language: {
            conclusion: "Test a two-part split; do not move everything at once.",
            reasons_not_to_split: ["The jobs still share the same browser state."],
            how_to_check: ["Run the focused browser contract after each step."],
          },
          slices: [{
            job: "Render agent advice",
            symbols: [{ name: "renderAgentResult" }, { name: "architectureDecisionMarkup" }],
            destination: { path: "src/anaxigraph/dashboard/agent-view.js" },
          }],
        }],
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
  await expect(result).toContainText("Task path through the code map");
  await expect(result).toContainText(
    "Product behavior → Browser dashboard → src/anaxigraph/dashboard/finding-controller.js",
  );
  await expect(result).toContainText("renderAgentResult(value, kind)");
  await expect(result).toContainText("Own behavior people use directly");
  await expect(result).toContainText("These files build the same browser workflow");
  await expect(result).toContainText("The scope result remains readable");
  await expect(result).toContainText("Called by src/anaxigraph/dashboard/app.js");
  await expect(result).toContainText("Where to start");
  await expect(result).toContainText("What to preserve");
  await expect(result).toContainText("How to verify it");
  await expect(result).toContainText("Should this large file be split?");
  await expect(result).toContainText("Test a two-part split");
  await expect(result).toContainText("Render agent advice");
  await expect(result).toContainText("renderAgentResult");
  await expect(result).toContainText("Why keeping it together may be better");
  await expect(result).not.toContainText("/100");
  await expect(result).not.toContainText("% confidence");
});
