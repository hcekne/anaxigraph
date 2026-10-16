import { api, byId, escapeHtml, request, selectedRepository, state, toast } from "/assets/dashboard-core.js";
import { switchView } from "/assets/navigation.js";
import { buildFlows } from "/assets/workflow-model.js";
import { drawWorkflowEdges, overviewWorkflowLinks, workflowDetail, workflowDiagram, workflowTabs } from "/assets/workflow-render.js";

let data = null;
let selectedFlow = "mapping";
let selectedStep = "scan";
let requestToken = 0;
let timer = null;
let runningRequest = false;
let controlsRepository = null;
let observer;

export function setupWorkflowsView() {
  const section = document.createElement("section");
  section.id = "view-workflows";
  section.className = "view";
  section.innerHTML = shell();
  byId("view-overview").after(section);
  const entry = document.createElement("article");
  entry.id = "workflow-entry";
  entry.className = "panel workflow-entry";
  byId("metric-grid").after(entry);
  document.addEventListener("click", handleClick);
  byId("workflow-run-form").addEventListener("submit", startWorkflow);
  byId("workflow-tabs").addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...byId("workflow-tabs").children];
    const index = tabs.indexOf(document.activeElement);
    const next = tabs[(index + (event.key === "ArrowRight" ? 1 : 2)) % tabs.length];
    next.click();
    byId(next.id)?.focus();
  });
  window.addEventListener("anaxigraph:viewchange", ({ detail }) => {
    window.clearTimeout(timer);
    if (detail.name === "workflows") void loadWorkflows();
  });
  byId("repository-select").addEventListener("change", clearWorkflows);
  observer = new ResizeObserver(() => drawWorkflowEdges(byId("workflow-diagram")?.querySelector(".workflow-canvas")));
  observer.observe(byId("workflow-diagram"));
}

function shell() {
  return `<article class="panel workflow-intro"><div><p class="eyebrow">Repository workflows</p>
    <h2>Follow the work. Explore the results.</h2><p>Every step uses evidence from the selected repository. Select a card to see what goes in, what comes out and which models did the work.</p></div>
    <button id="workflow-refresh" type="button" class="secondary-button">Refresh progress</button></article>
    <p id="workflow-message" class="workflow-message" role="status">Reading repository progress…</p>
    <div id="workflow-tabs" class="workflow-tabs" role="tablist" aria-label="Repository workflows"></div>
    <section id="workflow-panel" role="tabpanel"><article id="workflow-diagram" class="panel workflow-diagram"></article>
    <div class="workflow-lower"><article id="workflow-detail" class="panel workflow-detail"></article>
    <article class="panel workflow-run"><p class="eyebrow">Run this workflow</p><h3 id="workflow-run-title">Mapping</h3>
    <p id="workflow-run-note"></p><form id="workflow-run-form">
    <div class="workflow-fields"><label>Executor<select id="workflow-executor"></select></label>
    <label>Worker model<input id="workflow-model" maxlength="200" placeholder="Model ID" autocomplete="off" /></label>
    <label>Reasoning effort<input id="workflow-effort" maxlength="40" placeholder="Executor default" /></label>
    <label>Parallel jobs<input id="workflow-parallel" type="number" min="1" max="64" value="2" /></label></div>
    <div id="workflow-fresh-options" hidden><label>Independent proposals<select id="workflow-proposals"><option value="1">1 proposal</option><option value="2" selected>2 proposals</option><option value="3">3 proposals</option></select></label>
    <label>Review goal (optional)<input id="workflow-goal" maxlength="4000" placeholder="What should the review help improve?" /></label>
    <label class="workflow-check"><input id="workflow-restart" type="checkbox" /> Start a new review generation</label></div>
    <details id="workflow-routing"><summary>Model choices by stage</summary><div></div></details>
    <p id="workflow-execution-note" class="muted"></p><button id="workflow-run-button" class="button" type="submit">Start workflow</button>
    <button id="workflow-scan" class="secondary-button" type="button">Refresh source scan</button>
    </form></article></div></section>`;
}

function clearWorkflows() {
  requestToken += 1;
  window.clearTimeout(timer);
  data = null;
  runningRequest = false;
  byId("workflow-run-button").disabled = true;
  byId("workflow-entry").textContent = "Reading workflow progress for this repository…";
  byId("workflow-diagram").textContent = "Reading repository progress…";
  byId("workflow-detail").textContent = "";
  byId("workflow-message").textContent = "Reading repository progress…";
}

export function resetWorkflowsView() {
  clearWorkflows();
  void loadWorkflows(true);
}

async function loadWorkflows(resetControls = false) {
  const token = ++requestToken;
  const repositoryId = state.repositoryId;
  try {
    const value = await request(api("/api/workflows"));
    if (token !== requestToken || repositoryId !== state.repositoryId) return;
    const changed = data && (data.snapshot_id !== value.snapshot_id ||
      (["queued", "running"].includes(data.semantic.worker?.status) && !["queued", "running"].includes(value.semantic.worker?.status)) ||
      (data.semantic.jobs?.running_live > 0 && !value.semantic.jobs?.running_live));
    data = value;
    if (changed) { await state.reloadRepository?.(); return; }
    if (resetControls || controlsRepository !== repositoryId) configureControls();
    render();
  } catch (error) {
    if (token === requestToken && repositoryId === state.repositoryId) {
      byId("workflow-message").textContent = `Progress is unavailable: ${error.message}`;
    }
  } finally {
    if (token === requestToken && byId("view-workflows").classList.contains("active")) {
      window.clearTimeout(timer);
      timer = window.setTimeout(loadWorkflows, 3500);
    }
  }
}

function configureControls() {
  const execution = data.execution;
  const agent = execution.configured_provider === "agent";
  const names = agent ? execution.local_executors : ["configured"];
  const retained = controlsRepository === state.repositoryId;
  const executor = byId("workflow-executor").value;
  byId("workflow-executor").innerHTML = names.map(name => `<option value="${name}">${escapeHtml(name === "configured" ? execution.configured_provider : name)}</option>`).join("");
  if (retained && names.includes(executor)) byId("workflow-executor").value = executor;
  byId("workflow-model").disabled = !agent;
  byId("workflow-model").required = agent;
  byId("workflow-effort").disabled = !agent;
  byId("workflow-parallel").max = execution.max_parallel_jobs;
  if (!retained) {
    byId("workflow-model").value = agent ? "" : data.semantic.model || "";
    byId("workflow-effort").value = "";
    byId("workflow-parallel").value = Math.min(2, execution.max_parallel_jobs);
    byId("workflow-goal").value = "";
    byId("workflow-restart").checked = false;
    byId("workflow-proposals").value = "2";
  }
  controlsRepository = state.repositoryId;
  const tiers = data.semantic.semantic_policy?.stage_models || {};
  byId("workflow-routing").querySelector("div").innerHTML = Object.entries(tiers).map(([tier, choice]) => `<p><strong>${escapeHtml(tier)}:</strong> ${escapeHtml([choice.provider, choice.model, choice.reasoning_effort].filter(Boolean).join(" · ") || "Selected worker")}</p>`).join("")
    + "<p>Repository stage choices take precedence over the worker model. Proposal and map reviews share the taxonomy choice. Recorded models appear on completed cards.</p>";
}

function render() {
  if (!data || data.repository_id !== state.repositoryId) return;
  const flows = buildFlows(data, state.overview?.files || 0);
  const flow = flows.find(item => item.id === selectedFlow);
  const current = flow.steps.find(item => item.id === selectedStep) || flow.steps[0];
  selectedStep = current.id;
  const focusStep = document.activeElement?.dataset.step;
  byId("workflow-tabs").innerHTML = workflowTabs(flows, selectedFlow);
  byId("workflow-panel").setAttribute("aria-labelledby", `workflow-tab-${selectedFlow}`);
  byId("workflow-diagram").innerHTML = workflowDiagram(flow, selectedStep);
  byId("workflow-detail").innerHTML = workflowDetail(current);
  byId("workflow-entry").innerHTML = overviewWorkflowLinks(flows);
  if (focusStep) document.querySelector(`[data-step="${focusStep}"]`)?.focus({ preventScroll: true });
  drawWorkflowEdges(byId("workflow-diagram").querySelector(".workflow-canvas"));
  renderControls(flow);
}

function renderControls(flow) {
  const semantic = data.semantic;
  const worker = semantic.worker || {};
  const active = ["queued", "running"].includes(worker.status) || semantic.jobs?.running_live > 0;
  const stale = semantic.map_status?.state !== "current";
  const allowed = data.execution.mounted && semantic.enabled && !stale && !active && !data.scan?.active;
  const available = data.execution.configured_provider !== "agent" || data.execution.local_executors.length > 0;
  byId("workflow-run-button").disabled = runningRequest || !allowed || !available || (flow.id === "fresh-eyes" && data.execution.configured_provider !== "agent");
  byId("workflow-run-button").textContent = active ? "Worker is running…" : `Start / resume ${flow.name.toLowerCase()}`;
  byId("workflow-scan").disabled = runningRequest || !data.execution.mounted || active || data.scan?.active;
  byId("workflow-run-title").textContent = flow.name;
  byId("workflow-run-note").textContent = flow.id === "patterns" ? flow.note : "Starts model calls on this server and resumes saved work. Existing requested reviews can also advance on the shared queue.";
  byId("workflow-fresh-options").hidden = flow.id !== "fresh-eyes";
  byId("workflow-execution-note").textContent = !data.execution.mounted ? "This repository is available for reading only."
    : !semantic.enabled ? "AI mapping is disabled in this repository's service policy."
      : flow.id === "fresh-eyes" && data.execution.configured_provider !== "agent" ? "Fresh eyes requires the repository's agent provider. Mapping and patterns can use the configured provider."
      : !available ? "No local Codex or Claude executor is installed on this server. A connected host worker can still process the saved queue."
        : "Saved work survives a page reload. After a server restart, resume unfinished work here. Configured stage models and usage limits still apply.";
  byId("workflow-message").textContent = worker.error || (semantic.budget?.paused || worker.paused ? "Work is paused at the configured usage limit. Saved results remain available."
    : data.scan?.active ? `Source scan: ${data.scan.phase || data.scan.status} · ${data.scan.completed || 0} files processed.`
    : stale ? "These results belong to the saved scan. Refresh the source scan before running more analysis."
      : active ? `Work is running for ${selectedRepository()?.name || "this repository"}. Progress updates automatically.`
        : semantic.jobs?.pending || semantic.jobs?.retry ? "Saved tasks are waiting. Start a worker to continue; queued tasks do not run by themselves."
          : `Saved scan ${data.snapshot_id ?? "not available"} · Select any step to explore its evidence and results.`);
}

function handleClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.openFlow || button.dataset.flow) {
    selectedFlow = button.dataset.openFlow || button.dataset.flow;
    selectedStep = "";
    if (button.dataset.openFlow) switchView("workflows");
    render();
  } else if (button.dataset.step) {
    selectedStep = button.dataset.step;
    render();
  } else if (button.dataset.workflowView) {
    switchView(button.dataset.workflowView);
  } else if (button.id === "workflow-refresh") {
    void loadWorkflows();
  } else if (button.id === "workflow-scan") {
    void startScan();
  }
}

async function startWorkflow(event) {
  event.preventDefault();
  if (!data || data.repository_id !== state.repositoryId || byId("workflow-run-button").disabled) return;
  const body = { repository_id: state.repositoryId, workflow: selectedFlow,
    executor: byId("workflow-executor").value, model: byId("workflow-model").value.trim(),
    reasoning_effort: byId("workflow-effort").value.trim(), parallel_jobs: Number(byId("workflow-parallel").value),
    proposal_count: Number(byId("workflow-proposals").value), goal: byId("workflow-goal").value.trim() || null,
    restart: byId("workflow-restart").checked };
  await runAction(() => request("/api/workflows/run", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  }));
}

async function startScan() {
  if (!data || data.repository_id !== state.repositoryId || byId("workflow-scan").disabled) return;
  await runAction(() => request(api("/api/scan"), { method: "POST" }));
}

async function runAction(action) {
  const repositoryId = state.repositoryId;
  runningRequest = true;
  render();
  try {
    const result = await action();
    if (repositoryId !== state.repositoryId) return;
    byId("workflow-restart").checked = false;
    toast(result.status === "already_running" ? "A worker is already processing this repository." : "Work started. Progress will appear in the flow.");
    await loadWorkflows();
  } catch (error) {
    if (repositoryId === state.repositoryId) toast(error.message, true);
  } finally {
    if (repositoryId === state.repositoryId) { runningRequest = false; render(); }
  }
}
