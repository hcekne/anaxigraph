import { expect, test } from "@playwright/test";
import { configuredProgress, open, progress } from "./workflow-fixture.js";

test("the opening page shows the diagram and direct flow links survive a reload", async ({ page }) => {
  await page.route("**/api/workflows?*", route => route.fulfill({ json: progress() }));
  await page.goto("/?repository=1");
  await expect(page.locator("#view-workflows")).toBeVisible();
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("4 / 12 files");
  await expect(page.locator("#primary-navigation [data-view=workflows]")).toHaveClass(/active/);
  await page.locator("#workflow-tab-patterns").click();
  await expect(page).toHaveURL(/repository=1#workflows\/patterns$/);
  await page.reload();
  await expect(page.locator("#workflow-tab-patterns")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-step="pattern_review"]')).toBeVisible();
  await page.goto("/?repository=1#workflows/fresh-eyes");
  await expect(page.locator("#workflow-tab-fresh-eyes")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-step="proposals"]')).toBeVisible();
});

test("the map separates current coverage from repeated jobs and keeps optional flows not run", async ({ page }) => {
  await open(page);
  const intrinsic = page.locator('[data-step="intrinsic"]');
  await expect(intrinsic).toContainText("4 / 12 files");
  await expect(intrinsic).toContainText("2 reused");
  await expect(intrinsic).not.toContainText("gpt-6-luna");
  await expect(page.locator("#workflow-message")).toContainText("steps remain");
  await intrinsic.click();
  await expect(page.locator("#workflow-detail")).toContainText("15");
  await expect(page.locator("#workflow-detail")).toContainText("unknown token usage");
  await expect(page.locator("#workflow-tab-patterns small")).toContainText("Not run");
  await expect(page.locator("#workflow-tab-fresh-eyes small")).toContainText("Not run");
  await page.keyboard.press("Escape");
  await page.locator("#workflow-routing summary").click();
  await expect(page.locator("#workflow-routing")).toContainText("gpt-6.1-sol");
  await intrinsic.click();
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
  await expect(page.locator("#workflow-tab-patterns small")).toContainText("Running");
  value.semantic.worker = { status: "complete", workflow: "patterns" };
  value.semantic.jobs = {};
  value.semantic.architecture_charter = { status: "current" };
  value.semantic.patterns = { enabled: false, planned: true, selected: 0, finalized: 0 };
  await page.locator("#workflow-refresh").click();
  await expect(page.locator('[data-step="pattern_assessment"]')).toContainText("0 / 0 pairs");
  await expect(page.locator("#workflow-tab-patterns small")).toContainText("Complete");
  await expect(page.locator("#workflow-model")).toHaveValue("chosen-model");
  await expect(page.locator("#workflow-effort")).toHaveValue("high");
});

test("fresh eyes shows independent proposals, recorded models and the ranked review", async ({ page }, testInfo) => {
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
  await page.keyboard.press("Escape");
  await page.locator('[data-step="grounding"]').click();
  await expect(page.locator("#workflow-detail")).toContainText("do not prove a recommendation correct");
  await page.keyboard.press("Escape");
  await expect(page.locator(".workflow-edges > path")).toHaveCount(8);
  await page.locator("#workflow-diagram").screenshot({ path: testInfo.outputPath("fresh-eyes-branches.png") });
});

test("desktop and phone diagrams fit, keep arrows and support both themes", async ({ page }, testInfo) => {
  await open(page);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    for (const [flow, steps] of [["mapping", 8], ["patterns", 6], ["fresh-eyes", 7]]) {
      for (const theme of ["constellation-light", "constellation-dark"]) {
        await page.locator("#theme-select").selectOption(theme);
        await page.locator(`#workflow-tab-${flow}`).click();
        expect(await page.locator(".workflow-edges > path").count()).toBeGreaterThanOrEqual(steps - 1);
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
        await page.screenshot({ path: testInfo.outputPath(`workflows-${flow}-${width}-${theme}.png`), fullPage: true });
      }
    }
  }
});

test("a delayed response from another repository cannot repaint the selected flow", async ({ page }) => {
  const first = progress(1), second = progress(2);
  first.semantic.worker = { status: "running", workflow: "mapping" };
  first.coverage.workers = [{ job_kind: "intrinsic", scope_type: "module", executor_model: "gpt-6-luna", running: 2 }];
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
      if (hold && !isSecond) { hold = false; waiting = true; await new Promise(resolve => { release = resolve; }); }
      await route.fulfill({ json: isSecond ? second : first });
    } else {
      if (url.searchParams.get("repository_id") === "2") url.searchParams.set("repository_id", "1");
      await route.continue({ url: url.toString() });
    }
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("4 / 12");
  await expect(page.locator('[data-step="intrinsic"] .workflow-spinner')).toBeVisible();
  hold = true;
  await page.locator("#workflow-refresh").click();
  await expect.poll(() => waiting).toBeTruthy();
  await page.locator("#repository-select").selectOption("2");
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("9 / 12");
  const delivered = page.waitForResponse(response => response.url().includes("workflows?repository_id=1"));
  release();
  await delivered;
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("9 / 12");
  await expect(page.locator(".workflow-spinner")).toHaveCount(0);
  first.coverage.workers = [];
  await page.locator("#repository-select").selectOption("1");
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("Preparing jobs…");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await page.unrouteAll({ behavior: "wait" });
});

test("card settings survive polling and reload; a sample saves choices before running only two jobs", async ({ page }) => {
  const value = configuredProgress();
  let saved, posted;
  await page.route("**/api/workflows/settings", async route => {
    saved = route.request().postDataJSON();
    value.settings.steps[saved.step] = saved.workers;
    value.settings.customized = [saved.step];
    await route.fulfill({ json: { repository_id: 1, settings: value.settings } });
  });
  await page.route("**/api/workflows/run", async route => {
    posted = route.request().postDataJSON();
    value.semantic.worker = { status: "running", workflow: "mapping" };
    value.coverage.workers = [{ job_kind: "intrinsic", scope_type: "module", executor_model: "gpt-6.1-sol", running: 2 }];
    await route.fulfill({ json: { status: "started", repository_id: 1 } });
  });
  await open(page, value);
  await page.locator('[data-step="intrinsic"]').click();
  await expect(page.locator("#workflow-detail")).toContainText("Next run · suggested");
  await expect(page.locator("#workflow-detail")).toContainText("4 parallel workers");
  await page.keyboard.press("Escape");
  await page.locator('[data-configure-step="intrinsic"]').click();
  const model = page.locator('#workflow-step-form [name="model"]');
  await model.selectOption("gpt-6.1-sol");
  await page.locator('#workflow-step-form [name="workers"]').fill("2");
  await model.focus();
  await page.waitForResponse(response => response.url().includes("/api/workflows?"));
  await expect(model).toHaveValue("gpt-6.1-sol");
  await expect(model).toBeFocused();
  await page.getByRole("button", { name: "Try 2 jobs", exact: true }).click();
  await expect.poll(() => posted?.step).toBe("intrinsic");
  expect(saved.workers[0]).toMatchObject({ provider: "codex", model: "gpt-6.1-sol", workers: 2 });
  expect(posted).toMatchObject({ workflow: "mapping", use_step_settings: true, max_jobs: 2 });
  await expect(page.locator('[data-step="intrinsic"]')).toContainText("2 / 2 workers active");
  await expect(page.locator('[data-run-step="context"]')).toBeEnabled();
  await page.reload();
  await page.locator('[data-step="intrinsic"]').click();
  await expect(page.locator("#workflow-detail")).toContainText("GPT-6.1 Sol");
  await expect(page.locator("#workflow-detail")).toContainText("your settings");
  await expect(page.locator("#workflow-detail")).toContainText("Recorded models: gpt-6-luna");
});

test("suggested rows can be restored and provider workers stay readable on phone and desktop", async ({ page }, testInfo) => {
  const value = configuredProgress();
  value.semantic.architecture_charter = { status: "current" };
  await open(page, value);
  await page.locator('[data-configure-step="context"]').click();
  await page.getByRole("button", { name: "Add model", exact: true }).click();
  await expect(page.locator(".workflow-worker-row")).toHaveCount(2);
  await page.getByRole("button", { name: "Use suggested", exact: true }).click();
  await expect(page.locator(".workflow-worker-row")).toHaveCount(1);
  await expect(page.locator('#workflow-step-form [name="model"]')).toHaveValue("gpt-6-luna");
  await page.keyboard.press("Escape");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    for (const flow of ["mapping", "patterns", "fresh-eyes"]) {
      await page.locator(`#workflow-tab-${flow}`).click();
      expect(await page.evaluate(() => document.body.scrollWidth <= innerWidth)).toBeTruthy();
      await expect(page.locator(".workflow-node-top strong").first()).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath(`configured-${flow}-${width}.png`), fullPage: true });
    }
  }
  await page.locator('[data-configure-step="proposals"]').click();
  await expect(page.locator(".workflow-worker-row")).toHaveCount(2);
  await expect(page.locator('#workflow-step-form [name="provider"]').nth(1)).toHaveValue("claude");
});

test("model dropdown contains only supported choices for its provider", async ({ page }) => {
  await open(page, configuredProgress());
  await page.locator('[data-configure-step="intrinsic"]').click();
  const provider = page.locator('#workflow-step-form [name="provider"]');
  const model = page.locator('#workflow-step-form select[name="model"]');
  await expect(page.locator('#workflow-step-form input[name="model"]')).toHaveCount(0);
  await expect(model.locator("option")).toHaveText(["gpt-6-luna", "gpt-6.1-sol"]);
  await provider.selectOption("claude");
  await expect(model.locator("option")).toHaveText(["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]);
  await model.selectOption("claude-sonnet-5-5");
  await expect(page.locator('#workflow-step-form [name="reasoning_effort"] option[value="xhigh"]')).toHaveCount(0);
  await page.waitForResponse(response => response.url().includes("/api/workflows?"));
  await expect(model).toHaveValue("claude-sonnet-5-5");
  await provider.selectOption("codex");
  await expect(model).toHaveValue("gpt-6-luna");
  await expect(model.locator("option")).toHaveText(["gpt-6-luna", "gpt-6.1-sol"]);
});

test("unknown saved models require an explicit valid selection", async ({ page }) => {
  const value = configuredProgress();
  value.settings.steps.intrinsic[0].model = "invented-model";
  await open(page, value);
  await page.locator('[data-configure-step="intrinsic"]').click();
  await expect(page.locator('#workflow-step-form select[name="model"]')).toHaveValue("");
  await expect(page.locator("#workflow-step-form .workflow-error")).toContainText("invented-model is unavailable");
  expect(await page.locator("#workflow-step-form").evaluate(form => form.checkValidity())).toBe(false);
});

test("retry errors appear on the card while a surviving pool keeps running", async ({ page }) => {
  const value = configuredProgress();
  value.coverage.failures = [{ job_kind: "intrinsic", scope_type: "module", scope_key: "pkg/example.py", status: "retry", error: "Selected model rejected by provider" }];
  await open(page, value);
  const card = page.locator('[data-step="intrinsic"]');
  await expect(card).toContainText("Needs attention");
  await expect(card).toContainText("Retry pending");
  await expect(card.locator(".workflow-card-error")).toHaveAttribute("title", "Selected model rejected by provider");
  value.semantic.worker = { status: "running", workflow: "mapping", step: "intrinsic", pool_errors: [{ step: "intrinsic", provider: "claude", model: "claude-sonnet-5-5", error: "Selected model rejected by provider" }] };
  value.coverage.workers = [{ job_kind: "intrinsic", scope_type: "module", executor_model: "gpt-6-luna", running: 2 }];
  await page.locator("#workflow-refresh").click();
  await expect(card.locator(".workflow-spinner")).toBeVisible();
  await expect(card).toContainText("2 / 4 workers active");
  await expect(card).toContainText("claude-sonnet-5-5 unavailable");
  await card.click();
  await expect(page.locator("#workflow-detail")).toContainText("Selected model rejected by provider");
});

test("the whole active card pulses with live counts, includes its actions and respects reduced motion", async ({ page }, testInfo) => {
  const value = configuredProgress();
  value.execution.max_parallel_jobs = 12;
  const workers = [{ ...value.settings.steps.intrinsic[0], workers: 12 }];
  value.semantic.worker = { status: "running", workflow: "mapping", active_step: "intrinsic", settings: { intrinsic: workers } };
  value.settings.steps.intrinsic[0].workers = 8; // A subsequent choice must not change the live capacity.
  value.coverage.workers = [{ job_kind: "intrinsic", scope_type: "module", executor_model: "gpt-6-luna", running: 12 }];
  value.coverage.live_jobs[0].running = 12;
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await open(page, value);
  const node = page.locator('[data-step="intrinsic"]'), card = node.locator("..");
  await expect(node).toContainText("12 / 12 workers active");
  await node.click();
  await page.keyboard.press("Escape");
  await expect(card).toHaveClass(/running.*selected/);
  const appearance = await card.evaluate(element => {
    const footer = element.querySelector(".workflow-card-actions");
    return { outline: getComputedStyle(element).outlineStyle, radius: getComputedStyle(element).borderBottomLeftRadius,
      ring: getComputedStyle(element, "::after").animationName,
      spinner: getComputedStyle(element.querySelector(".workflow-spinner")).animationName,
      containsFooter: element.getBoundingClientRect().bottom >= footer.getBoundingClientRect().bottom };
  });
  expect(appearance).toEqual({ outline: "solid", radius: "16px", ring: "workflow-pulse", spinner: "workflow-spin", containsFooter: true });
  value.coverage.workers[0].running = value.coverage.live_jobs[0].running = 3;
  await page.locator("#workflow-refresh").click();
  await expect(node).toContainText("3 / 12 workers active");
  await expect(node).toContainText("3 / 12 workers active");
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    for (const theme of ["constellation-light", "constellation-dark"]) {
      await page.locator("#theme-select").selectOption(theme);
      expect(await page.evaluate(() => document.body.scrollWidth <= innerWidth)).toBeTruthy();
      await card.screenshot({ path: testInfo.outputPath(`active-card-${width}-${theme}.png`) });
    }
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(node.locator(".workflow-spinner")).toHaveCSS("animation-name", "none");
  await expect(node).toContainText("3 / 12 workers active");
  expect(await card.evaluate(element => getComputedStyle(element, "::after").animationName)).toBe("none");
});

for (const reportsStep of [true, false]) {
test(`Run step stays active through acceptance, planning and reload (${reportsStep ? "step-aware" : "workflow-only"} server)`, async ({ page }) => {
  const value = configuredProgress();
  let release, waiting = false;
  await page.route("**/api/workflows/run", async route => {
    waiting = true;
    await new Promise(resolve => { release = resolve; });
    value.semantic.worker = { status: "running", workflow: "mapping",
      ...(reportsStep ? { step: "intrinsic", settings: value.settings.steps } : {}) };
    await route.fulfill({ json: { status: "started", repository_id: 1 } });
  });
  await open(page, value);
  const node = page.locator('[data-step="intrinsic"]');
  await expect(node.locator(".workflow-spinner")).toHaveCount(0); // Queued tasks alone are not running.
  await page.locator('[data-run-step="intrinsic"]').click();
  try {
    await expect.poll(() => waiting).toBeTruthy();
    await expect(node).toContainText("Starting step…");
    await expect(node.locator(".workflow-spinner")).toBeVisible();
  } finally { release?.(); }
  await expect(node).toContainText("Preparing jobs…");
  await expect(node.locator("..")).toHaveClass(/running/);
  await expect(page.locator("#workflow-message")).toHaveText("Preparing pending jobs…");
  await page.waitForResponse(response => response.url().includes("/api/workflows?"));
  await expect(node.locator(".workflow-spinner")).toBeVisible();
  await page.reload();
  await expect(node).toContainText("Preparing jobs…");
  await expect(node.locator(".workflow-spinner")).toBeVisible();
  value.semantic.worker = { status: "complete", workflow: "mapping", step: "intrinsic" };
  value.coverage.scopes.module.intrinsic = 12;
  value.semantic.jobs = {};
  await page.locator("#workflow-refresh").click();
  await expect(node).toContainText("Complete");
  await expect(node.locator(".workflow-spinner")).toHaveCount(0);
  await expect(node.locator("..")).not.toHaveClass(/running/);
});
}

test("observed workers keep their card active between jobs and server step changes take precedence", async ({ page }) => {
  const value = configuredProgress();
  value.semantic.worker = { status: "running", workflow: "mapping" };
  value.coverage.workers = [{ job_kind: "intrinsic", scope_type: "module", executor_model: "gpt-6-luna", running: 2 }];
  await open(page, value);
  const intrinsic = page.locator('[data-step="intrinsic"]'), context = page.locator('[data-step="context"]');
  await expect(intrinsic).toContainText("2 / 4 workers active");
  value.coverage.workers = [];
  await page.locator("#workflow-refresh").click();
  await expect(intrinsic).toContainText("Preparing jobs…");
  await page.reload();
  await expect(intrinsic.locator(".workflow-spinner")).toBeVisible();
  value.semantic.worker.active_step = "context";
  await page.locator("#workflow-refresh").click();
  await expect(context).toContainText("Preparing jobs…");
  await expect(intrinsic.locator(".workflow-spinner")).toHaveCount(0);
  delete value.semantic.worker.active_step;
  value.snapshot_id += 1;
  await page.locator("#workflow-refresh").click();
  await expect(page.locator(".workflow-spinner")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("#workflow-message")).toHaveText("Preparing pending jobs…");
  await expect(page.locator(".workflow-spinner")).toHaveCount(0); // The old scan's card must not stick.
});

test("rejected and already-running requests do not leave the clicked card spinning", async ({ page }) => {
  const value = configuredProgress();
  let requests = 0;
  await page.route("**/api/workflows/run", async route => {
    requests += 1;
    if (requests === 1) return route.fulfill({ status: 503, json: { detail: "Worker unavailable" } });
    value.semantic.worker = { status: "running", workflow: "mapping", active_step: "context" };
    await route.fulfill({ json: { status: "already_running", repository_id: 1 } });
  });
  await open(page, value);
  const run = page.locator('[data-run-step="intrinsic"]');
  await run.click();
  await expect.poll(() => requests).toBe(1);
  await expect(run).toBeEnabled();
  await expect(page.locator(".workflow-spinner")).toHaveCount(0);
  await run.click();
  await expect(page.locator('[data-step="context"] .workflow-spinner')).toBeVisible();
  await expect(page.locator('[data-step="intrinsic"] .workflow-spinner')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('[data-step="context"] .workflow-spinner')).toBeVisible();
  await expect(page.locator('[data-step="intrinsic"] .workflow-spinner')).toHaveCount(0);
});
