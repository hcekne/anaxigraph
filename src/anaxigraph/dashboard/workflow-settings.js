import { byId, escapeAttr, escapeHtml, state, toast } from "/assets/dashboard-core.js";

const drafts = new Map();
let editorKey = "";
let editorStep = null;
let editorData = null;
let saving = false;

export function setupStepSettings(save, run, saved, changed) {
  const editor = byId("workflow-step-settings");
  editor.addEventListener("input", rememberDraft);
  editor.addEventListener("change", event => {
    if (event.target.name === "provider") {
      const row = event.target.closest("fieldset");
      const provider = event.target.value;
      row.querySelector('[name="model"]').innerHTML = options(editorData.settings.models[provider], "");
      row.querySelector('[name="reasoning_effort"]').innerHTML = options(efforts(provider), "medium", { "": "Model default" });
    }
    rememberDraft();
  });
  editor.addEventListener("click", event => {
    const action = event.target.closest("button")?.dataset.settingsAction;
    if (action) {
      editRows(action, event.target.closest("button").dataset.index);
      changed();
    }
  });
  editor.addEventListener("submit", async event => {
    event.preventDefault();
    if (saving) return;
    const repositoryId = state.repositoryId, step = editorStep.id, key = editorKey;
    const workers = readWorkers();
    saving = true;
    try {
      await save(step, workers, repositoryId);
      drafts.delete(key);
      if (repositoryId !== state.repositoryId) return;
      renderStepSettings(editorStep, editorData, true);
      toast("Step settings saved.");
      saved();
      if (event.submitter?.dataset.saveRun != null) await run(step, Number(event.submitter.dataset.jobLimit) || null);
    } catch (error) {
      if (repositoryId === state.repositoryId) toast(error.message, true);
    } finally { saving = false; }
  });
}

export function resetStepSettings() { editorKey = ""; }

export function hasUnsavedSettings() {
  return [...drafts.keys()].some(key => key.startsWith(`${state.repositoryId}:`));
}

export function renderStepSettings(item, data, force = false) {
  const key = `${data.repository_id}:${item.id}`;
  editorStep = item;
  editorData = data;
  if (key === editorKey && !force) return;
  editorKey = key;
  const element = byId("workflow-step-settings");
  if (!item.plan) {
    element.innerHTML = `<p class="eyebrow">Selected step · ${escapeHtml(item.title)}</p><p>This step uses AnaxiGraph code. No provider, model or AI workers are needed.</p>`;
    return;
  }
  const rows = drafts.get(key) || data.settings.steps[item.id];
  const rowLimit = item.mode === "sequence" ? Math.min(3, data.semantic.taxonomy?.required_review_passes ?? 2) : 3;
  element.innerHTML = `<p class="eyebrow">Configure this step</p><h3>${escapeHtml(item.title)}</h3>
    <p>${modeDescription(item.mode, data)}</p><form id="workflow-step-form">
    <div class="workflow-worker-rows">${rows.map((row, index) => workerRow(row, index, item, data)).join("")}</div>
    <div class="workflow-settings-actions">${item.mode !== "single" && rows.length < rowLimit ? '<button type="button" class="secondary-button" data-settings-action="add">Add model</button>' : ""}
    <button type="button" class="secondary-button" data-settings-action="suggested">Use suggested</button></div>
    <p id="workflow-settings-status" class="muted" role="status">${drafts.has(key) ? "Unsaved changes" : "These choices apply to the next run. Saved results are kept."}</p>
    <div class="workflow-settings-actions"><button class="secondary-button" type="submit">Save settings</button>
    <button class="button" type="submit" data-save-run>Save &amp; run step →</button>
    ${item.mode === "parallel" ? '<button class="secondary-button" type="submit" data-save-run data-job-limit="2">Try 2 jobs</button>' : ""}</div></form>`;
}

function modeDescription(mode, data) {
  if (mode === "sequence") return `${data.semantic.taxonomy?.required_review_passes ?? 2} ordered passes. Models run in this order, repeating if needed; only one pass runs at a time.`;
  if (mode === "proposals") return `One independent proposal per model row. Up to ${Math.min(3, data.execution.max_parallel_jobs)} proposals can run together. A different slot count or provider assignment requires a new review generation.`;
  if (mode === "single") return "One model produces this result after the preceding steps are ready.";
  return `Workers take the next file as soon as they finish. The combined limit is ${data.execution.max_parallel_jobs}. If a model becomes unavailable, the other selected models continue the remaining files.`;
}

function workerRow(row, index, item, data) {
  const mode = item.mode;
  const name = mode === "sequence" ? `Pass ${index + 1}` : mode === "proposals" ? `Proposal ${String.fromCharCode(65 + index)}` : `Model ${index + 1}`;
  const choices = data.settings.models[row.provider] || [];
  const invalid = !choices.includes(row.model);
  return `<fieldset class="workflow-worker-row"><legend>${name}</legend><div class="workflow-fields">
    <label>Provider<select name="provider">${options(["codex", "claude"], row.provider, { codex: "OpenAI · Codex", claude: "Anthropic · Claude" })}</select></label>
    <label>Model<select name="model" required>${invalid ? '<option value="" disabled selected>Choose a supported model</option>' : ""}${options(choices, row.model)}</select></label>
    <label>${mode === "parallel" ? "Parallel workers" : "Workers per result"}<input name="workers" type="number" min="1" max="${mode === "parallel" ? data.execution.max_parallel_jobs : 1}" value="${row.workers}" required ${mode !== "parallel" ? "readonly" : ""} /></label>
    <label>Reasoning effort<select name="reasoning_effort">${options(efforts(row.provider), row.reasoning_effort, { "": "Model default" })}</select></label></div>
    ${invalid ? `<p class="workflow-error">Saved model ${escapeHtml(row.model)} is unavailable. Choose a model before running.</p>` : ""}
    ${index ? `<button type="button" class="secondary-button" data-settings-action="remove" data-index="${index}">Remove ${name.toLowerCase()}</button>` : ""}</fieldset>`;
}

function efforts(provider) {
  return provider === "claude" ? ["", "low", "medium", "high", "max"] : ["", "low", "medium", "high", "xhigh", "max"];
}

function options(values, selected, labels = {}) {
  return values.map(value => `<option value="${escapeAttr(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(labels[value] || value)}</option>`).join("");
}

function readWorkers() {
  return [...byId("workflow-step-settings").querySelectorAll("fieldset")].map(row => ({
    provider: row.querySelector('[name="provider"]').value,
    model: row.querySelector('[name="model"]').value.trim(),
    workers: Number(row.querySelector('[name="workers"]').value),
    reasoning_effort: row.querySelector('[name="reasoning_effort"]').value,
  }));
}

function rememberDraft() {
  if (!editorStep?.plan) return;
  drafts.set(editorKey, readWorkers());
  byId("workflow-settings-status").textContent = "Unsaved changes · save before running";
}

function editRows(action, index) {
  let rows = readWorkers();
  if (action === "suggested") rows = structuredClone(editorData.settings.suggested[editorStep.id]);
  if (action === "remove") rows.splice(Number(index), 1);
  if (action === "add" && rows.length < 3) rows.push({ provider: "claude", model: "claude-opus-5-5", workers: 1, reasoning_effort: "medium" });
  drafts.set(editorKey, rows);
  renderStepSettings(editorStep, editorData, true);
}

let returnFocus = null;

export function stepDialogShell() {
  return `<dialog id="workflow-step-dialog" class="workflow-dialog" aria-labelledby="workflow-dialog-title">
    <header class="workflow-dialog-header"><h2 id="workflow-dialog-title">Step details</h2>
    <button id="workflow-dialog-close" type="button" class="secondary-button" aria-label="Close step details">Close ✕</button></header>
    <div class="workflow-dialog-tabs" role="tablist" aria-label="Step information">
    <button id="workflow-details-tab" type="button" role="tab" data-step-panel="details" aria-controls="workflow-detail" aria-selected="true">Progress &amp; models</button>
    <button id="workflow-configure-tab" type="button" role="tab" data-step-panel="configure" aria-controls="workflow-step-settings" aria-selected="false" tabindex="-1">Configure</button></div>
    <div class="workflow-dialog-body"><section id="workflow-detail" class="workflow-detail" role="tabpanel" aria-labelledby="workflow-details-tab"></section>
    <section id="workflow-step-settings" class="workflow-run" role="tabpanel" aria-labelledby="workflow-configure-tab" hidden></section></div></dialog>`;
}

export function setupStepDialog() {
  const dialog = byId("workflow-step-dialog");
  byId("workflow-dialog-close").addEventListener("click", closeStepDialog);
  dialog.addEventListener("keydown", containDialogFocus);
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeStepDialog();
    }
    const tab = event.target.closest("[data-step-panel]");
    if (tab) selectPanel(tab.dataset.stepPanel);
  });
  dialog.querySelector('[role="tablist"]').addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...dialog.querySelectorAll('[role="tab"]')].filter(tab => !tab.hidden);
    const index = tabs.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + 1) % tabs.length;
    tabs[next].click();
    tabs[next].focus();
  });
  dialog.addEventListener("close", () => {
    if (returnFocus) document.querySelector(returnFocus)?.focus({ preventScroll: true });
  });
}

function containDialogFocus(event) {
  if (event.key !== "Tab") return;
  const controls = [...event.currentTarget.querySelectorAll("button, input, select, textarea, a[href], [tabindex]")]
    .filter(control => !control.disabled && control.tabIndex >= 0 && control.getClientRects().length);
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

function selectPanel(panel) {
  const configure = panel === "configure" && !byId("workflow-configure-tab").hidden;
  byId("workflow-detail").hidden = configure;
  byId("workflow-step-settings").hidden = !configure;
  for (const tab of byId("workflow-step-dialog").querySelectorAll('[role="tab"]')) {
    const selected = (tab.dataset.stepPanel === "configure") === configure;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
}

export function openStepDialog(step, configure = false) {
  returnFocus = `[data-${configure ? "configure-step" : "step"}="${step}"]`;
  selectPanel(configure ? "configure" : "details");
  byId("workflow-step-dialog").showModal();
}

export function updateStepDialog(item, index, configurable) {
  byId("workflow-dialog-title").textContent = `${index + 1}. ${item.title}`;
  byId("workflow-configure-tab").hidden = !configurable;
  if (!configurable) selectPanel("details");
}

export function closeStepDialog() {
  byId("workflow-step-dialog").close();
}
