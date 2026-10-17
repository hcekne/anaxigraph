import { escapeAttr, escapeHtml, format } from "/assets/dashboard-core.js";
import { workflowState, statusLabels } from "/assets/workflow-model.js";

const number = value => format.format(Number(value || 0));
const diagrams = {
  mapping: { number: "01", columns: 4, handoff: "Validate + repair" },
  patterns: { number: "02", columns: 3, handoff: "Independent critique" },
  "fresh-eyes": { number: "03", columns: 4, handoff: "Apply mission + constraints" },
};

export function workflowTabs(flows, selected) {
  return flows.map(flow => `<button type="button" role="tab" id="workflow-tab-${flow.id}"
    aria-selected="${flow.id === selected}" aria-controls="workflow-panel" data-flow="${flow.id}">
    <span class="workflow-tab-number">${diagrams[flow.id].number}</span><span class="workflow-tab-copy">
    <strong>${escapeHtml(flow.name)}</strong><small>${statusLabels[workflowState(flow)]} · ${flow.steps.filter(item => item.status === "complete").length} / ${flow.steps.length} steps</small>
    </span><span class="workflow-tab-arrow" aria-hidden="true">→</span></button>`).join("");
}

export function workflowDiagram(flow, selectedStep) {
  const diagram = diagrams[flow.id];
  return `<div class="workflow-heading"><div>
    <h2><span>${diagram.number}</span> ${escapeHtml(flow.title)}</h2><p>${escapeHtml(flow.description)}</p></div>
    <span class="workflow-status ${workflowState(flow)}">${statusLabels[workflowState(flow)]}</span></div>
    ${modelLegend(flow)}
    <div class="workflow-canvas" data-columns="${diagram.columns}" data-handoff="${diagram.handoff}"><svg class="workflow-edges" aria-hidden="true"></svg>
    <ol class="workflow-nodes">${flow.steps.map((item, index) => nodeMarkup(item, index, selectedStep)).join("")}</ol></div>
    <p class="workflow-note">${escapeHtml(flow.note)}</p>
    <p class="workflow-explore-hint">Select a step to explore its evidence and results below. Progress updates as work is saved.</p>`;
}

function nodeMarkup(item, index, selectedStep) {
  const isSoftware = item.owner !== "AI worker";
  const models = item.plan?.map(worker => worker.model) || item.jobs.models || [];
  const palette = isSoftware ? "software" : models.length === 1 ? modelPalette(models[0]) : "model";
  const owner = isSoftware ? item.owner : models.length === 1 ? modelName(models[0]) : "Model work";
  const progress = item.total > 0 ? Math.min(100, item.done / item.total * 100) : item.status === "complete" ? 100 : 0;
  return `<li><article class="workflow-card ${palette}"><button type="button" class="workflow-node ${palette} ${item.status}${item.parallel ? " parallel" : ""}"
    data-step="${item.id}" aria-pressed="${selectedStep === item.id}" aria-controls="workflow-detail">
    <span class="workflow-node-top"><span class="workflow-number">${index + 1}</span>
    <span class="workflow-owner">${escapeHtml(owner)}</span></span>
    <strong>${escapeHtml(item.title)}</strong><span class="workflow-description">${escapeHtml(item.description)}</span>
    ${item.parallel ? parallelMarkup(item.stages) : ""}
    <span class="workflow-count">${number(item.done)}${item.total == null ? "" : ` / ${number(item.total)}`} <small>${escapeHtml(item.unit)}</small></span>
    <span class="workflow-track" aria-hidden="true"><i style="width:${progress}%"></i></span>
    <span class="workflow-node-bottom"><span class="workflow-status ${item.status}">${statusLabels[item.status]}</span>
    ${item.reused ? `<small>${number(item.reused)} reused</small>` : ""}</span>
    ${nextRunMarkup(item)}
    ${activeWorkers(item.jobs)}
    <span class="workflow-models">${modelLabels(item).map(name => `<span class="${modelPalette(name)}" title="${escapeAttr(name)}">${escapeHtml(name)}</span>`).join("")}</span>
    </button>${cardActions(item)}</article></li>`;
}

function activeWorkers(jobs) {
  return (jobs.workers || []).map(worker => `<small class="workflow-active-worker">Running now: ${number(worker.running)} × ${escapeHtml(worker.executor_model || worker.executor_id || "worker")}</small>`).join("");
}

function nextRunMarkup(item) {
  if (!item.plan) return item.owner === "AI worker" ? "" : '<span class="workflow-next-run"><b>No model needed</b><small>Handled by AnaxiGraph</small></span>';
  return `<span class="workflow-next-run"><b>Next run · ${item.customized ? "your settings" : "suggested"}</b>${item.plan.map((worker, index) => {
    const prefix = item.mode === "sequence" ? `Pass ${index + 1} · ` : item.mode === "proposals" ? `Proposal ${String.fromCharCode(65 + index)} · ` : "";
    const count = item.mode === "parallel" ? `${worker.workers} parallel worker${worker.workers === 1 ? "" : "s"}` : "1 worker";
    return `<span class="workflow-planned-model ${modelPalette(worker.model)}"><strong>${escapeHtml(prefix)}${worker.provider === "claude" ? "Anthropic" : "OpenAI"}</strong><span>${escapeHtml(modelName(worker.model))}</span><small>${count}</small></span>`;
  }).join("")}${item.mode === "sequence" ? "<small>Ordered passes · one runs at a time</small>" : ""}</span>`;
}

function cardActions(item) {
  if (item.plan) return `<div class="workflow-card-actions"><button type="button" data-configure-step="${item.id}">Configure</button><button type="button" data-run-step="${item.id}">Run step →</button></div>`;
  if (item.id === "scan") return '<div class="workflow-card-actions"><button type="button" data-run-scan>Refresh source scan</button></div>';
  if (["pattern_plan", "brief", "grounding"].includes(item.id)) return `<div class="workflow-card-actions"><button type="button" data-run-step="${item.id}">Run step →</button></div>`;
  return item.view ? `<div class="workflow-card-actions"><button type="button" data-workflow-view="${item.view}">Explore results →</button></div>` : "";
}

function parallelMarkup(stages = []) {
  return `<span class="workflow-proposal-lanes">${stages.map((item, index) => {
    const model = item.provenance?.executor_model || item.provenance?.model;
    return `<span class="${model ? modelPalette(model) : "model"}">
      <b>Proposal ${String.fromCharCode(65 + index)}</b><span>${escapeHtml(model ? modelName(model) : "Independent session")}</span>
      <small>${item.state === "current" ? "Saved proposal" : "Awaiting result"}</small></span>`;
  }).join("")}</span>`;
}

function modelLabels(item) {
  return item.jobs.models?.length ? item.jobs.models.map(model => `Saved: ${model}`) : [];
}

function modelPalette(name) {
  if (/claude|opus|sonnet|haiku/i.test(name)) return "opus";
  return /sol/i.test(name) ? "sol" : "model";
}

function modelName(name) {
  return name.replace(/^gpt-/i, "GPT-").replace(/-(luna|sol|astra|terra)$/i, (_, model) => ` ${model[0].toUpperCase()}${model.slice(1)}`)
    .replace(/^claude-(\w+)-(\d+)-(\d+)$/i, (_, model, major, minor) => `Claude ${model[0].toUpperCase()}${model.slice(1)} ${major}.${minor}`);
}

function modelLegend(flow) {
  const models = [...new Set(flow.steps.flatMap(item => item.plan?.map(worker => worker.model) || item.jobs.models || []))];
  const chips = models.map(model => `<span class="${modelPalette(model)}" title="${escapeAttr(model)}">${escapeHtml(modelName(model))}</span>`);
  if (flow.steps.some(item => item.owner === "AI worker" && !item.plan && !item.jobs.models?.length)) chips.push('<span class="model">Model work · model recorded when run</span>');
  return `<div class="workflow-legend" aria-label="Who does the work"><span class="software">AnaxiGraph code</span>${chips.join("")}</div>
    <p class="workflow-legend-note">Next-run choices appear on each card; saved results keep their recorded models. Arrows show how evidence feeds the next step.</p>`;
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
  const preferred = Number(canvas.dataset.columns);
  const columns = canvas.clientWidth >= 1000 ? preferred : canvas.clientWidth >= 580 ? 2 : 1;
  list.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
  nodes.forEach((node, index) => {
    const row = Math.floor(index / columns);
    node.style.gridRow = row + 1;
    node.style.gridColumn = row % 2 ? columns - index % columns : index % columns + 1;
  });
  const origin = canvas.getBoundingClientRect();
  const paths = nodes.slice(1).map((node, index) => connectionPaths(nodes[index], node, origin));
  const svg = canvas.querySelector("svg");
  svg.setAttribute("viewBox", `0 0 ${canvas.clientWidth} ${canvas.clientHeight}`);
  svg.innerHTML = `<defs><marker id="workflow-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M1 1 L7 4 L1 7"/></marker></defs>${paths.join("")}
    ${columns === preferred ? handoffLabel(nodes, preferred, origin, canvas.dataset.handoff) : ""}`;
}

function connectionPaths(fromNode, toNode, origin) {
  const from = fromNode.firstElementChild.getBoundingClientRect(), to = toNode.firstElementChild.getBoundingClientRect();
  if (fromNode.style.gridRow !== toNode.style.gridRow) {
    const x = from.left + from.width / 2 - origin.left;
    return `<path d="M${x},${from.bottom - origin.top + 4} V${to.top - origin.top - 5}"/>`;
  }
  const forward = to.left > from.left;
  const starts = connectionPorts(fromNode, from, forward, origin);
  const ends = connectionPorts(toNode, to, !forward, origin);
  const middle = ((forward ? from.right + to.left : from.left + to.right) / 2) - origin.left;
  return starts.flatMap(start => ends.map(end => `<path d="M${start.x},${start.y} H${middle} V${end.y} H${end.x}"/>`)).join("");
}

function connectionPorts(node, box, right, origin) {
  const lanes = [...node.querySelectorAll(".workflow-proposal-lanes > span")];
  const boxes = lanes.length ? lanes.map(lane => lane.getBoundingClientRect()) : [box];
  return boxes.map(rect => ({ x: (right ? rect.right + 4 : rect.left - 4) - origin.left, y: rect.top + rect.height / 2 - origin.top }));
}

function handoffLabel(nodes, columns, origin, label) {
  if (nodes.length <= columns) return "";
  const from = nodes[columns - 1].firstElementChild.getBoundingClientRect(), to = nodes[columns].firstElementChild.getBoundingClientRect();
  const x = from.left + from.width / 2 - origin.left - 14;
  const y = (from.bottom + to.top) / 2 - origin.top + 4;
  return `<text x="${x}" y="${y}" text-anchor="end">${escapeHtml(label)}</text>`;
}

export function overviewWorkflowLinks(flows) {
  return `<div><p class="eyebrow">Your repository, step by step</p><h2>See how the map comes together</h2>
    <p>Explore progress, inspect each handoff, and start optional reviews.</p></div>
    <div class="workflow-shortcuts">${flows.map(flow => `<button type="button" data-open-flow="${flow.id}">
    <strong>${escapeHtml(flow.name)} <span aria-hidden="true">→</span></strong>
    <span>${statusLabels[workflowState(flow)]} · ${flow.steps.filter(item => item.status === "complete").length} / ${flow.steps.length} steps</span></button>`).join("")}</div>`;
}
