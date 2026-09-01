import { expect, test } from "@playwright/test";

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
}

test("agent workbench shows the readable architecture recommendation", async ({ page }) => {
  const scope = {
    contract_version: "architecture-guidance-v1",
    identity: "architecture-guidance-v1:1:fixture",
    intent: "refactor",
    goal: "Change the dashboard feedback workflow",
    risk: "medium",
    risk_reasons: [],
    primary_files: [{ path: "src/anaxigraph/dashboard/finding-controller.js" }],
    related_files: [],
    protected_files: [],
    tests: ["tests/visual/agent-scope.spec.js"],
    known_findings: [],
    architecture_rules: [],
    recommendation: {
      action: "split",
      summary: "Test a bounded responsibility split in the dashboard controller.",
      starting_point: "src/anaxigraph/dashboard/finding-controller.js",
      why: ["The current module owns two separately named jobs."],
      tradeoffs: ["The jobs still share browser state."],
      reasons_not_to_change: ["Keep the module together if the state cannot be separated."],
      migration_cost: "medium",
      confidence: { score: 0.82, label: "high", basis: "semantic_and_reviewed" },
    },
    impact_summary: {
      direct_callers: ["src/anaxigraph/dashboard/app.js"],
      dependencies: ["src/anaxigraph/dashboard/findings-view.js"],
      transitive_candidates: [],
    },
    unknowns: ["Whether another view shares the same state."],
    caveats: ["Runtime-only browser wiring may be absent."],
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
      history_evidence: {
        change_coupling: {
          status: "available",
          plain_language: {
            conclusion: "Two files repeatedly changed in the same commits.",
            limits: "This is a clue, not a source-code link or an instruction to merge files.",
          },
          items: [{
            selected_path: "src/anaxigraph/dashboard/finding-controller.js",
            partner_path: "tests/visual/agent-scope.spec.js",
            plain_language: {
              observation: "The controller and its browser test changed together four times.",
              why_it_may_matter: "Changes here may need the browser behavior checked.",
            },
          }],
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
  await page.getByRole("button", { name: "Guide", exact: true }).click();
  await expect(page.locator("#view-agents")).toContainText(
    "One architecture adviser for people and coding agents",
  );
  await page.evaluate(async (value) => {
    const controller = await import("/assets/finding-controller.js");
    controller.renderAgentResult(value, "scope");
  }, scope);

  const result = page.locator("#agent-result");
  await expect(result).toContainText("Recommendation");
  await expect(result).toContainText("Test a bounded responsibility split");
  await expect(result).toContainText("Reasons to leave the design alone");
  await expect(result).toContainText("82%");
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
  await expect(result).toContainText("Files that often change together");
  await expect(result).toContainText("changed together four times");
  await expect(result).toContainText("not a source-code link");
  await expect(result).toContainText("How to verify it");
  await expect(result).toContainText("Should this large file be split?");
  await expect(result).toContainText("Test a two-part split");
  await expect(result).toContainText("Render agent advice");
  await expect(result).toContainText("renderAgentResult");
  await expect(result).toContainText("Why keeping it together may be better");
  await expect(result).not.toContainText("/100");
  await expect(result).not.toContainText("% confidence");
});

test("dashboard submits actor-neutral guidance through the shared API", async ({ page }) => {
  await openDashboard(page);
  await page.getByRole("button", { name: "Guide", exact: true }).click();
  await page.locator("#scope-goal").fill("Simplify dashboard finding presentation");
  await page.locator("#guidance-intent").selectOption("improve");
  await page.locator("#scope-focus").fill("dashboard findings");

  const responsePromise = page.waitForResponse((response) => (
    response.url().includes("/api/guidance") && response.request().method() === "POST"
  ));
  await page.getByRole("button", { name: "Get architecture guidance" }).click();
  const response = await responsePromise;
  const request = response.request().postDataJSON();
  const guidance = await response.json();

  expect(request.intent).toBe("improve");
  expect(request.focus).toBe("dashboard findings");
  expect(guidance.contract_version).toBe("architecture-guidance-v1");
  await expect(page.locator("#agent-result")).toContainText(guidance.recommendation.summary);
});
