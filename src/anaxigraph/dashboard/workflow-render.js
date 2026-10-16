import { escapeAttr, escapeHtml, format } from "/assets/dashboard-core.js";
import { workflowState, statusLabels } from "/assets/workflow-model.js";

const number = value => format.format(Number(value || 0));

export function workflowTabs(flows, selected) {
  return flows.map(flow => `<button type="button" role="tab" id="workflow-tab-${flow.id}"
    aria-selected="${flow.id === selected}" aria-controls="workflow-panel" data-flow="${flow.id}">
    <span>${escapeHtml(flow.name)}</span><small>${statusLabels[workflowState(flow)]}</small></button>`).join("");
}

export function workflowDiagram(flow, selectedStep) {
  return `<div class="workflow-heading"><div><p class="eyebrow">How the pieces fit together</p>
    <h2>${escapeHtml(flow.title)}</h2><p>${escapeHtml(flow.description)}</p></div>
    <span class="workflow-status ${workflowState(flow)}">${statusLabels[workflowState(flow)]}</span></div>
    <div class="workflow-canvas"><svg class="workflow-edges" aria-hidden="true"></svg>
    <ol class="workflow-nodes">${flow.steps.map((item, index) => nodeMarkup(item, index, selectedStep)).join("")}</ol></div>
    <p class="workflow-note">${escapeHtml(flow.note)}</p>`;
}

function nodeMarkup(item, index, selectedStep) {
  const isSoftware = item.owner !== "AI worker";
  const progress = item.total > 0 ? Math.min(100, item.done / item.total * 100) : item.status === "complete" ? 100 : 0;
  return `<li><button type="button" class="workflow-node ${isSoftware ? "software" : "model"} ${item.status}"
    data-step="${item.id}" aria-pressed="${selectedStep === item.id}" aria-controls="workflow-detail">
    <span class="workflow-node-top"><span class="workflow-number">${index + 1}</span>
    <span class="workflow-owner">${escapeHtml(item.owner)}</span></span>
    <strong>${escapeHtml(item.title)}</strong><span class="workflow-description">${escapeHtml(item.description)}</span>
    ${item.parallel ? parallelMarkup(item.stages) : ""}
    <span class="workflow-count">${number(item.done)}${item.total == null ? "" : ` / ${number(item.total)}`} <small>${escapeHtml(item.unit)}</small></span>
    <span class="workflow-track" aria-hidden="true"><i style="width:${progress}%"></i></span>
    <span class="workflow-node-bottom"><span class="workflow-status ${item.status}">${statusLabels[item.status]}</span>
    ${item.reused ? `<small>${number(item.reused)} reused</small>` : ""}</span>
    <span class="workflow-models">${modelLabels(item).map(name => `<span title="${escapeAttr(name)}">${escapeHtml(name)}</span>`).join("")}</span>
    </button></li>`;
}

function parallelMarkup(stages = []) {
  return `<span class="workflow-proposal-lanes">${stages.map((item, index) => `<span>
    <b>${String.fromCharCode(65 + index)}</b>${escapeHtml(item.provenance?.executor_model || item.provenance?.model || "Independent session")}</span>`).join("")}</span>`;
}

function modelLabels(item) {
  return item.jobs.models?.length ? item.jobs.models : item.owner === "AI worker" ? ["Model recorded when run"] : [];
}

export function workflowDetail(item) {
  const jobs = item.jobs;
  const hasUsage = jobs.input_tokens != null;
  const telemetry = hasUsage ? `<dl class="workflow-facts">
    <div><dt>Completed model jobs</dt><dd>${number(jobs.completed)}</dd></div>
    <div><dt>Running now</dt><dd>${number(jobs.running)}</dd></div>
    <div><dt>Input tokens</dt><dd>${number(jobs.input_tokens)}</dd></div>
    <div><dt>Output tokens</dt><dd>${number(jobs.output_tokens)}</dd></div>
    </dl><p class="muted">Job totals can include repeated work. File coverage above counts current saved descriptions.
    ${jobs.token_counts_missing ? `${number(jobs.token_counts_missing)} completed jobs have unknown token usage.` : ""}</p>` : "";
  return `<div class="workflow-detail-heading"><div><p class="eyebrow">Selected step</p>
    <h3>${escapeHtml(item.title)}</h3></div><span class="workflow-status ${item.status}">${statusLabels[item.status]}</span></div>
    <p>${escapeHtml(item.detail || item.description)}</p>
    ${item.jobs.models?.length ? `<p><strong>Recorded models:</strong> ${item.jobs.models.map(escapeHtml).join(", ")}</p>` : ""}
    ${item.reused ? `<p>${number(item.reused)} current results were reused from an earlier scan.</p>` : ""}
    ${telemetry}${stageDetails(item.stages)}
    ${(jobs.errors || []).map(error => `<p class="workflow-error"><strong>Recorded failure · ${escapeHtml(error.scope_key)}</strong><br>${escapeHtml(error.error)}</p>`).join("")}
    ${item.view ? `<button type="button" class="secondary-button" data-workflow-view="${item.view}">Explore ${item.view === "overview" ? "the Charter" : item.view === "fresh-eyes" ? "review results" : item.view} →</button>` : ""}`;
}

function stageDetails(stages = []) {
  if (!stages.length) return "";
  return `<div class="workflow-stage-records">${stages.map(item => `<article><strong>${escapeHtml(item.label || item.key)}</strong>
    <p>${escapeHtml(item.provenance?.executor_model || item.provenance?.model || "No model result saved yet")}</p>
    <p>${escapeHtml(item.reason || "Waiting to start")}</p>
    ${item.required_executor ? `<p>Required executor: ${escapeHtml(item.required_executor)}</p>` : ""}
    ${item.telemetry?.token_counts_reported ? `<small>${number(item.telemetry.input_tokens)} input / ${number(item.telemetry.output_tokens)} output tokens</small>` : ""}
    </article>`).join("")}</div>`;
}

export function drawWorkflowEdges(canvas) {
  if (!canvas || !canvas.offsetWidth) return;
  const list = canvas.querySelector("ol");
  const nodes = [...list.children];
  const columns = canvas.clientWidth >= 1000 ? 4 : canvas.clientWidth >= 580 ? 2 : 1;
  list.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
  nodes.forEach((node, index) => {
    const row = Math.floor(index / columns);
    node.style.gridRow = row + 1;
    node.style.gridColumn = row % 2 ? columns - index % columns : index % columns + 1;
  });
  const origin = canvas.getBoundingClientRect();
  const boxes = nodes.map(node => node.getBoundingClientRect());
  const paths = boxes.slice(1).map((box, index) => {
    const from = boxes[index];
    const sameRow = Math.abs(from.top - box.top) < 2;
    const forward = box.left > from.left;
    const x1 = sameRow ? (forward ? from.right : from.left) : from.left + from.width / 2;
    const y1 = sameRow ? from.top + from.height / 2 : from.bottom;
    const x2 = sameRow ? (forward ? box.left : box.right) : box.left + box.width / 2;
    const y2 = sameRow ? box.top + box.height / 2 : box.top;
    return `<path d="M${x1 - origin.left},${y1 - origin.top} L${x2 - origin.left},${y2 - origin.top}"/>`;
  });
  const svg = canvas.querySelector("svg");
  svg.setAttribute("viewBox", `0 0 ${canvas.clientWidth} ${canvas.clientHeight}`);
  svg.innerHTML = `<defs><marker id="workflow-arrow" markerWidth="8" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M1 1 L5 4 L1 7"/></marker></defs>${paths.join("")}`;
}

export function overviewWorkflowLinks(flows) {
  return `<div><p class="eyebrow">Your repository, step by step</p><h2>See how the map comes together</h2>
    <p>Explore progress, inspect each handoff, and start optional reviews.</p></div>
    <div class="workflow-shortcuts">${flows.map(flow => `<button type="button" data-open-flow="${flow.id}">
    <strong>${escapeHtml(flow.name)} <span aria-hidden="true">→</span></strong>
    <span>${statusLabels[workflowState(flow)]} · ${flow.steps.filter(item => item.status === "complete").length} / ${flow.steps.length} steps</span></button>`).join("")}</div>`;
}
