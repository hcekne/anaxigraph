import { expect, test } from "@playwright/test";

function progress(repositoryId = 1) {
  return {
    repository_id: repositoryId, snapshot_id: 42, scan: { active: false },
    execution: { mounted: true, configured_provider: "agent", local_executors: ["codex", "claude"], max_parallel_jobs: 4 },
    coverage: {
      scopes: { module: { total: 12, excluded: 0, intrinsic: 4, current: 2, intrinsic_reused: 2, reused: 1 } },
      live_jobs: [{ job_kind: "intrinsic", scope_type: "module", running: 0, interrupted: 0 }],
      document_models: [], scan: { analyzed_count: 10, reused_count: 2, error_count: 0 },
    },
    semantic: {
      enabled: true, provider: "agent", jobs: { pending: 8, running_live: 0 }, worker: { status: "idle" },
      map_status: { state: "current" }, budget: { paused: false },
      taxonomy: { enabled: true, required_review_passes: 2, ready: false },
      patterns: { enabled: false, planned: false, selected: 0, finalized: 0 },
      semantic_policy: { stage_models: { repository: { model: "gpt-6.1-sol", reasoning_effort: "high" } } },
      telemetry: { semantic: { current_snapshot: { actions: [{
        job_kind: "intrinsic", scope_type: "module", completed: 15, pending: 8, input_tokens: 12000,
        output_tokens: 400, token_counts_missing: 1, models: ["gpt-6-luna"],
      }] } } },
    },
    fresh_eyes: { state: "not_started", ready: false, stages: [], recommendations: [] },
  };
}

async function open(page, value = progress()) {
  await page.route("**/api/workflows?*", route => route.fulfill({ json: value }));
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(page.locator(".workflow-node")).toHaveCount(8);
}

test("the map separates current coverage from repeated jobs and keeps optional flows not run", async ({ page }) => {
  await open(page);
  const intrinsic = page.locator('[data-step="intrinsic"]');
  await expect(intrinsic).toContainText("4 / 12 files");
  await expect(intrinsic).toContainText("2 reused");
  await expect(intrinsic).toContainText("gpt-6-luna");
  await expect(page.locator("#workflow-message")).toContainText("waiting");
  await intrinsic.click();
  await expect(page.locator("#workflow-detail")).toContainText("15");
  await expect(page.locator("#workflow-detail")).toContainText("unknown token usage");
  await expect(page.locator("#workflow-tab-patterns small")).toHaveText("Not run");
  await expect(page.locator("#workflow-tab-fresh-eyes small")).toHaveText("Not run");
  await page.locator("#workflow-routing summary").click();
  await expect(page.locator("#workflow-routing")).toContainText("gpt-6.1-sol");
  await page.getByRole("button", { name: "Explore modules →" }).click();
  await expect(page.locator("#view-modules")).toHaveClass(/active/);
});

test("starting a pattern run uses explicit controls and zero candidates can finish", async ({ page }) => {
  const value = progress();
  let posted;
  await page.route("**/api/workflows/run", async route => {
    posted = route.request().postDataJSON();
    value.semantic.worker = { status: "running", workflow: "patterns" };
    await route.fulfill({ json: { status: "started", repository_id: 1 } });
  });
  await open(page, value);
  await page.locator("#workflow-tab-patterns").click();
  await page.locator("#workflow-model").fill("chosen-model");
  await page.locator("#workflow-effort").fill("high");
  await page.locator("#workflow-run-button").click();
  await expect.poll(() => posted?.workflow).toBe("patterns");
  expect(posted).toMatchObject({ repository_id: 1, executor: "codex", model: "chosen-model", reasoning_effort: "high", parallel_jobs: 2 });
  await expect(page.locator("#workflow-run-button")).toBeDisabled();
  await expect(page.locator("#workflow-tab-patterns small")).toHaveText("Running");
  value.semantic.worker = { status: "complete", workflow: "patterns" };
  value.semantic.jobs = {};
  value.semantic.architecture_charter = { status: "current" };
  value.semantic.patterns = { enabled: false, planned: true, selected: 0, finalized: 0 };
  await page.locator("#workflow-refresh").click();
  await expect(page.locator('[data-step="pattern_assessment"]')).toContainText("0 / 0 pairs");
  await expect(page.locator("#workflow-tab-patterns small")).toHaveText("Complete");
  await expect(page.locator("#workflow-model")).toHaveValue("chosen-model");
  await expect(page.locator("#workflow-effort")).toHaveValue("high");
});

test("fresh eyes shows independent proposals, recorded models and the ranked review", async ({ page }) => {
  const value = progress();
  value.fresh_eyes = {
    state: "current", ready: true, capability_brief: { mission: "A useful system" },
    stages: ["proposal:a", "proposal:b", "adjudication", "comparison", "review"].map((key, i) => ({
      key, label: key, state: "current", reason: "Saved result",
      provenance: { executor_model: i === 1 ? "claude-opus-5-5" : "gpt-6.1-sol" },
    })),
    recommendations: [{ title: "A small change" }],
  };
  await open(page, value);
  await page.locator("#workflow-tab-fresh-eyes").click();
  await expect(page.locator(".workflow-node")).toHaveCount(7);
  const proposals = page.locator('[data-step="proposals"]');
  await expect(proposals).toContainText("2 / 2 proposals");
  await expect(proposals.locator(".workflow-proposal-lanes > span")).toHaveCount(2);
  await proposals.click();
  await expect(page.locator("#workflow-detail")).toContainText("gpt-6.1-sol");
  await expect(page.locator("#workflow-detail")).toContainText("claude-opus-5-5");
  await expect(page.locator('[data-step="mission_filter"]')).toContainText("Complete");
  await page.locator('[data-step="grounding"]').click();
  await expect(page.locator("#workflow-detail")).toContainText("do not prove a recommendation correct");
});

test("desktop and phone diagrams fit, keep arrows and support both themes", async ({ page }, testInfo) => {
  await open(page);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    for (const theme of ["constellation-light", "constellation-dark"]) {
      await page.locator("#theme-select").selectOption(theme);
      await expect(page.locator(".workflow-edges > path")).toHaveCount(7);
      const layout = await page.evaluate(() => ({
        viewport: innerWidth, content: document.body.scrollWidth,
        boxes: [...document.querySelectorAll(".workflow-node")].map(node => {
          const rect = node.getBoundingClientRect();
          return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom };
        }),
      }));
      expect(layout.content).toBeLessThanOrEqual(layout.viewport);
      for (let i = 0; i < layout.boxes.length; i++) {
        for (let j = i + 1; j < layout.boxes.length; j++) {
          const a = layout.boxes[i], b = layout.boxes[j];
          expect(a.right <= b.x || b.right <= a.x || a.bottom <= b.y || b.bottom <= a.y).toBeTruthy();
        }
      }
      await page.screenshot({ path: testInfo.outputPath(`workflows-${width}-${theme}.png`), fullPage: true });
    }
  }
});

test("a delayed response from another repository cannot repaint the selected flow", async ({ page }) => {
  const first = progress(1), second = progress(2);
  second.coverage.scopes.module.intrinsic = 9;
  let hold = false, release, waiting = false;
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/repositories") {
      const response = await route.fetch();
      const rows = await response.json();
      await route.fulfill({ json: [rows[0], { ...rows[0], id: 2, name: "Second repository" }] });
    } else if (url.pathname === "/api/workflows") {
      const isSecond = url.searchParams.get("repository_id") === "2";
      if (hold && !isSecond) { waiting = true; await new Promise(resolve => { release = resolve; }); }
      await route.fulfill({ json: isSecond ? second : first });
    } else {
      if (url.searchParams.get("repository_id") === "2") url.searchParams.set("repository_id", "1");
      await route.fulfill({ response: await route.fetch({ url: url.toString() }) });
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("4 / 12");
  hold = true;
  await page.locator("#workflow-refresh").click();
  await expect.poll(() => waiting).toBeTruthy();
  await page.locator("#repository-select").selectOption("2");
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("9 / 12");
  const delivered = page.waitForResponse(response => response.url().includes("workflows?repository_id=1"));
  release();
  await delivered;
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("9 / 12");
});
