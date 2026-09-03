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

test("cross-provider proposals name their executor families", async ({ page }) => {
  const crossProvider = {
    ...reviewResult(),
    diversity: {
      proposal_count: 2,
      cross_provider: true,
      models: ["fixture-model"],
      executor_families: ["claude", "codex"],
    },
    caveats: [],
  };
  await page.route("**/api/fresh-eyes**", async (route) => {
    await route.fulfill({ json: crossProvider });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();

  await expect(page.locator("#fresh-eyes-diversity")).toContainText("Proposals from claude and codex");
  await expect(page.locator("#fresh-eyes-diversity")).toContainText("Different providers are recorded");
  await expect(page.locator("#fresh-eyes-diversity")).not.toContainText("not cross-provider");
});

test("dirty snapshot banner is shown only for dirty reviews", async ({ page }) => {
  const clean = { ...reviewResult(), snapshot: snapshot(false) };
  const dirty = { ...reviewResult(), snapshot: snapshot(true) };
  let payload = dirty;
  await page.route("**/api/fresh-eyes**", async (route) => {
    await route.fulfill({ json: payload });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();

  const warning = page.locator("#view-fresh-eyes .fresh-eyes-warning");
  await expect(warning).toBeVisible();
  await expect(warning).toContainText("dirty checkout");
  await expect(warning).toContainText("working-tree fingerprint ffffffffffff");

  payload = clean;
  await page.locator("#fresh-eyes-refresh").click();
  await expect(warning).toHaveCount(0);
});

function snapshot(dirty) {
  return {
    snapshot_id: 2,
    commit_sha: "a".repeat(40),
    branch: "main",
    snapshot_kind: "working_tree",
    dirty,
    working_tree_fingerprint: dirty ? "f".repeat(64) : null,
    scan_consistency: null,
    analyzed_at: "2026-09-02T10:00:00+00:00",
  };
}

function reviewResult() {
  return {
    contract_version: "fresh-eyes-review-v1",
    identity: "fresh-eyes-review-v1:1:2:abc",
    review_generation: 2,
    state: "current",
    ready: true,
    generations: [
      { generation: 1, snapshot_id: 1, state: "superseded", ready: false },
      { generation: 2, snapshot_id: 2, state: "current", ready: true },
    ],
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
  return {
    key,
    label,
    state: "current",
    reason: "Complete",
    telemetry: {
      key,
      duration_ms: 431_000,
      output_bytes: 20_480,
      input_tokens: 235_690,
      output_tokens: 20_055,
      token_counts_reported: true,
      input_tokens_plausible: true,
      attempts_observed: 1,
    },
  };
}

test("a stale grounding status names the citations that did not resolve", async ({ page }) => {
  const grounded = {
    ...reviewResult(),
    grounding_summary: { counts: { confirmed: 0, needs_test: 0, already_satisfied: 0, stale: 1 } },
    recommendations: [{
      ...reviewResult().recommendations[0],
      grounding: {
        status: "stale",
        reason: "Cited code changed after the review was produced: pkg/core.py.",
        checks: [{ kind: "path", value: "pkg/core.py", field: "current_evidence", result: "changed" }],
      },
    }],
  };
  await page.route("**/api/fresh-eyes**", async (route) => {
    await route.fulfill({ json: grounded });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();

  const badge = page.locator(".fresh-grounding.stale");
  await expect(badge).toContainText("Stale");
  await expect(badge).toContainText("Cited code changed after the review was produced");
  await expect(page.locator(".fresh-grounding-checks")).toContainText(
    "1 citation that did not resolve",
  );
  await page.locator(".fresh-grounding-checks summary").click();
  await expect(page.locator(".fresh-grounding-checks")).toContainText("path pkg/core.py — changed");
});

test("a recorded generation can be read but not restarted", async ({ page }) => {
  const superseded = {
    ...reviewResult(),
    review_generation: 1,
    state: "superseded",
    ready: false,
    recommendations: [{
      rank: 1,
      title: "Split the durable queue",
      action: "split",
      confidence: 0.6,
      smallest_change: "Move claiming behind its own boundary.",
      expected_benefit: "One reason to change per module.",
      reasons_not_to_proceed: [],
      verification: [],
    }],
  };
  await page.route("**/api/fresh-eyes**", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({ json: url.searchParams.get("generation") === "1" ? superseded : reviewResult() });
  });
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();

  await expect(page.locator(".fresh-stage").first()).toContainText("235690 in / 20055 out tokens");
  const selector = page.locator("#fresh-eyes-generation");
  await expect(selector).toBeVisible();
  await selector.selectOption("1");
  await expect(page.locator(".fresh-recommendation")).toContainText("Split the durable queue");
  await expect(page.locator("#fresh-eyes-title")).toHaveText("Recorded earlier generation");
  await expect(page.getByRole("button", { name: "Reading a recorded generation" })).toBeDisabled();
  await selector.selectOption("");
  await expect(page.locator(".fresh-recommendation")).toContainText("Consolidate duplicate orchestration");
  await expect(page.getByRole("button", { name: "Review complete" })).toBeDisabled();
});

test("two generations render side by side with provenance headers", async ({ page }) => {
  await routeGenerations(page, leftGeneration(), rightGeneration());
  await openFreshEyes(page);
  await page.locator("#fresh-eyes-compare").selectOption("2");

  const columns = page.locator(".fresh-compare-column");
  await expect(columns).toHaveCount(2);
  await expect(columns.nth(0).locator("h3")).toHaveText("Generation 3");
  await expect(columns.nth(1).locator("h3")).toHaveText("Generation 2");
  await expect(columns.nth(0)).toContainText("claude-fable-5-1");
  await expect(columns.nth(1)).toContainText("gpt-5.6-sol");
  await expect(columns.nth(0)).toContainText("different providers are recorded");
  await expect(columns.nth(1)).toContainText("not cross-provider agreement");
  await expect(columns.nth(0)).toContainText("7m 11s · 20.0 KiB written");
  await expect(columns.nth(0).locator(".fresh-compare-recommendations li")).toContainText([
    "Consolidate duplicate orchestration",
    "Name the boundary",
  ]);
  await expect(columns.nth(1).locator(".fresh-compare-recommendations li")).toContainText([
    "Split the durable queue",
  ]);
  await expect(columns.nth(0)).toContainText("Workflow engine");
  await expect(columns.nth(1)).toContainText("No rejected ideas were recorded");
  await expect(columns.nth(0)).toContainText("Disagreements the adjudicator preserved");
  await expect(columns.nth(0)).toContainText("Boundary");
  await expect(columns.nth(0)).toContainText("72% in the ranked strategy");

  const alignment = page.locator(".fresh-compare-alignment");
  await expect(alignment).toContainText("Matched by lexical signals");
  await expect(alignment).toContainText("Recommendations both generations made");
  await expect(alignment).toContainText("Only generation 3 recommended");
  await expect(alignment).toContainText("Only generation 2 recommended");
  await expect(alignment).toContainText(
    "Lexical matching cannot detect the same intent expressed in different words",
  );
});

test("same-generation comparison shows a notice", async ({ page }) => {
  await routeGenerations(page, leftGeneration(), rightGeneration());
  await openFreshEyes(page);
  await page.locator("#fresh-eyes-compare").selectOption("3");

  await expect(page.locator(".fresh-compare-notice")).toContainText(
    "Pick a different generation on one side",
  );
  await expect(page.locator(".fresh-compare")).toContainText("Both sides name generation 3");
  await expect(page.locator(".fresh-compare-column")).toHaveCount(0);
});

test("a seven-versus-five comparison fits desktop and phone viewports", async ({ page }) => {
  const left = {
    ...leftGeneration(),
    recommendations: manyAdvice(7, "Claude"),
    strategy: { summary: "Seven", rejected_ideas: manyRejected(11) },
  };
  const right = {
    ...rightGeneration(),
    recommendations: manyAdvice(5, "Codex"),
    strategy: { summary: "Five", rejected_ideas: manyRejected(5) },
  };
  await routeGenerations(page, left, right);
  await openFreshEyes(page);
  await page.locator("#fresh-eyes-compare").selectOption("2");
  await expect(page.locator(".fresh-compare-column")).toHaveCount(2);

  const viewports = [[{ width: 1440, height: 1100 }, false], [{ width: 390, height: 844 }, true]];
  for (const [viewport, stacked] of viewports) {
    await page.setViewportSize(viewport);
    const layout = await page.evaluate(() => {
      const columns = [...document.querySelectorAll(".fresh-compare-column")];
      return {
        documentFits:
          document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        columnsFit: columns.every((column) => column.scrollWidth <= column.clientWidth + 1),
        stacked: Math.round(columns[0].getBoundingClientRect().left)
          === Math.round(columns[1].getBoundingClientRect().left),
      };
    });
    expect(layout).toEqual({ documentFits: true, columnsFit: true, stacked });
  }
});

async function openFreshEyes(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Fresh eyes", exact: true }).click();
  await expect(page.locator("#fresh-eyes-compare")).toBeVisible();
}

async function routeGenerations(page, left, right) {
  await page.route("**/api/fresh-eyes**", async (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get("compare_with")) {
      await route.fulfill({ json: { ...left, alignment: alignmentBlock() } });
      return;
    }
    await route.fulfill({ json: params.get("generation") === "2" ? right : left });
  });
}

function comparedGenerations() {
  return [{ generation: 2, snapshot_id: 2, state: "superseded", ready: false },
    { generation: 3, snapshot_id: 3, state: "current", ready: true }];
}

function proposalStage(model) {
  return {
    ...stage("proposal:a", "Independent proposal A"),
    provenance: { provider: "agent", executor_id: "cli:codex:1", executor_model: model },
  };
}

function leftGeneration() {
  return {
    ...reviewResult(),
    review_generation: 3,
    snapshot_id: 3,
    generations: comparedGenerations(),
    stages: [proposalStage("claude-fable-5-1")],
    diversity: { proposal_count: 2, cross_provider: true,
      models: ["claude-fable-5-1"], executor_families: ["claude", "codex"] },
    recommendations: [
      advice(1, "Consolidate duplicate orchestration", "consolidate"),
      advice(2, "Name the boundary", "split"),
    ],
    strategy: {
      summary: "Generation 3",
      confidence: 0.72,
      rejected_ideas: [{ idea: "Workflow engine", reason: "The fixed recipe does not need one." }],
    },
  };
}

function rightGeneration() {
  return {
    ...reviewResult(),
    review_generation: 2,
    snapshot_id: 2,
    state: "superseded",
    ready: false,
    generations: comparedGenerations(),
    stages: [proposalStage("gpt-5.6-sol")],
    diversity: { proposal_count: 2, cross_provider: false,
      models: ["gpt-5.6-sol"], executor_families: ["codex"] },
    recommendations: [advice(1, "Split the durable queue", "split")],
    adjudication: { disagreements: [] },
    strategy: { summary: "Generation 2", rejected_ideas: [] },
  };
}

function reference(index, rank, title, action) {
  return { kind: "recommendation", index, rank, title, action };
}

function alignmentBlock() {
  return {
    method: "lexical",
    left: { review_generation: 3 },
    right: { review_generation: 2 },
    aligned: [{
      left: reference(0, 1, "Consolidate duplicate orchestration", "consolidate"),
      right: reference(0, 1, "Consolidate the duplicated orchestration", "consolidate"),
      score: 0.61,
      signals: { same_action: true },
    }],
    conflicting: [],
    unmatched_left: [reference(1, 2, "Name the boundary", "split")],
    unmatched_right: [reference(1, 2, "Split the durable queue", "split")],
    caveats: [
      "Lexical matching cannot detect the same intent expressed in different words, so an "
      + "unmatched recommendation is not evidence that the other generation missed it.",
    ],
  };
}

function advice(rank, title, action) {
  return { rank, title, action, confidence: 0.5, smallest_change: "One change.",
    expected_benefit: "One behavior to verify.", reasons_not_to_proceed: [], verification: [] };
}

function manyAdvice(count, prefix) {
  return Array.from({ length: count }, (_, index) => advice(
    index + 1,
    `${prefix} idea ${index + 1}: src/anaxigraph/semantic_fresh_eyes_generations_and_telemetry.py`,
    "split",
  ));
}

function manyRejected(count) {
  return Array.from({ length: count }, (_, index) => ({ reason: "Outside the mission.",
    idea: `Rejected idea ${index + 1} naming an-unbroken-identifier-that-must-wrap-in-column` }));
}
