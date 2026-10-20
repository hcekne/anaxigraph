import { api, byId, escapeHtml, request, selectedRepository, state, toast } from "/assets/dashboard-core.js";
import { switchView } from "/assets/navigation.js";
import { buildFlows } from "/assets/workflow-model.js";
import { drawWorkflowEdges, overviewWorkflowLinks, workflowDetail, workflowDiagram, workflowTabs } from "/assets/workflow-render.js";
import { closeStepDialog, hasUnsavedSettings, openStepDialog, renderStepSettings, resetStepSettings, setupStepDialog, setupStepSettings, stepDialogShell, updateStepDialog } from "/assets/workflow-settings.js";

let data = null;
let selectedFlow = "mapping";
let selectedStep = "scan";
let requestToken = 0;
let timer = null;
let runningRequest = false;
let startingStep = null;
const rememberedSteps = new Map();
let controlsRepository = null;
let observer;
let loadingState = "loading";

export function setupWorkflowsView() {
  const section = document.createElement("section");
  section.id = "view-workflows";
  section.className = "view";
  section.innerHTML = shell();
  byId("view-overview").after(section);
  const entry = document.createElement("article");
  entry.id = "workflow-entry";
  entry.className = "panel workflow-entry";
  byId("view-overview").prepend(entry);
  document.addEventListener("click", handleClick);
  byId("workflow-run-form").addEventListener("submit", startWorkflow);
  setupStepDialog();
  setupStepSettings(saveStepSettings, startStep, closeStepDialog, render);
  byId("workflow-tabs").addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...byId("workflow-tabs").children];
    const index = tabs.indexOf(document.activeElement);
    const offset = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
    const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs.at(-1) : tabs[(index + offset + tabs.length) % tabs.length];
    next.click();
    byId(next.id)?.focus();
  });
  window.addEventListener("anaxigraph:viewchange", ({ detail }) => {
    window.clearTimeout(timer);
    closeStepDialog();
    if (detail.name !== "workflows") return;
    selectedFlow = ["mapping", "patterns", "fresh-eyes"].includes(detail.flow) ? detail.flow : "mapping";
    selectedStep = "";
    if (loadingState !== "ready") showLoadingState(loadingState);
    render();
    if (state.repositoryId) void loadWorkflows();
  });
  byId("repository-select").addEventListener("change", clearWorkflows);
  observer = new ResizeObserver(() => drawWorkflowEdges(byId("workflow-diagram")?.querySelector(".workflow-canvas")));
  observer.observe(byId("workflow-diagram"));
}

function shell() {
  return `<div class="workflow-workspace"><aside class="workflow-sidebar" aria-labelledby="workflow-intro-title">
    <header class="workflow-intro"><p class="eyebrow">Your repository, illustrated</p>
    <h2 id="workflow-intro-title">See how the pieces fit together.</h2><p>Follow the evidence from source to map to fresh ideas.</p></header>
    <div id="workflow-tabs" class="workflow-tabs" role="tablist" aria-orientation="vertical" aria-label="Repository workflows"></div>
    <button id="workflow-refresh" type="button" class="secondary-button">Refresh progress</button></aside>
    <section id="workflow-panel" class="workflow-stage" role="tabpanel"><article id="workflow-diagram" class="panel workflow-diagram" aria-busy="true"></article></section>
    <aside id="workflow-run-controls" class="workflow-run-controls" aria-labelledby="workflow-run-title" hidden><article class="panel workflow-run">
    <p class="eyebrow">Run this workflow</p><h3 id="workflow-run-title">Mapping</h3>
    <p id="workflow-run-note"></p><p id="workflow-message" class="workflow-message" role="status">Reading repository progress…</p>
    <form id="workflow-run-form">${runFields()}
    <button id="workflow-run-button" class="button" type="submit">Start workflow</button>
    <button id="workflow-scan" class="secondary-button" type="button">Refresh source scan</button>
    <p id="workflow-execution-note" class="muted"></p>
    <details id="workflow-limits"><summary>Execution limits</summary><p></p></details>
    </form></article></aside></div>
    ${stepDialogShell()}<aside id="workflow-loading" class="workflow-loading" role="status" aria-live="polite" aria-atomic="true">
    <i class="workflow-load-spinner" aria-hidden="true"></i><div><strong id="workflow-loading-title">Loading repository map…</strong>
    <p id="workflow-loading-detail">Reading saved steps, file counts and worker activity.</p>
    <button id="workflow-load-retry" class="secondary-button" type="button" hidden>Retry loading</button></div></aside>`;
}

function runFields() {
  return `<div id="workflow-legacy-options" class="workflow-fields"><label>Executor<select id="workflow-executor"></select></label>
    <label>Worker model<input id="workflow-model" maxlength="200" placeholder="Model ID" autocomplete="off" /></label>
    <label>Reasoning effort<input id="workflow-effort" maxlength="40" placeholder="Executor default" /></label>
    <label>Parallel jobs<input id="workflow-parallel" type="number" min="1" max="64" value="2" /></label></div>
    <div id="workflow-fresh-options" hidden><label id="workflow-proposal-count">Independent proposals<select id="workflow-proposals"><option value="1">1 proposal</option><option value="2" selected>2 proposals</option><option value="3">3 proposals</option></select></label>
    <label>Review goal (optional)<input id="workflow-goal" maxlength="4000" placeholder="What should the review help improve?" /></label>
    <label class="workflow-check"><input id="workflow-restart" type="checkbox" /> Start a new review generation</label></div>
    <details id="workflow-routing"><summary>Model choices by stage</summary><div></div></details>`;
}

function clearWorkflows() {
  closeStepDialog();
  requestToken += 1;
  window.clearTimeout(timer);
  data = null;
  resetStepSettings();
  runningRequest = false;
  startingStep = null;
  byId("workflow-run-button").disabled = true;
  byId("workflow-entry").textContent = "Reading workflow progress for this repository…";
  byId("workflow-diagram").textContent = "";
  byId("workflow-tabs").textContent = "";
  byId("workflow-detail").textContent = "";
  byId("workflow-message").textContent = "Reading repository progress…";
  showLoadingState("loading");
}

function showLoadingState(status, message = "") {
  loadingState = status;
  const loading = status === "loading", failed = status === "error";
  const popup = byId("workflow-loading");
  popup.hidden = status === "ready";
  popup.classList.toggle("failed", failed);
  popup.querySelector(".workflow-load-spinner").hidden = !loading;
  byId("workflow-load-retry").hidden = !failed;
  byId("workflow-diagram").setAttribute("aria-busy", String(loading));
  byId("workflow-run-controls").hidden = !data;
  byId("workflow-refresh").disabled = loading && !!state.repositoryId;
  if (status === "ready") return;
  const title = { mapping: "repository map", patterns: "pattern analysis", "fresh-eyes": "fresh-eyes review" }[selectedFlow];
  byId("workflow-loading-title").textContent = failed ? "Couldn’t load workflow progress" : `Loading ${title}…`;
  const name = selectedRepository()?.name;
  byId("workflow-loading-detail").textContent = failed ? (message || byId("workflow-loading-detail").textContent) : `Reading saved steps, file counts and worker activity${name ? ` for ${name}` : ""}.`;
  byId("workflow-run-button").disabled = true;
  byId("workflow-scan").disabled = true;
  document.querySelectorAll("[data-run-step], [data-run-scan], [data-save-run]").forEach(button => { button.disabled = true; });
}

export function workflowRepositoryLoadFailed(error) {
  if (!data) showLoadingState("error", error.message);
}

export function resetWorkflowsView() {
  if (data?.repository_id !== state.repositoryId) clearWorkflows();
  void loadWorkflows(controlsRepository !== state.repositoryId);
}

async function loadWorkflows(resetControls = false, foreground = false) {
  const token = ++requestToken;
  const repositoryId = state.repositoryId;
  window.clearTimeout(timer);
  if (foreground || (!data && loadingState !== "error")) showLoadingState("loading");
  try {
    const value = await request(api("/api/workflows"));
    if (token !== requestToken || repositoryId !== state.repositoryId) return;
    retainRunningStep(value);
    const changed = repositoryResultsChanged(data, value);
    data = value;
    showLoadingState("ready");
    if (changed) { render(); await state.reloadRepository?.(); return; }
    if (resetControls || controlsRepository !== repositoryId) configureControls();
    render();
  } catch (error) {
    if (token === requestToken && repositoryId === state.repositoryId) {
      byId("workflow-message").textContent = `Progress is unavailable: ${error.message}`;
      if (!data || loadingState === "loading") showLoadingState("error", error.message);
    }
  } finally {
    if (token === requestToken && byId("view-workflows").classList.contains("active")) {
      window.clearTimeout(timer);
      timer = window.setTimeout(loadWorkflows, 3500);
    }
  }
}

function rememberStep(repositoryId, value) {
  rememberedSteps.set(repositoryId, value);
  const key = `anaxigraph.running-step.${repositoryId}`;
  try {
    if (value) window.sessionStorage.setItem(key, JSON.stringify(value));
    else window.sessionStorage.removeItem(key);
  } catch (_) { /* In-memory feedback still works when browser storage is disabled. */ }
}

function recalledStep(repositoryId) {
  if (!rememberedSteps.has(repositoryId)) {
    let value = null;
    try { value = JSON.parse(window.sessionStorage.getItem(`anaxigraph.running-step.${repositoryId}`)); }
    catch (_) { /* A reload can still use server-reported activity. */ }
    rememberedSteps.set(repositoryId, value);
  }
  return rememberedSteps.get(repositoryId);
}

function retainRunningStep(value) {
  const worker = value.semantic.worker || {};
  const active = ["queued", "running"].includes(worker.status);
  const previous = recalledStep(value.repository_id);
  const flow = buildFlows(value).find(item => item.id === worker.workflow);
  const liveStep = flow?.steps.find(item => item.jobs.running > 0)?.id;
  const step = worker.active_step || worker.step || liveStep;
  let current = null;
  if (active && step) current = { workflow: worker.workflow, step, snapshot_id: value.snapshot_id };
  else if (active && previous?.workflow === worker.workflow && previous?.snapshot_id === value.snapshot_id) current = previous;
  rememberStep(value.repository_id, current);
  // Older running services report the flow before they can report the active card.
  value.client_step = current?.step;
}

function repositoryResultsChanged(previous, current) {
  if (!previous) return false;
  return previous.snapshot_id !== current.snapshot_id ||
    (["queued", "running"].includes(previous.semantic.worker?.status) && !["queued", "running"].includes(current.semantic.worker?.status)) ||
    (previous.semantic.jobs?.running_live > 0 && !current.semantic.jobs?.running_live);
}

function configureControls() {
  const execution = data.execution;
  const agent = execution.configured_provider === "agent";
  const names = agent ? execution.local_executors : ["configured"];
  const retained = controlsRepository === state.repositoryId;
  const executor = byId("workflow-executor").value;
  byId("workflow-executor").innerHTML = names.map(name => `<option value="${name}">${escapeHtml(name === "configured" ? execution.configured_provider : name)}</option>`).join("");
  if (retained && names.includes(executor)) byId("workflow-executor").value = executor;
  const perStep = agent && !!data.settings;
  byId("workflow-legacy-options").hidden = perStep;
  byId("workflow-routing").hidden = perStep;
  byId("workflow-proposal-count").hidden = perStep;
  byId("workflow-model").disabled = !agent || perStep;
  byId("workflow-model").required = agent && !perStep;
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
  const flows = buildFlows(data, state.overview?.files || 0, startingStep);
  const flow = flows.find(item => item.id === selectedFlow);
  const current = flow.steps.find(item => item.id === selectedStep) || flow.steps[0];
  selectedStep = current.id;
  const focusStep = document.activeElement?.dataset.step;
  const focusTab = document.activeElement?.closest("#workflow-tabs") && document.activeElement.id;
  byId("workflow-tabs").innerHTML = workflowTabs(flows, selectedFlow);
  byId("workflow-panel").setAttribute("aria-labelledby", `workflow-tab-${selectedFlow}`);
  byId("workflow-diagram").innerHTML = workflowDiagram(flow, selectedStep);
  byId("workflow-detail").innerHTML = workflowDetail(current);
  updateStepDialog(current, flow.steps.indexOf(current), !!data.settings && !!current.plan);
  if (data.settings) renderStepSettings(current, data);
  byId("workflow-entry").innerHTML = overviewWorkflowLinks(flows);
  if (focusStep) document.querySelector(`[data-step="${focusStep}"]`)?.focus({ preventScroll: true });
  if (focusTab) byId(focusTab)?.focus({ preventScroll: true });
  drawWorkflowEdges(byId("workflow-diagram").querySelector(".workflow-canvas"));
  renderControls(flow);
}

function renderControls(flow) {
  const { active, stale, allowed, available, unsupported } = executionState(flow);
  byId("workflow-run-button").disabled = runningRequest || !allowed || !available || unsupported;
  byId("workflow-run-button").textContent = active ? "Worker is running…" : flow.update ? "Update affected work" : `Start / resume ${flow.name.toLowerCase()}`;
  byId("workflow-scan").disabled = loadingState !== "ready" || runningRequest || !data.execution.mounted || active || data.scan?.active;
  byId("workflow-run-title").textContent = flow.name;
  byId("workflow-run-note").textContent = flow.id === "patterns" ? flow.note : "Starts model calls on this server and resumes saved work. Existing requested reviews can also advance on the shared queue.";
  if (data.settings) byId("workflow-run-note").textContent = "Runs the remaining steps in this flow using each card’s saved choices. Completed work is reused. Single-step buttons run only that step.";
  if (flow.update) byId("workflow-run-note").textContent = `${flow.update.summary} Starts with ${flow.update.nextTitle.toLowerCase()}, then checks the dependent steps.`;
  byId("workflow-fresh-options").hidden = flow.id !== "fresh-eyes";
  byId("workflow-execution-note").textContent = executionNote(available, unsupported);
  byId("workflow-limits").querySelector("p").textContent = executionLimits();
  byId("workflow-message").textContent = progressMessage(active, stale);
  updateStepButtons({ active, allowed, unsupported });
}

function updateStepButtons({ active, allowed, unsupported }) {
  document.querySelectorAll("[data-run-step]").forEach(button => { button.disabled = runningRequest || !allowed || unsupported; });
  document.querySelectorAll("[data-run-scan]").forEach(button => { button.disabled = byId("workflow-scan").disabled; });
  byId("workflow-step-settings").querySelectorAll("input, select, button").forEach(input => {
    input.disabled = !data.execution.mounted;
    if (input.dataset.saveRun != null) input.disabled ||= runningRequest || !allowed || unsupported;
  });
}

function executionState(flow) {
  const semantic = data.semantic;
  const active = ["queued", "running"].includes(semantic.worker?.status) || semantic.jobs?.running_live > 0;
  const stale = semantic.map_status?.state !== "current";
  const prerequisite = data.settings && flow.id !== "mapping" && semantic.architecture_charter?.status !== "current";
  const allowed = loadingState === "ready" && data.execution.mounted && semantic.enabled && !stale && !active && !data.scan?.active && !prerequisite;
  const available = data.execution.configured_provider !== "agent" || data.execution.local_executors.length > 0;
  const unsupported = flow.id === "fresh-eyes" && data.execution.configured_provider !== "agent";
  return { active, stale, allowed, available, unsupported };
}

function executionNote(available, unsupported) {
  return !data.execution.mounted ? "This repository is available for reading only."
    : !data.semantic.enabled ? "AI mapping is disabled in this repository's service policy."
      : unsupported ? "Fresh eyes requires the repository's agent provider. Mapping and patterns can use the configured provider."
      : !available ? "No local Codex or Claude executor is installed on this server. A connected host worker can still process the saved queue."
        : data.settings ? `Host workers: ${data.execution.local_executors.join(" + ")}. Card settings select the models. Complete Mapping before starting optional reviews.`
        : "Saved work survives a page reload. After a server restart, resume unfinished work here. Configured stage models and usage limits still apply.";
}

function executionLimits() {
  const policy = data.semantic.semantic_policy || {};
  const parallel = policy.max_parallel_jobs ?? data.execution.max_parallel_jobs;
  const attempts = policy.max_attempts;
  const timeout = policy.timeout_seconds == null ? "No AnaxiGraph model time limit" : `${policy.timeout_seconds}s per model call`;
  const output = policy.max_output_tokens == null ? "provider default output capacity" : `${policy.max_output_tokens} output tokens per call`;
  const retryOutput = policy.max_output_tokens_on_retry == null ? "" : `; ${policy.max_output_tokens_on_retry} output tokens on retry`;
  const budget = policy.daily_budget_usd == null ? "no daily spending cap" : `$${policy.daily_budget_usd} daily spending cap`;
  return `${parallel} parallel workers shared by this repository. ${attempts == null ? "Failed jobs follow the repository retry policy." : `Up to ${attempts} attempts per failed job, then an explicit retry is required.`} ${timeout}; ${output}${retryOutput}; ${budget}. Run Step continues until the selected work finishes or a reported error needs attention. Active leases renew automatically. Provider account and model limits still apply.`;
}

function progressMessage(active, stale) {
  const semantic = data.semantic;
  const worker = semantic.worker || {};
  return worker.error || (semantic.budget?.paused || worker.paused ? "Work is paused at the configured usage limit. Saved results remain available."
    : data.scan?.active ? `Source scan: ${data.scan.phase || data.scan.status} · ${data.scan.completed || 0} files processed.`
    : stale ? "These results belong to the saved scan. Refresh the source scan before running more analysis."
      : stepIsFinishing(active) ? "All results for this step are saved. Finishing the run…"
      : active ? `Work is running for ${selectedRepository()?.name || "this repository"}. Progress updates automatically.`
        : idleMessage(semantic));
}

function stepIsFinishing(active) {
  const step = data.semantic.worker?.step;
  return active && step && !data.semantic.jobs?.running_live
    && buildFlows(data).flatMap(flow => flow.steps).some(item => item.id === step && item.status === "complete");
}

function idleMessage(semantic) {
  const worker = semantic.worker || {};
  if (worker.message) return `${worker.message} ${worker.processed || 0} jobs processed in the last run.`;
  return semantic.jobs?.pending || semantic.jobs?.retry ? "Saved tasks are waiting. Start a worker to continue; queued tasks do not run by themselves."
    : `Saved scan ${data.snapshot_id ?? "not available"} · Select any step to explore its evidence and results.`;
}

function handleClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.openFlow || button.dataset.flow) {
    selectedFlow = button.dataset.openFlow || button.dataset.flow;
    selectedStep = "";
    switchView("workflows", false, selectedFlow);
  } else if (button.dataset.step || button.dataset.configureStep || button.dataset.progressStep) {
    selectedStep = button.dataset.step || button.dataset.configureStep || button.dataset.progressStep;
    render();
    openStepDialog(selectedStep, !!button.dataset.configureStep);
  } else if (button.dataset.runStep) {
    void startStep(button.dataset.runStep);
  } else if (button.dataset.workflowView) {
    closeStepDialog();
    switchView(button.dataset.workflowView);
  } else if (button.id === "workflow-focus") {
    byId("workflow-diagram").scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (["workflow-refresh", "workflow-load-retry"].includes(button.id)) {
    if (state.repositoryId) void loadWorkflows(false, true);
    else window.location.reload();
  } else if (button.id === "workflow-scan" || button.dataset.runScan != null) {
    void startScan();
  }
}

async function startWorkflow(event) {
  event.preventDefault();
  if (!data || data.repository_id !== state.repositoryId || byId("workflow-run-button").disabled) return;
  if (data.settings && data.execution.configured_provider === "agent") { await startStep(); return; }
  const body = { repository_id: state.repositoryId, workflow: selectedFlow,
    executor: byId("workflow-executor").value, model: byId("workflow-model").value.trim(),
    reasoning_effort: byId("workflow-effort").value.trim(), parallel_jobs: Number(byId("workflow-parallel").value),
    proposal_count: Number(byId("workflow-proposals").value), goal: byId("workflow-goal").value.trim() || null,
    restart: byId("workflow-restart").checked };
  await runAction(() => request("/api/workflows/run", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  }));
}

async function saveStepSettings(step, workers, repositoryId) {
  const result = await request("/api/workflows/settings", { method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ repository_id: repositoryId, step, workers }) });
  if (repositoryId !== state.repositoryId) return;
  data.settings = result.settings;
  render();
}

async function startStep(step = null, maxJobs = null) {
  if (!data || data.repository_id !== state.repositoryId) return;
  if (hasUnsavedSettings()) { toast("Save the pending step settings before starting work.", true); return; }
  const flow = buildFlows(data).find(item => step ? item.steps.some(candidate => candidate.id === step) : item.id === selectedFlow);
  if (!executionState(flow).allowed || runningRequest) return;
  await runAction(() => request("/api/workflows/run", { method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ repository_id: state.repositoryId, workflow: flow.id,
      use_step_settings: true, step, max_jobs: maxJobs,
      goal: byId("workflow-goal").value.trim() || null, restart: byId("workflow-restart").checked }) }), step, flow.id);
}

async function startScan() {
  if (!data || data.repository_id !== state.repositoryId || byId("workflow-scan").disabled) return;
  await runAction(() => request(api("/api/scan"), { method: "POST" }), "scan");
}

async function runAction(action, step = null, workflow = selectedFlow) {
  const repositoryId = state.repositoryId;
  const snapshotId = data.snapshot_id;
  runningRequest = true;
  startingStep = step;
  render();
  try {
    const result = await action();
    if (result.status === "started" && step && step !== "scan") {
      rememberStep(repositoryId, { workflow, step, snapshot_id: snapshotId });
    }
    if (repositoryId !== state.repositoryId) return;
    byId("workflow-restart").checked = false;
    toast(result.status === "already_running" ? "A worker is already processing this repository." : "Work started. Progress will appear in the flow.");
    await loadWorkflows();
  } catch (error) {
    if (repositoryId === state.repositoryId) toast(error.message, true);
  } finally {
    if (repositoryId === state.repositoryId) { runningRequest = false; startingStep = null; render(); }
  }
}
