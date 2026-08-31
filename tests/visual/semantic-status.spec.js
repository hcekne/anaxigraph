import { expect, test } from "@playwright/test";

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator(".group-family").first()).toBeVisible();
}

function idleSemanticLanguage(agent = false) {
  return {
    version: "semantic-status-explanation-v2",
    conclusion: "AI mapping is incomplete, and no worker is running right now.",
    progress: "5 of 20 included files have a current AI description of both the file itself and its role in this repository.",
    work_state: "No worker is processing the queue right now. Unfinished work is safely saved and can be resumed, but it will not finish until a worker starts.",
    remaining_work: ["15 file descriptions are unfinished or waiting for a refresh."],
    what_to_do: ["Start a background coding-agent worker and keep it running until the map is complete."],
    how_to_read_progress: [
      "Progress measures included files with complete current descriptions; it is not a grade for the code.",
      "AI mapping writes only to AnaxiGraph's external index; it does not edit repository source.",
      ...(agent ? ["The connected coding agent chooses its runtime model and reasoning effort. AnaxiGraph does not hardcode either one into the saved understanding of the code."] : []),
    ],
  };
}

test("semantic progress and model-backed pattern advice use direct language", async ({ page }) => {
  let semanticPath = "";
  let semanticModule = null;
  const charter = {
    contract_version: "architecture-charter-v1",
    identity: "architecture-charter-v1:1:1:7",
    state: "current",
    complete: true,
    purpose: {
      statement: "Keeps a saved map of the repository for people and coding agents.",
      presented_statement: "Keeps a continuously reviewed map for people and coding agents.",
    },
    capabilities: [{ statement: "Shows how files work together without changing source code." }],
    responsibilities: [{ statement: "Keeps code explanations tied to current evidence." }],
    execution_flows: [{ statement: "A person asks a question and receives a bounded repository explanation." }],
    extension_points: [{ statement: "Add a new code reader through the existing reader interface." }],
    coherence_concerns: [{ statement: "Code links created only while the program runs may be missing." }],
    unknowns: [{ question: "Which runtime-created links are absent?" }],
    conflicts: [],
    declared_context: [{
      statement: "Keeps a continuously reviewed map for people and coding agents.",
      author: "repository owner",
      rationale: "Continuity is part of the intended product behavior.",
    }],
    provenance: { provider: "codex", model: "test-model" },
  };
  await page.route("**/api/overview*", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...await response.json(), architecture_charter: charter } });
  });
  await page.route("**/api/semantic*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fulfill({ json: { status: "started" } });
      return;
    }
    await route.fulfill({
      json: {
        enabled: true,
        state: "pending",
        semantically_ready: false,
        eligible_modules: 20,
        current: 5,
        pending: 15,
        pending_scopes: 0,
        failed: 0,
        failed_scopes: 0,
        excluded: 2,
        coverage: 0.25,
        jobs: { pending: 15 },
        budget: { paused: false },
        worker: { status: "idle" },
        plain_language: idleSemanticLanguage(),
      },
    });
  });
  await page.route("**/api/modules*", async (route) => {
    const response = await route.fetch();
    const modules = await response.json();
    const module = modules.find((item) => item.evaluation?.monitored_by_default !== false);
    semanticPath = module.path;
    module.semantic = {
      ...(module.semantic || {}),
      status: "current",
      pattern_opportunities: [{
        name: "Adapter pattern",
        scope: "module",
        score: 91,
        confidence: 0.88,
        rationale: "Fits the existing provider boundary",
        evidence: ["Several provider implementations share one contract"],
        counter_evidence: [],
        migration_cost: "low",
        preconditions: [],
      }],
    };
    semanticModule = structuredClone(module);
    await route.fulfill({ response, json: modules });
  });
  await page.route("**/api/search*", async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    result.results = result.results.map((item) => (
      item.path === semanticPath ? { ...item, semantic: semanticModule.semantic } : item
    ));
    await route.fulfill({ response, json: result });
  });

  await openDashboard(page);
  await expect(page.locator(".metric", { hasText: "Files with current AI descriptions" }).locator("strong"))
    .toHaveText("25.0%");
  const notice = page.locator("#semantic-notice");
  await expect(notice).toContainText("no worker is running right now");
  await expect(notice).toContainText("15 file descriptions are unfinished");
  await expect(notice).not.toContainText("module job(s)");
  await expect(notice).not.toContainText("synthesis scope");
  await expect(notice.locator("[data-semantic-refresh]")).toBeVisible();
  await expect(page.locator("#repository-intelligence")).toBeVisible();
  await expect(page.locator("#repository-intelligence")).toContainText(
    "Keeps a continuously reviewed map",
  );
  await expect(page.locator("#repository-intelligence")).toContainText(
    "Shows how files work together",
  );
  await expect(page.locator("#repository-intelligence")).toContainText(
    "Keeps code explanations tied to current evidence",
  );
  await expect(page.locator("#repository-intelligence")).toContainText(
    "A person asks a question",
  );
  await expect(page.locator("#repository-intelligence")).toContainText(
    "Which runtime-created links are absent?",
  );
  await expect(page.locator("#repository-intelligence")).toContainText(
    "repository owner: Continuity is part of the intended product behavior.",
  );

  await page.getByRole("button", { name: "Files", exact: true }).click();
  await page.locator("#module-search").fill(semanticPath);
  await expect(page.locator(".pattern-cell", { hasText: "Adapter pattern" })).toContainText("AI");
  await expect(page.locator(".pattern-cell", { hasText: "Adapter pattern" })).not.toContainText("91/100");
});

test("an idle coding-agent task list says saved work will not finish by itself", async ({ page }) => {
  await page.route("**/api/semantic*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fulfill({ json: { status: "started" } });
      return;
    }
    await route.fulfill({
      json: {
        enabled: true,
        provider: "agent",
        execution_mode: "coding_agent",
        state: "pending",
        semantically_ready: false,
        eligible_modules: 20,
        current: 5,
        pending: 15,
        pending_scopes: 0,
        failed: 0,
        failed_scopes: 0,
        excluded: 0,
        coverage: 0.25,
        jobs: { pending: 15, running: 2, running_live: 0, reclaimable: 2 },
        budget: { paused: false },
        worker: { status: "idle" },
        plain_language: idleSemanticLanguage(true),
      },
    });
  });
  await openDashboard(page);

  const notice = page.locator("#semantic-notice");
  await expect(notice).toContainText("No worker is processing the queue right now");
  await expect(notice).toContainText("it will not finish until a worker starts");
  await expect(notice.locator("[data-semantic-refresh]")).toHaveText("Prepare AI tasks");
  await expect(notice.locator("[data-semantic-refresh]")).toBeEnabled();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.locator("#settings-semantic-command")).toContainText(
    "--executor codex --background",
  );
  await expect(page.locator("#settings-semantic-command")).toContainText("semantic-status");
  await expect(page.locator("#settings-semantic-summary")).toContainText(
    "does not hardcode either one",
  );
});
