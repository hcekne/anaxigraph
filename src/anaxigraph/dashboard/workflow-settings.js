import { byId, escapeAttr, escapeHtml, state, toast } from "/assets/dashboard-core.js";

const drafts = new Map();
let editorKey = "";
let editorStep = null;
let editorData = null;
let saving = false;

export function setupStepSettings(save, run) {
  const editor = byId("workflow-step-settings");
  editor.addEventListener("input", rememberDraft);
  editor.addEventListener("change", event => {
    if (event.target.name === "provider") {
      const row = event.target.closest("fieldset");
      row.querySelector('[name="model"]').value = editorData.settings.models[event.target.value][0];
      row.querySelector('[name="reasoning_effort"]').value = "medium";
    }
    rememberDraft();
  });
  editor.addEventListener("click", event => {
    const action = event.target.closest("button")?.dataset.settingsAction;
    if (action) editRows(action, event.target.closest("button").dataset.index);
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
  return `Workers share distinct jobs. The combined limit is ${data.execution.max_parallel_jobs} workers; fewer run when less work is ready.`;
}

function workerRow(row, index, item, data) {
  const mode = item.mode;
  const name = mode === "sequence" ? `Pass ${index + 1}` : mode === "proposals" ? `Proposal ${String.fromCharCode(65 + index)}` : `Model ${index + 1}`;
  const choices = Object.values(data.settings.models).flat();
  return `<fieldset class="workflow-worker-row"><legend>${name}</legend><div class="workflow-fields">
    <label>Provider<select name="provider">${options(["codex", "claude"], row.provider, { codex: "OpenAI · Codex", claude: "Anthropic · Claude" })}</select></label>
    <label>Model<input name="model" value="${escapeAttr(row.model)}" list="workflow-model-options" required maxlength="200" autocomplete="off" /></label>
    <label>${mode === "parallel" ? "Parallel workers" : "Workers per result"}<input name="workers" type="number" min="1" max="${mode === "parallel" ? data.execution.max_parallel_jobs : 1}" value="${row.workers}" required ${mode !== "parallel" ? "readonly" : ""} /></label>
    <label>Reasoning effort<select name="reasoning_effort">${options(["", "low", "medium", "high", "xhigh", "max"], row.reasoning_effort, { "": "Model default" })}</select></label></div>
    ${index ? `<button type="button" class="secondary-button" data-settings-action="remove" data-index="${index}">Remove ${name.toLowerCase()}</button>` : ""}
    ${index === 0 ? `<datalist id="workflow-model-options">${choices.map(model => `<option value="${escapeAttr(model)}"></option>`).join("")}</datalist>` : ""}</fieldset>`;
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
