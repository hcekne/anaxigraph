import { expect, test } from "@playwright/test";
import { installSemanticFixture } from "./semantic-graph-fixture.js";

async function installSubjects(page, holdDetail = null) {
  const source = await installSemanticFixture(page), requests = [];
  const subjects = [
    { id: "observed", graph_kind: "observed", label: "Observed implementation" },
    { id: "subject:brief", graph_kind: "functional_brief", label: "Saved functional brief", revision: "brief-revision" },
    { id: "subject:fresh", graph_kind: "fresh_alternative", label: "Fresh Eyes product alternative A", revision: "fresh-revision" },
    { id: "subject:target", graph_kind: "planning_target", label: "Selected architecture target", revision: "target-revision" },
  ].map(item => ({ ...item, entity_kinds: item.id === "observed" ? ["module", "function", "interface", "contract", "capability"] : ["component", "contract"], default_kind: item.id === "observed" ? "module" : "" }));
  const node = subject => ({ id: `${subject.id}:node`, kind: "component", label: `${subject.label} responsibility`, path: "", metrics: {}, overview: "Deliver the required behavior behind a clear interface.", detail: `Saved explanation for ${subject.revision}.`, properties: { constraints: ["Preserve required access rules"], planned_paths: subject.graph_kind === "planning_target" ? ["src/proposed.py"] : [] }, readiness: subject.graph_kind === "functional_brief" ? "functional_requirement" : "proposed" });
  await page.route("**/api/graph/subjects?*", route => route.fulfill({ json: { subjects } }));
  await page.route("**/api/graph/**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/graph/subjects") return route.fallback();
    const subject = subjects.find(item => item.id === url.searchParams.get("graph_subject")) || subjects[0];
    requests.push({ path: url.pathname, ...Object.fromEntries(url.searchParams) });
    if (subject.id === "observed") return route.fallback();
    const context = { repository_id: 1, snapshot_id: 1, graph_kind: subject.graph_kind, graph_subject: subject.id, revision: subject.revision };
    if (url.pathname === "/api/graph/entity") {
      if (holdDetail) await holdDetail(subject.id);
      return route.fulfill({ json: { context, node: node(subject), functions: [], interfaces: [], contracts: [], connections: {} } });
    }
    return route.fulfill({ json: { context, nodes: [node(subject)], edges: [], total_nodes: 1, returned_nodes: 1, total_edges: 0, returned_edges: 0, next_offset: null } });
  });
  return { source, subjects, requests };
}

test("graph subjects have their own revisions and never acquire source metrics or grouping", async ({ page }) => {
  const { subjects, requests } = await installSubjects(page);
  await page.goto("/#graph");
  await expect(page.locator("#graph-subject-select option")).toHaveCount(4);
  for (const subject of subjects.slice(1)) {
    await page.locator("#graph-subject-select").selectOption(subject.id);
    await expect(page.locator("#graph-subject-note")).toContainText(subject.revision);
    await expect(page.locator("#map-layer-select")).toBeDisabled();
    await expect(page.locator("#size-select")).toBeHidden();
    await page.locator(`#graph-entity-list [data-entity-id="${subject.id}:node"]`).click();
    await expect(page.locator("#inspector")).toContainText(`Saved explanation for ${subject.revision}`);
    await expect(page.locator("#inspector .inspector-path")).toHaveCount(0);
    await expect(page.locator("#inspector .entity-metrics")).toHaveCount(0);
    await expect(page.locator("#inspector")).toContainText("Preserve required access rules");
    expect(requests.at(-1).graph_subject).toBe(subject.id);
    const pageRequest = requests.findLast(item => item.path === "/api/graph/entities");
    expect(pageRequest.kind).toBe("");
    expect(requests.at(-1).snapshot_id).toBeUndefined();
  }
  await expect(page.locator("#inspector")).toContainText("Planned Paths");
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await expect(page.locator(".module-row")).toHaveCount(2);
  await expect(page.locator("#module-subject-note")).toContainText("observed source");
  await expect(page.locator("#map-layer-select")).toBeEnabled();
  expect(requests.at(-1).graph_subject).toBe("observed");
});

test("a late alternative response cannot repaint a newly selected planning target", async ({ page }) => {
  let release, waiting = false;
  const held = new Promise(resolve => { release = resolve; });
  await installSubjects(page, async id => { if (id === "subject:fresh") { waiting = true; await held; } });
  await page.goto("/#graph");
  await expect(page.locator("#graph-subject-select option")).toHaveCount(4);
  await page.locator("#graph-subject-select").selectOption("subject:fresh");
  await page.locator('#graph-entity-list [data-entity-id="subject:fresh:node"]').click();
  await expect.poll(() => waiting).toBe(true);
  await page.locator("#graph-subject-select").selectOption("subject:target");
  await page.locator('#graph-entity-list [data-entity-id="subject:target:node"]').click();
  await expect(page.locator("#inspector")).toContainText("target-revision");
  const late = page.waitForResponse(response => response.url().includes("entity_id=subject%3Afresh%3Anode"));
  release(); await (await late).finished();
  await expect(page.locator("#inspector")).toContainText("target-revision");
  await expect(page.locator("#inspector")).not.toContainText("Saved explanation for fresh-revision");
});

test("selecting another subject removes previous entity controls while its graph is loading", async ({ page }) => {
  await installSubjects(page);
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route("**/api/graph/entities?*", async route => {
    if (new URL(route.request().url()).searchParams.get("graph_subject") === "subject:target") await held;
    await route.fallback();
  });
  await page.goto("/#graph");
  await expect(page.locator("#graph-entity-list button").first()).toBeVisible();
  await page.locator("#graph-subject-select").selectOption("subject:target");
  await expect(page.locator("#graph-entity-list button")).toHaveCount(0);
  release();
  await expect(page.locator('#graph-entity-list [data-entity-id="subject:target:node"]')).toBeVisible();
});

test("newly saved alternatives appear when returning to Graph without reloading the checkout", async ({ page }) => {
  const { subjects } = await installSubjects(page);
  await page.goto("/#graph");
  await expect(page.locator("#graph-subject-select option")).toHaveCount(4);
  await page.getByRole("button", { name: "Guide", exact: true }).click();
  subjects.push({ ...subjects[2], id: "subject:new-alternative", revision: "newly-saved", label: "Fresh Eyes new alternative" });
  await page.getByRole("button", { name: "Understand", exact: true }).click();
  await page.getByRole("button", { name: "Graph", exact: true }).click();
  await expect(page.locator("#graph-subject-select option")).toHaveCount(5);
  await page.locator("#graph-subject-select").selectOption("subject:new-alternative");
  await expect(page.locator("#graph-subject-note")).toContainText("newly-saved");
});
